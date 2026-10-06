"""Owner-scoped comparisons and public, evidence-derived discovery."""

import json
import statistics

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from backend.adaptive.models import Blueprint, Program
from backend.assistance.service import AssistantService


def build(adaptive, payload):
    assistant = AssistantService(adaptive.s)
    if assistant.provider != "Gemini":
        raise HTTPException(
            409,
            "Configure Gemini to generate a strategy proposal; manual editing and Pine import remain available",
        )
    schema = {
        "type": "object",
        "properties": {
            "program": Program.model_json_schema(),
            "explanation": {"type": "string"},
            "questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["program", "explanation", "questions"],
        "additionalProperties": False,
    }
    try:
        with httpx.Client(timeout=45, follow_redirects=False) as client:
            response = assistant.gemini_request(
                client,
                {
                    "systemInstruction": {
                        "parts": [
                            {
                                "text": "Translate intent into one supported deterministic trading program. Return a proposal, never promise profit or claim execution. Supported: momentum, mean_reversion, sma_cross, ema_cross. Do not invent unavailable indicators or external data. If intent cannot be represented, retain the draft program and explain the unsupported requirements in questions. Never change risk, market, funds or fees. Respond in the user language."
                            }
                        ]
                    },
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "intent": payload.intent,
                                            "draft_program": payload.draft.program.model_dump(),
                                        }
                                    )
                                }
                            ],
                        }
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseJsonSchema": schema,
                        "maxOutputTokens": 4096,
                    },
                },
            )
            response.raise_for_status()
            candidate = response.json()["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise ValueError("Incomplete proposal")
            result = json.loads(
                "".join(p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought"))
            )
        program = Program.model_validate(result["program"])
        if not isinstance(result.get("questions"), list) or not all(
            isinstance(x, str) for x in result["questions"]
        ):
            raise ValueError("Invalid questions")
        proposal = payload.draft.model_dump() | {
            "program": program.model_dump(),
            "intent": payload.intent,
            "pine_source": None,
        }
        Blueprint.model_validate(proposal)
        return {
            "proposal": proposal,
            "explanation": str(result["explanation"])[:4000],
            "questions": result["questions"][:10],
            "changes": [
                {"field": "program." + k, "before": getattr(payload.draft.program, k), "after": v}
                for k, v in program.model_dump().items()
                if getattr(payload.draft.program, k) != v
            ],
            "provider": "Gemini",
            "requires_review": True,
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError, ValidationError) as exc:
        raise HTTPException(503, "AI proposal unavailable or invalid; your draft was not changed") from exc


def compare(adaptive, first, second, owner_id):
    a, b = [adaptive.get(i, owner_id) for i in (first, second)]
    if first == second or not a["source_bundle"] or a["source_bundle"] != b["source_bundle"]:
        raise HTTPException(422, "Choose two distinct instances of the same Bundle")
    return {
        "source_bundle": a["source_bundle"],
        "agents": [
            {
                "agent_id": x["agent_id"],
                "name": x["name"],
                "evolution": adaptive.learning.evolution(x["agent_id"], owner_id),
            }
            for x in (a, b)
        ],
        "note": "Different outcomes may produce different policies. Identical evidence can produce identical learning; divergence is not a success criterion.",
    }


def catalog(adaptive):
    items = []
    with adaptive.db.connect() as conn:
        rows = conn.execute(
            "SELECT b.bundle_id,b.owner_id,b.body,u.name FROM adaptive_bundles b JOIN users u ON u.user_id=b.owner_id WHERE b.listed=1 ORDER BY b.created_at DESC LIMIT 100"
        ).fetchall()
        for r in rows:
            body = adaptive.checked(json.loads(r["body"]))
            items.append(
                {
                    "id": r["bundle_id"],
                    "kind": "bundle",
                    "name": body["name"],
                    "market": body["strategy_apr"]["blueprint"]["market"],
                    "creator_id": r["owner_id"],
                    "creator_name": r["name"],
                    "revision": body["revision"],
                    "url": "/bundles/" + r["bundle_id"],
                    "gate_passed": body["evidence"]["body"]["gate"]["passed"],
                }
            )
        rows = conn.execute(
            "SELECT s.strategy_id,s.owner_id,s.name,s.version,u.name AS creator FROM strategies s JOIN users u ON u.user_id=s.owner_id WHERE s.listed=1 ORDER BY s.updated_at DESC LIMIT 100"
        ).fetchall()
        for r in rows:
            body = adaptive.s.get(r["strategy_id"], public=True, conn=conn)
            items.append(
                {
                    "id": r["strategy_id"],
                    "kind": "strategy",
                    "name": r["name"],
                    "market": body["market"],
                    "creator_id": r["owner_id"],
                    "creator_name": r["creator"],
                    "revision": r["version"],
                    "url": "/exchange/strategies/" + r["strategy_id"],
                    "gate_passed": None,
                }
            )
    return {"items": items}


def creator(adaptive, uid):
    items = [i for i in catalog(adaptive)["items"] if i["creator_id"] == uid]
    if not items:
        raise HTTPException(404, "No public work from this creator")
    return {
        "creator_id": uid,
        "name": items[0]["creator_name"],
        "items": items,
        "metrics": {
            "public_strategies": sum(i["kind"] == "strategy" for i in items),
            "public_bundles": sum(i["kind"] == "bundle" for i in items),
            "passed_recorded_holdouts": sum(i["gate_passed"] is True for i in items),
        },
        "note": "Counts describe currently public work, not an independently ranked creator track record.",
    }


def intelligence(adaptive, bid):
    adaptive.get_bundle(bid)  # Public data only, never reveal private clone records.
    values = []
    with adaptive.db.connect() as conn:
        # Aggregate only explicitly published descendants, one latest snapshot per agent.
        rows = conn.execute(
            """SELECT b.body FROM adaptive_bundles b JOIN adaptive_agents a ON a.agent_id=b.agent_id
            WHERE a.source_bundle=? AND b.listed=1 AND b.revision=(SELECT max(c.revision) FROM adaptive_bundles c WHERE c.agent_id=b.agent_id AND c.listed=1)""",
            (bid,),
        ).fetchall()
        for row in rows:
            body = adaptive.checked(json.loads(row[0]))
            if body["agent_apr"].get("schema") == "tracy.agent-apr/2":
                values.append(body["agent_apr"])
    minimum = 3
    return {
        "bundle_id": bid,
        "public_descendants": len(values),
        "minimum_cohort": minimum,
        "rules": []
        if len(values) < minimum
        else [
            {
                "rule_id": r["rule_id"],
                "median_probability": statistics.median(v["apr"][i]["probability"] for v in values),
                "min_probability": min(v["apr"][i]["probability"] for v in values),
                "max_probability": max(v["apr"][i]["probability"] for v in values),
            }
            for i, r in enumerate(values[0]["apr"])
        ],
        "note": "Descriptive aggregate of opted-in public descendant snapshots, including inherited evidence; not independent samples or a causal uplift estimate. No private trades or automatic cross-agent updates.",
    }
