import json
import time
from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException

from backend.adaptive.engine import ENGINE, experiment, initial_state
from backend.adaptive.learning import LearningLoop, rows_for, upgrade_state
from backend.adaptive.models import Blueprint
from backend.adaptive.pine import parse
from backend.crypto.hashing import digest
from backend.crypto.signatures import sign, verify
from backend.execution_control import require_execution
from backend.market_data.provider import provenance


class AdaptiveService:
    def __init__(self, strategies):
        self.s, self.db = strategies, strategies.db
        self.learning = LearningLoop(self)

    def signed(self, body):
        hashed = digest(body)
        return {
            "body": body,
            "hash": hashed,
            "public_key": self.s.receipts.public_key,
            "signature": sign(self.s.receipts.key, bytes.fromhex(hashed)),
        }

    def checked(self, envelope):
        if (
            envelope["public_key"] != self.s.receipts.public_key
            or digest(envelope["body"]) != envelope["hash"]
            or not verify(envelope["public_key"], envelope["signature"], bytes.fromhex(envelope["hash"]))
        ):
            raise HTTPException(409, "Adaptive record integrity failed")
        return envelope["body"]

    def state(self, conn, agent_id, revision):
        row = conn.execute(
            "SELECT body,state_hash FROM adaptive_states WHERE agent_id=? AND revision=?",
            (agent_id, revision),
        ).fetchone()
        envelope = json.loads(row[0])
        if envelope["hash"] != row[1]:
            raise HTTPException(409, "State index integrity failed")
        return self.checked(envelope)

    def get(self, agent_id, owner_id, conn=None):
        if conn is None:
            with self.db.connect() as c:
                return self.get(agent_id, owner_id, c)
        row = conn.execute(
            "SELECT * FROM adaptive_agents WHERE agent_id=? AND owner_id=?", (agent_id, owner_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Adaptive agent not found")
        strategy = conn.execute(
            "SELECT * FROM adaptive_strategies WHERE strategy_id=?", (row["strategy_id"],)
        ).fetchone()
        envelope = json.loads(strategy["body"])
        if envelope["hash"] != strategy["strategy_hash"]:
            raise HTTPException(409, "Strategy index integrity failed")
        apr = self.checked(envelope)
        runs = conn.execute(
            "SELECT body FROM adaptive_runs WHERE agent_id=? ORDER BY created_at DESC,rowid DESC LIMIT 10",
            (agent_id,),
        ).fetchall()
        for run in runs:
            self.checked(json.loads(run[0]))
        bundles = conn.execute(
            "SELECT bundle_id,bundle_hash,listed,revision FROM adaptive_bundles WHERE agent_id=?", (agent_id,)
        ).fetchall()
        review_report = json.loads(runs[0][0]) if runs else None
        if not review_report and row["source_bundle"]:
            inherited = conn.execute(
                "SELECT body FROM adaptive_bundles WHERE bundle_id=?", (row["source_bundle"],)
            ).fetchone()
            if inherited:
                review_report = self.checked(json.loads(inherited[0]))["evidence"]
                self.checked(review_report)
        return {
            "review_report": review_report,
            **dict(row),
            "strategy_apr": apr,
            "strategy_hash": strategy["strategy_hash"],
            "state": self.state(conn, agent_id, row["revision"]),
            "runs": [json.loads(r[0]) for r in runs],
            "bundles": [dict(b) for b in bundles],
        }

    def save_state(self, conn, aid, revision, body):
        envelope = self.signed(body)
        conn.execute(
            "INSERT INTO adaptive_states VALUES(?,?,?,?)",
            (aid, revision, json.dumps(envelope), envelope["hash"]),
        )

    def create(
        self,
        payload,
        owner_id,
        inherited=None,
        source=None,
        instance_name=None,
        source_apr=None,
        source_identity=None,
    ):
        bp = payload.model_dump()
        if bp["pine_source"]:
            parsed = parse(bp["pine_source"])
            if parsed["program"] != bp["program"]:
                raise HTTPException(422, "Pine source and reviewed program differ; import again")
        apr = {
            "schema": "tracy.strategy-apr/2",
            "apr": rows_for(bp, initial_state(bp)["arms"]),
            "engine": ENGINE,
            "blueprint": bp,
            "allowed_learning": "Entry threshold only, in the enumerated arms. Risk limits, fees, market and allocation are immutable.",
            "risk_exit_authorization": "Reduce-only exits may close existing inventory regardless of entry size/approval limits. No shorting or withdrawals.",
            "execution": "Paper only: historical next-bar-open or forward current bid/ask, plus configured fees and slippage.",
        }
        if source_identity:
            apr["source_identity"] = source_identity
        if source_apr is not None:
            apr = deepcopy(source_apr)
        aid, sid, now = "adaptive_" + uuid4().hex, "apr_" + uuid4().hex, int(time.time())
        strategy = self.signed(apr)
        with self.db.connect(write=True) as conn:
            if (
                conn.execute("SELECT count(*) FROM adaptive_agents WHERE owner_id=?", (owner_id,)).fetchone()[
                    0
                ]
                >= 50
            ):
                raise HTTPException(409, "Adaptive workspace limit reached")
            conn.execute(
                "INSERT INTO adaptive_strategies VALUES(?,?,?,?,?)",
                (sid, owner_id, json.dumps(strategy), strategy["hash"], now),
            )
            conn.execute(
                "INSERT INTO adaptive_agents VALUES(?,?,?,?,1,?,?)",
                (aid, owner_id, sid, instance_name or bp["name"], source, now),
            )
            state = deepcopy(inherited) if inherited else upgrade_state(bp, initial_state(bp))
            state.update(last_run_id=None, inherited_from=source, personal_closed_trades=0)
            self.save_state(conn, aid, 1, state)
        return self.get(aid, owner_id)

    def fork(self, payload, owner_id):
        try:
            old = self.s.get(payload.strategy_id, owner_id, version=payload.version)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            old = self.s.get(payload.strategy_id, version=payload.version, public=True)
        if old["strategy_config"]["runner"] == "buy_hold":
            raise HTTPException(
                422,
                "Buy-and-hold remains a fixed control; choose momentum or mean reversion to learn entry thresholds",
            )
        cfg = old["strategy_config"]
        bp = Blueprint(
            name=payload.name,
            intent=old["description"] or "Learn bounded entry thresholds from this strategy",
            market=old["market"],
            timeframe=old["timeframe"],
            capital=old["starting_capital"],
            allocation_pct=cfg["allocation_pct"],
            fee_bps=cfg["fee_bps"],
            slippage_bps=cfg["slippage_bps"],
            guardrails=old["guardrails"],
            program={
                "kind": cfg["runner"],
                "lookback": cfg["lookback"],
                "threshold_bps": cfg["threshold_bps"],
                "exit_after_bars": cfg["exit_after_bars"],
            },
        )
        return self.create(
            bp,
            owner_id,
            source_identity={
                "strategy_id": old["strategy_id"],
                "version": old["version"],
                "creator_id": old["owner_id"],
                "configuration_hash": digest(
                    {"program": bp.program.model_dump(), "guardrails": bp.guardrails.model_dump()}
                ),
            },
        )

    def train(self, aid, owner_id, payload):
        req_hash = digest(payload.model_dump())
        with self.db.connect() as conn:
            agent = self.get(aid, owner_id, conn)
            existing = conn.execute(
                "SELECT request_hash,body FROM adaptive_runs WHERE agent_id=? AND request_id=?",
                (aid, payload.request_id),
            ).fetchone()
            if existing:
                if existing[0] != req_hash:
                    raise HTTPException(409, "Request ID reused with different experiment parameters")
                return json.loads(existing[1])
        if agent["revision"] != payload.expected_revision:
            raise HTTPException(409, "Agent changed; reload before training")
        bp = agent["strategy_apr"]["blueprint"]
        snapshot = self.s.market_data.window(
            bp["market"],
            bp["timeframe"],
            payload.training_bars + payload.validation_bars,
            payload.period_start,
        )
        if snapshot["period_start"] < agent["state"]["observed_until"]:
            raise HTTPException(
                409,
                "This agent has already observed part of this period. Choose new, non-overlapping data; create a fresh baseline agent to repeat an experiment.",
            )
        report = experiment(bp, snapshot, agent["state"], payload.training_bars)
        run_id, now = "learning_" + uuid4().hex, int(time.time())
        next_state = report["next_state"]
        next_state.update(
            last_run_id=run_id,
            personal_closed_trades=agent["state"].get("personal_closed_trades", 0)
            + report["training"]["metrics"]["closed_trade_count"],
        )
        report.update(
            run_id=run_id,
            agent_id=aid,
            strategy_hash=agent["strategy_hash"],
            prior_revision=agent["revision"],
            resulting_revision=agent["revision"] + 1,
            source=provenance(snapshot),
            created_at=now,
        )
        envelope = self.signed(report)
        with self.db.connect(write=True) as conn:
            current = self.get(aid, owner_id, conn)
            if current["revision"] != payload.expected_revision:
                raise HTTPException(409, "Agent changed during training; no state was overwritten")
            if conn.execute(
                "SELECT 1 FROM adaptive_forward WHERE agent_id=? AND status IN ('RUNNING','STOPPING')", (aid,)
            ).fetchone():
                raise HTTPException(409, "Stop the forward run before training")
            self.save_state(conn, aid, agent["revision"] + 1, next_state)
            if next_state.get("apr") and next_state["apr"] != agent["state"].get("apr"):
                outcomes = report["training"]["attributed_outcomes"]
                change = {
                    "schema": "tracy.policy-change/1",
                    "agent_id": aid,
                    "previous_revision": agent["revision"],
                    "revision": agent["revision"] + 1,
                    "before": agent["state"]["apr"],
                    "after": next_state["apr"],
                    "timestamp": now,
                    "outcome_ids": [o["decision_id"] for o in outcomes],
                    "report_hash": envelope["hash"],
                    "reason": "Chronological historical horizon attribution; evidence is in the signed experiment, holdout is excluded",
                    "eligible_samples": sum(o["attribution"]["eligible_for_learning"] for o in outcomes),
                }
                conn.execute(
                    "INSERT INTO learning_changes VALUES(?,?,?)",
                    (aid, agent["revision"] + 1, json.dumps(self.signed(change))),
                )
            conn.execute("UPDATE adaptive_agents SET revision=revision+1 WHERE agent_id=?", (aid,))
            conn.execute(
                "INSERT INTO adaptive_runs VALUES(?,?,?,?,?,?,?)",
                (run_id, aid, payload.request_id, req_hash, json.dumps(envelope), envelope["hash"], now),
            )
        return envelope

    def activate(self, aid, owner_id, payload):
        with self.db.connect(write=True) as conn:
            agent = self.get(aid, owner_id, conn)
            state = deepcopy(agent["state"])
            if agent["revision"] != payload.expected_revision or not state["last_run_id"]:
                raise HTTPException(409, "Train and review the latest agent revision first")
            if conn.execute(
                "SELECT 1 FROM adaptive_forward WHERE agent_id=? AND status IN ('RUNNING','STOPPING')", (aid,)
            ).fetchone():
                raise HTTPException(409, "Stop the forward run before activating a policy")
            row = conn.execute(
                "SELECT body FROM adaptive_runs WHERE run_id=? AND agent_id=?", (state["last_run_id"], aid)
            ).fetchone()
            envelope = json.loads(row[0])
            report = self.checked(envelope)
            if envelope["hash"] != payload.report_hash or report["resulting_revision"] != agent["revision"]:
                raise HTTPException(409, "Review no longer matches the current state")
            if not report["gate"]["passed"]:
                raise HTTPException(409, "Candidate failed the holdout gate; incumbent stays active")
            state.update(active_arm=report["candidate_arm"], activation_report=payload.report_hash)
            self.save_state(conn, aid, agent["revision"] + 1, state)
            conn.execute("UPDATE adaptive_agents SET revision=revision+1 WHERE agent_id=?", (aid,))
        return self.get(aid, owner_id)

    def bundle(self, aid, owner_id, revision):
        with self.db.connect(write=True) as conn:
            agent = self.get(aid, owner_id, conn)
            if revision != agent["revision"]:
                raise HTTPException(409, "Agent changed; reload before freezing a bundle")
            row = conn.execute(
                "SELECT * FROM adaptive_bundles WHERE agent_id=? AND revision=?", (aid, revision)
            ).fetchone()
            if row:
                return {
                    "bundle_id": row["bundle_id"],
                    "envelope": json.loads(row["body"]),
                    "listed": bool(row["listed"]),
                }
            if not agent["review_report"]:
                raise HTTPException(409, "Run an experiment or inherit a documented bundle before freezing")
            body = {
                "schema": "tracy.bundle/1",
                "engine": ENGINE,
                "name": agent["name"],
                "strategy_apr": agent["strategy_apr"],
                "strategy_hash": agent["strategy_hash"],
                "agent_apr": agent["state"],
                "revision": revision,
                "evidence": agent["review_report"],
                "created_at": int(time.time()),
                "transfer": "Rules and learned state only. No capital, credentials, positions or personal trade history.",
                "network": "solana-devnet",
                "execution": "paper",
                "price": "Current test-SOL license terms are separate from this immutable evidence snapshot",
            }
            completed = conn.execute(
                "SELECT forward_id,body FROM adaptive_forward WHERE agent_id=? AND status='COMPLETED' ORDER BY rowid",
                (aid,),
            ).fetchall()
            body["forward_evidence"] = []
            for forward_id, forward_body in completed:
                chain = [
                    json.loads(r[0])
                    for r in conn.execute(
                        "SELECT body FROM adaptive_forward_events WHERE forward_id=? ORDER BY sequence",
                        (forward_id,),
                    )
                ]
                previous = None
                for event in chain:
                    record = self.checked(event)
                    if record["previous_hash"] != previous:
                        raise HTTPException(409, "Forward evidence chain mismatch")
                    previous = event["hash"]
                if not chain or chain[-1]["body"]["state_hash"] != digest(json.loads(forward_body)):
                    raise HTTPException(409, "Forward state mismatch")
                body["forward_evidence"].append(
                    {"forward_id": forward_id, "state": json.loads(forward_body), "events": chain}
                )
            body["source_bundle"] = agent["source_bundle"]
            body["learning_evidence"] = {
                "changes": [
                    json.loads(r[0])
                    for r in conn.execute(
                        "SELECT body FROM learning_changes WHERE agent_id=? ORDER BY revision", (aid,)
                    )
                ],
                "outcomes": [
                    json.loads(r[0])
                    for r in conn.execute("SELECT body FROM learning_outcomes WHERE agent_id=?", (aid,))
                ],
                "decisions": [
                    json.loads(r[0])
                    for r in conn.execute("SELECT body FROM learning_decisions WHERE agent_id=?", (aid,))
                ],
            }
            for records in body["learning_evidence"].values():
                for record in records:
                    self.checked(record)
            envelope = self.signed(body)
            bid = "bundle_" + uuid4().hex
            conn.execute(
                "INSERT INTO adaptive_bundles VALUES(?,?,?,?,?,?,0,?)",
                (bid, owner_id, aid, revision, json.dumps(envelope), envelope["hash"], body["created_at"]),
            )
            return {"bundle_id": bid, "envelope": envelope, "listed": False}

    def get_bundle(self, bid, owner_id=None):
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM adaptive_bundles WHERE bundle_id=?", (bid,)).fetchone()
            if not row or (not row["listed"] and row["owner_id"] != owner_id):
                raise HTTPException(404, "Bundle not found")
            envelope = json.loads(row["body"])
            if envelope["hash"] != row["bundle_hash"]:
                raise HTTPException(409, "Bundle index integrity failed")
            self.checked(envelope)
            anchor = conn.execute(
                "SELECT signature,status,body FROM adaptive_anchors WHERE bundle_id=?", (bid,)
            ).fetchone()
            return {
                "bundle_id": bid,
                "envelope": envelope,
                "listed": bool(row["listed"]),
                "anchor": {"signature": anchor[0], "status": anchor[1], **json.loads(anchor[2])}
                if anchor
                else None,
            }

    def publish(self, bid, owner_id, listed):
        with self.db.connect(write=True) as conn:
            row = conn.execute("SELECT owner_id FROM adaptive_bundles WHERE bundle_id=?", (bid,)).fetchone()
            if not row or row[0] != owner_id:
                raise HTTPException(404, "Bundle not found")
            conn.execute("UPDATE adaptive_bundles SET listed=? WHERE bundle_id=?", (int(listed), bid))
        return self.get_bundle(bid, owner_id)

    def clone(self, bid, owner_id, payload):
        self.payments.require_license(bid, owner_id)
        source = self.get_bundle(bid, owner_id)
        body = source["envelope"]["body"]
        bp = body["strategy_apr"]["blueprint"]
        state = body["agent_apr"] if payload.mode == "bundle" else None
        return self.create(
            Blueprint.model_validate(bp), owner_id, state, bid, payload.name, body["strategy_apr"]
        )

    def catalog(self):
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT bundle_id,body FROM adaptive_bundles WHERE listed=1 ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return {
            "items": [
                {
                    "bundle_id": r[0],
                    "name": self.checked(json.loads(r[1]))["name"],
                    "market": json.loads(r[1])["body"]["strategy_apr"]["blueprint"]["market"],
                    "revision": json.loads(r[1])["body"]["revision"],
                    "gate": json.loads(r[1])["body"]["evidence"]["body"]["gate"],
                }
                for r in rows
            ]
        }

    def review_start(self, aid, owner_id, payload):
        require_execution(self.s.settings)
        with self.db.connect(write=True) as conn:
            agent = self.get(aid, owner_id, conn)
            if not payload.acknowledged or agent["revision"] != payload.expected_revision:
                raise HTTPException(409, "Review the exact current revision")
            if not agent["review_report"] or agent["review_report"]["hash"] != payload.report_hash:
                raise HTTPException(409, "Review the latest signed experiment")
            if conn.execute(
                "SELECT 1 FROM adaptive_forward WHERE agent_id=? AND status IN ('RUNNING','STOPPING')", (aid,)
            ).fetchone():
                raise HTTPException(409, "Stop the current comparison before changing its learning contract")
            if payload.policy_mode == "adaptive" and agent["state"].get("schema") != "tracy.agent-apr/2":
                state = upgrade_state(agent["strategy_apr"]["blueprint"], agent["state"])
                self.save_state(conn, aid, agent["revision"] + 1, state)
                conn.execute("UPDATE adaptive_agents SET revision=revision+1 WHERE agent_id=?", (aid,))
                agent = self.get(aid, owner_id, conn)
            body = {
                "agent_id": aid,
                "revision": agent["revision"],
                "state_hash": digest(agent["state"]),
                "strategy_hash": agent["strategy_hash"],
                "report_hash": payload.report_hash,
                "policy_mode": payload.policy_mode,
                "actor": owner_id,
                "timestamp": int(time.time()),
            }
            existing = conn.execute(
                "SELECT body FROM adaptive_reviews WHERE agent_id=? AND revision=?", (aid, agent["revision"])
            ).fetchone()
            if existing and self.checked(json.loads(existing[0]))["policy_mode"] != payload.policy_mode:
                raise HTTPException(409, "This immutable review already selected another mode")
            conn.execute(
                "INSERT OR IGNORE INTO adaptive_reviews VALUES(?,?,?)",
                (aid, agent["revision"], json.dumps(self.signed(body))),
            )
        return self.get(aid, owner_id)
