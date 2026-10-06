"""Versioned APR and horizon attribution. Probabilities are empirical thesis scores.

No claim of causal identification: attribution v0 abstains on execution anomalies,
large regime proxies and a noise band. A sample affects only its owning agent.
"""

import asyncio
import json
import math
import time
from copy import deepcopy
from statistics import pstdev

from fastapi import HTTPException

from backend.crypto.hashing import digest
from backend.market_data.provider import SECONDS, provenance

SCHEMA = "tracy.agent-apr/2"
ATTRIBUTION = "tracy.attribution/1"


def rows_for(bp, arms):
    horizon = bp.get("learning", {}).get("horizon_bars", 4) * SECONDS[bp["timeframe"]]
    return [
        {
            "rule_id": f"entry_{i}",
            "condition": {"program": bp["program"], "threshold_bps": a["value"]},
            "action": "BUY",
            "probability": 0.5,
            "probability_meaning": "Smoothed frequency of supported horizon theses; not calibrated profit probability",
            "reason": "Approved deterministic entry condition; no attributed evidence yet",
            "expected_return_pct": bp.get("learning", {}).get("expected_return_pct", 0.5),
            "evaluation_horizon_seconds": horizon,
            "invalidation_pct": bp.get("learning", {}).get("invalidation_pct", -1.5),
            "positive": 0,
            "negative": 0,
            "ignored": 0,
        }
        for i, a in enumerate(arms)
    ]


def upgrade_state(bp, state):
    value = deepcopy(state)
    if value.get("schema") != SCHEMA:
        value["legacy_evidence"] = {"schema": value.get("schema"), "arms": deepcopy(value["arms"])}
        for arm in value["arms"]:
            arm.update(alpha=1, beta=1, closed_trades=0, net_pnl=0.0)
        value["schema"] = SCHEMA
        value["apr"] = rows_for(bp, value["arms"])
        value["feedback_version"] = 0
        value["note"] = (
            "Legacy exit counts retained separately; only horizon-attributed evidence changes APR probabilities."
        )
    return value


def attribution(outcome):
    """Deterministic, inspectable v0; do not infer skill from net trade PnL."""
    actual = outcome["signal_return_pct"]
    if outcome["execution_abnormal"]:
        reason, eligible, signal, confidence = "execution_issue", False, 0, 0.0
    elif outcome["regime_changed"]:
        reason, eligible, signal, confidence = "regime_shift_uncertain", False, 0, 0.25
    elif outcome["max_adverse_pct"] <= outcome["invalidation_pct"]:
        reason, eligible, signal, confidence = "thesis_invalidated", True, -1, 1.0
    elif abs(actual) <= outcome["noise_band_pct"]:
        reason, eligible, signal, confidence = "inside_noise_band", False, 0, 0.0
    elif actual >= outcome["expected_return_pct"]:
        reason, eligible, signal, confidence = "expected_thesis_met", True, 1, 1.0
    elif actual < 0:
        reason, eligible, signal, confidence = "directional_thesis_failed", True, -1, 1.0
    else:
        reason, eligible, signal, confidence = "positive_but_target_unmet", False, 0, 0.5
    return {
        "version": ATTRIBUTION,
        "reason": reason,
        "eligible_for_learning": eligible,
        "decision_signal": signal,
        "execution_signal": -1 if outcome["execution_abnormal"] else 0,
        "market_regime_change": outcome["regime_changed"],
        "confidence": confidence,
        "noise_confidence": 1.0 if reason == "inside_noise_band" else 0.0,
        "limitation": "Rule-based attribution proxy, not proof of causality",
    }


def evaluate(decision, snapshot):
    bars = snapshot["bars"]
    if (
        not bars
        or snapshot["period_start"] != decision["evaluation_start"]
        or snapshot["period_end"] != decision["due_at"]
    ):
        raise ValueError("Outcome market window does not match the committed horizon")
    reference, execution = decision["reference_price"], decision["execution_price"]
    terminal = bars[-1]["price"]
    market_return = (terminal / reference - 1) * 100
    direction = 1 if decision["action"] == "BUY" else -1
    signal_return = direction * market_return
    slippage = direction * (execution / reference - 1) * 100
    fee_pct = decision["fee_bps"] / 100
    net_return = direction * (terminal / execution - 1) * 100 - 2 * fee_pct
    prior_vol = decision["market_state"].get("return_volatility_pct", 0)
    regime = abs(market_return) > max(3.0, 3 * prior_vol * math.sqrt(len(bars)))
    outcome = {
        "decision_id": decision["decision_id"],
        "expected_return_pct": decision["expected_return_pct"],
        "actual_return_pct": net_return,
        "signal_return_pct": signal_return,
        "market_return_pct": market_return,
        "market_benchmark": "same traded asset, not an independent index",
        "execution_slippage_pct": slippage,
        "execution_abnormal": abs(slippage) > decision["slippage_bps"] / 100 + 0.02,
        "regime_changed": regime,
        "noise_band_pct": max(0.05, (2 * decision["fee_bps"] + decision["slippage_bps"]) / 100),
        "max_adverse_pct": min((b["low"] / reference - 1) * 100 for b in bars),
        "max_favorable_pct": max((b["high"] / reference - 1) * 100 for b in bars),
        "invalidation_pct": decision["invalidation_pct"],
        "terminal_price": terminal,
        "hypothetical_horizon_pnl": decision["quantity"] * execution * net_return / 100,
        "pnl_meaning": "Horizon mark with round-trip fees; not the realized trade ledger",
        "window_note": "Extrema use complete candles after the entry candle boundary; the partial entry candle is excluded",
        "source": provenance(snapshot),
        "evaluated_at": int(time.time()),
    }
    outcome["attribution"] = attribution(outcome)
    return outcome


def decision_contract(bp, state, revision, decision, fill, history, did, aid, fid):
    interval = SECONDS[bp["timeframe"]]
    start = math.ceil(fill["timestamp"] / interval) * interval
    rule = state["apr"][fill["arm"]]
    prices = [b["price"] for b in history[-21:]]
    returns = [(b / a - 1) * 100 for a, b in zip(prices, prices[1:])]
    body = {
        "schema": "tracy.decision/1",
        "decision_id": did,
        "agent_id": aid,
        "forward_id": fid,
        "policy_revision": revision,
        "rule_id": rule["rule_id"],
        "arm": fill["arm"],
        "action": fill["side"],
        "market": bp["market"],
        "timeframe": bp["timeframe"],
        "probability": rule["probability"],
        "reason": rule["reason"],
        "condition": rule["condition"],
        "expected_return_pct": rule["expected_return_pct"],
        "invalidation_pct": rule["invalidation_pct"],
        "evaluation_horizon_seconds": rule["evaluation_horizon_seconds"],
        "evaluation_start": start,
        "due_at": start + rule["evaluation_horizon_seconds"],
        "reference_price": fill["requested_price"],
        "execution_price": fill["executed_price"],
        "quantity": fill["quantity"],
        "fee_bps": bp["fee_bps"],
        "slippage_bps": bp["slippage_bps"],
        "market_state": {
            "signal_as_of": decision["signal_as_of"],
            "return_volatility_pct": pstdev(returns) if returns else 0,
        },
        "guardrail_result": "ALLOW",
        "execution": "paper",
        "timestamp": fill["timestamp"],
    }
    return body


class LearningLoop:
    def __init__(self, adaptive):
        self.a, self.db = adaptive, adaptive.db

    def record(self, conn, fid, aid, owner_id, bp, state, revision, decision, fill, history):
        if state.get("schema") != SCHEMA or not fill or fill["side"] != "BUY":
            return
        did = "decision_" + digest({"forward": fid, "trade": fill["trade_id"]})[:32]
        body = decision_contract(bp, state, revision, decision, fill, history, did, aid, fid)
        envelope = self.a.signed(body)
        conn.execute(
            "INSERT OR IGNORE INTO learning_decisions VALUES(?,?,?,?,?,?)",
            (did, aid, owner_id, body["due_at"], json.dumps(envelope), envelope["hash"]),
        )
        conn.execute(
            "INSERT OR IGNORE INTO learning_jobs VALUES(?,'PENDING',?,NULL)", (did, body["due_at"] + 3)
        )

    def resolve(self, did):
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM learning_decisions WHERE decision_id=?", (did,)).fetchone()
            if (
                not row
                or conn.execute("SELECT 1 FROM learning_outcomes WHERE decision_id=?", (did,)).fetchone()
            ):
                return
            d = self.a.checked(json.loads(row["body"]))
        if time.time() < d["due_at"] + 2:
            return
        snapshot = self.a.s.market_data.window(
            d["market"],
            d["timeframe"],
            d["evaluation_horizon_seconds"] // SECONDS[d["timeframe"]],
            d["evaluation_start"],
        )
        body = evaluate(d, snapshot)
        body["decision_hash"] = row["decision_hash"]
        envelope = self.a.signed(body)
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO learning_outcomes VALUES(?,?,?,?,?)",
                (did, row["agent_id"], row["owner_id"], json.dumps(envelope), envelope["hash"]),
            )
            conn.execute("UPDATE learning_jobs SET status='DONE',last_error=NULL WHERE decision_id=?", (did,))
            self.feedback(conn, row["agent_id"], row["owner_id"])

    def feedback(self, conn, aid, owner_id):
        agent = self.a.get(aid, owner_id, conn)
        state = deepcopy(agent["state"])
        if state.get("schema") != SCHEMA:
            return
        # Frozen benchmark runs must finish before policy updates can take effect.
        running = conn.execute(
            "SELECT body FROM adaptive_forward WHERE agent_id=? AND status IN ('RUNNING','STOPPING')", (aid,)
        ).fetchall()
        if any(json.loads(r[0]).get("policy_mode", "frozen") != "adaptive" for r in running):
            return
        rows = conn.execute(
            """SELECT o.decision_id,o.body,o.outcome_hash,d.decision_hash,d.body AS decision FROM learning_outcomes o
            JOIN learning_decisions d ON d.decision_id=o.decision_id
            WHERE o.agent_id=? AND o.owner_id=? AND NOT EXISTS
            (SELECT 1 FROM learning_consumed c WHERE c.decision_id=o.decision_id) ORDER BY d.due_at,o.decision_id""",
            (aid, owner_id),
        ).fetchall()
        entries = [
            (r, self.a.checked(json.loads(r["body"])), self.a.checked(json.loads(r["decision"])))
            for r in rows
        ]
        for row, outcome, decision in entries:
            if (
                digest(outcome) != row["outcome_hash"]
                or digest(decision) != row["decision_hash"]
                or outcome.get("decision_hash") != row["decision_hash"]
                or outcome["decision_id"] != row["decision_id"]
                or decision["agent_id"] != aid
            ):
                raise HTTPException(409, "Outcome lineage integrity failed")
        minimum = agent["strategy_apr"]["blueprint"].get("learning", {}).get("minimum_samples", 20)
        useful = [x for x in entries if x[1]["attribution"]["eligible_for_learning"]]
        ready = {i for i in range(len(state["apr"])) if sum(d["arm"] == i for _, o, d in useful) >= minimum}
        if not ready:
            return
        entries = [entry for entry in entries if entry[2]["arm"] in ready]
        useful = [x for x in entries if x[1]["attribution"]["eligible_for_learning"]]
        before = deepcopy(state["apr"])
        for row, outcome, decision in entries:
            rule = state["apr"][decision["arm"]]
            signal = outcome["attribution"]
            key = (
                "ignored"
                if not signal["eligible_for_learning"]
                else "positive"
                if signal["decision_signal"] > 0
                else "negative"
            )
            rule[key] += 1
            if signal["eligible_for_learning"]:
                state["arms"][decision["arm"]]["alpha" if signal["decision_signal"] > 0 else "beta"] += 1
        for i in ready:
            rule = state["apr"][i]
            rule["probability"] = round((2 + rule["positive"]) / (4 + rule["positive"] + rule["negative"]), 6)
            rule["reason"] = (
                f"Horizon attribution: {rule['positive']} supported, {rule['negative']} failed, {rule['ignored']} ignored; attribution v1"
            )
        previous_arm = state["active_arm"]
        state["active_arm"] = max(
            range(len(state["apr"])), key=lambda i: (state["apr"][i]["probability"], -i)
        )
        state["feedback_version"] += 1
        # Probability affects entry admission in step(); risk boundaries never change.
        change = {
            "schema": "tracy.policy-change/1",
            "agent_id": aid,
            "previous_revision": agent["revision"],
            "revision": agent["revision"] + 1,
            "before": before,
            "after": state["apr"],
            "previous_arm": previous_arm,
            "active_arm": state["active_arm"],
            "timestamp": int(time.time()),
            "outcome_ids": [x[0]["decision_id"] for x in entries],
            "reason": "Minimum attributed horizon sample met; ignored execution/regime/noise outcomes do not change probability",
            "minimum_samples": minimum,
            "eligible_samples": len(useful),
        }
        state["observed_until"] = max(state["observed_until"], max(x[2]["due_at"] for x in entries))
        self.a.save_state(conn, aid, agent["revision"] + 1, state)
        conn.execute("UPDATE adaptive_agents SET revision=revision+1 WHERE agent_id=?", (aid,))
        envelope = self.a.signed(change)
        conn.execute(
            "INSERT INTO learning_changes VALUES(?,?,?)", (aid, agent["revision"] + 1, json.dumps(envelope))
        )
        for row, _, _ in entries:
            conn.execute(
                "INSERT INTO learning_consumed VALUES(?,?,?)",
                (row["decision_id"], aid, agent["revision"] + 1),
            )

    def evolution(self, aid, owner_id):
        agent = self.a.get(aid, owner_id)
        with self.db.connect() as conn:
            changes = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT body FROM learning_changes WHERE agent_id=? ORDER BY revision", (aid,)
                )
            ]
            outcomes = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT body FROM learning_outcomes WHERE agent_id=? AND owner_id=? ORDER BY rowid DESC LIMIT 200",
                    (aid, owner_id),
                )
            ]
            pending = conn.execute(
                "SELECT count(*) FROM learning_jobs j JOIN learning_decisions d USING(decision_id) WHERE d.agent_id=? AND j.status='PENDING'",
                (aid,),
            ).fetchone()[0]
        for item in changes + outcomes:
            self.a.checked(item)
        return {
            "agent_id": aid,
            "revision": agent["revision"],
            "original": agent["strategy_apr"].get("apr", []),
            "current": agent["state"].get("apr", []),
            "changes": changes,
            "outcomes": outcomes,
            "pending": pending,
            "attribution_version": ATTRIBUTION,
        }

    async def tick(self):
        with self.db.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT decision_id FROM learning_jobs WHERE status='PENDING' AND next_tick<=? ORDER BY next_tick LIMIT 20",
                    (int(time.time()),),
                )
            ]
        for did in ids:
            try:
                await asyncio.to_thread(self.resolve, did)
            except Exception:
                with self.db.connect(write=True) as conn:
                    conn.execute(
                        "UPDATE learning_jobs SET next_tick=?,last_error='Outcome data unavailable or integrity check failed; retry pending' WHERE decision_id=? AND status='PENDING'",
                        (int(time.time()) + 60, did),
                    )
