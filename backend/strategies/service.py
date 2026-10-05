import json
import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException

from backend.crypto.hashing import digest
from backend.crypto.signatures import encode_base64, public_key, sign
from backend.degradation.service import DegradationService
from backend.market_data.service import candles
from backend.performance.service import PerformanceService
from backend.strategies.models import VersionInput
from backend.trading.adapters import run_backtest
from backend.trading.service import TradingService


class StrategyService:
    def __init__(self, db, agents, control, receipts, settings):
        self.db, self.agents, self.control, self.receipts, self.settings = (
            db,
            agents,
            control,
            receipts,
            settings,
        )
        self.trading = TradingService(self)
        self.performance = PerformanceService(self)
        self.degradation = DegradationService(self)

    def get(self, strategy_id, owner_id=None, version=None, conn=None, public=False):
        if conn is None:
            with self.db.connect() as c:
                return self.get(strategy_id, owner_id, version, c, public)
        row = conn.execute(
            "SELECT s.*,a.name AS agent_name,a.listed AS agent_listed FROM strategies s JOIN agents a ON a.agent_id=s.agent_id WHERE s.strategy_id=?",
            (strategy_id,),
        ).fetchone()
        if not row or (owner_id and row["owner_id"] != owner_id) or (public and not row["listed"]):
            raise HTTPException(404, "Strategy not found")
        selected = version or row["version"]
        v = conn.execute(
            "SELECT body,created_at FROM strategy_versions WHERE strategy_id=? AND version=?",
            (strategy_id, selected),
        ).fetchone()
        if not v:
            raise HTTPException(404, "Strategy version not found")
        status = row["status"]
        if selected != row["version"]:
            historical = conn.execute(
                "SELECT status FROM trading_deployments WHERE strategy_id=? AND strategy_version=?",
                (strategy_id, selected),
            ).fetchone()
            has_test = conn.execute(
                "SELECT 1 FROM strategy_tests WHERE strategy_id=? AND strategy_version=? LIMIT 1",
                (strategy_id, selected),
            ).fetchone()
            status = historical["status"] if historical else "VALIDATED" if has_test else "DRAFT"
        return {
            **dict(row),
            **json.loads(v["body"]),
            "status": status,
            "version": selected,
            "current_version": row["version"],
            "version_created_at": v["created_at"],
            "listed": bool(row["listed"]),
        }

    def create(self, payload, owner_id):
        self.agents.get(payload.agent_id, owner_id)
        now = int(time.time())
        sid = "strategy_" + uuid4().hex
        body = VersionInput.model_validate(
            {k: v for k, v in payload.model_dump().items() if k not in ("agent_id", "name", "description")}
        ).model_dump()
        with self.db.connect(write=True) as conn:
            if (
                conn.execute("SELECT count(*) FROM strategies WHERE owner_id=?", (owner_id,)).fetchone()[0]
                >= 100
            ):
                raise HTTPException(409, "Workspace strategy limit reached")
            conn.execute(
                "INSERT INTO strategies VALUES(?,?,?,?,?,1,'DRAFT',0,?,?)",
                (sid, owner_id, payload.agent_id, payload.name.strip(), payload.description, now, now),
            )
            conn.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)", (sid, 1, json.dumps(body), now))
            self.control.event(
                conn,
                payload.agent_id,
                "strategy_created",
                {"strategy_id": sid, "version": 1, "snapshot": body, "actor": owner_id},
            )
        return self.get(sid, owner_id)

    def new_version(self, sid, owner_id, payload):
        with self.db.connect(write=True) as conn:
            current = self.get(sid, owner_id, conn=conn)
            if current["version"] != payload.expected_version:
                raise HTTPException(409, "Strategy changed; reload before creating a version")
            if current["status"] in ("LIVE", "DEGRADED"):
                raise HTTPException(409, "Pause the strategy before adapting it")
            if current["status"] == "ARCHIVED":
                raise HTTPException(409, "Archived strategies cannot be edited")
            version = current["version"] + 1
            body = payload.model_dump(exclude={"expected_version"})
            now = int(time.time())
            conn.execute(
                "INSERT INTO strategy_versions VALUES(?,?,?,?)", (sid, version, json.dumps(body), now)
            )
            conn.execute(
                "UPDATE strategies SET version=?,status='DRAFT',updated_at=? WHERE strategy_id=?",
                (version, now, sid),
            )
            conn.execute("UPDATE trading_deployments SET status='PAUSED' WHERE strategy_id=?", (sid,))
            self.control.event(
                conn,
                current["agent_id"],
                "strategy_version_created",
                {"strategy_id": sid, "version": version, "snapshot": body, "actor": owner_id},
            )
        return self.get(sid, owner_id)

    def test(self, sid, owner_id, payload):
        with self.db.connect(write=True) as conn:
            strategy = self.get(sid, owner_id, conn=conn)
            if strategy["status"] == "ARCHIVED":
                raise HTTPException(409, "Archived strategies cannot run tests")
            now = int(time.time())
            test_id = "test_" + uuid4().hex
            prior = strategy["status"]
            conn.execute("UPDATE strategies SET status='TESTING' WHERE strategy_id=?", (sid,))
            bars = candles(
                strategy["market"], strategy["timeframe"], payload.period_start, payload.bars, payload.dataset
            )
            body = run_backtest(strategy, bars)
            body.update(
                test_id=test_id,
                strategy_id=sid,
                strategy_version=strategy["version"],
                starting_capital=strategy["starting_capital"],
                market_period_start=bars[0]["timestamp"],
                market_period_end=bars[-1]["timestamp"],
                dataset=payload.dataset,
                started_at=now,
                finished_at=int(time.time()),
                strategy_snapshot={k: strategy[k] for k in VersionInput.model_fields},
            )
            body["result_hash"] = digest(body)
            body["public_key"] = self.receipts.public_key
            body["signature"] = sign(self.receipts.key, bytes.fromhex(body["result_hash"]))
            conn.execute(
                "INSERT INTO strategy_tests VALUES(?,?,?,?,?,?)",
                (test_id, sid, strategy["version"], now, body["finished_at"], json.dumps(body)),
            )
            conn.execute(
                "UPDATE strategies SET status=?,updated_at=? WHERE strategy_id=?",
                (prior if prior in ("LIVE", "DEGRADED", "PAUSED") else "VALIDATED", int(time.time()), sid),
            )
            self.control.event(
                conn,
                strategy["agent_id"],
                "strategy_test_completed",
                {
                    "strategy_id": sid,
                    "version": strategy["version"],
                    "test_id": test_id,
                    "result_hash": body["result_hash"],
                },
            )
        return body

    def deploy(self, sid, owner_id, payload):
        with self.db.connect(write=True) as conn:
            s = self.get(sid, owner_id, conn=conn)
            if s["version"] != payload.expected_version:
                raise HTTPException(409, "Strategy version changed")
            existing = conn.execute(
                "SELECT deployment_id FROM trading_deployments WHERE strategy_id=? AND strategy_version=?",
                (sid, s["version"]),
            ).fetchone()
            if existing:
                raise HTTPException(
                    409, "This version already has a deployment. Resume it instead of resetting its history."
                )
            if s["status"] != "VALIDATED":
                raise HTTPException(409, "Complete a test of this version before deploying")
            t = conn.execute(
                "SELECT test_id FROM strategy_tests WHERE strategy_id=? AND strategy_version=? ORDER BY started_at DESC,rowid DESC LIMIT 1",
                (sid, s["version"]),
            ).fetchone()
            if not t:
                raise HTTPException(409, "This version has no test")
            key = Ed25519PrivateKey.generate()
            dep = "deploy_" + uuid4().hex
            now = int(time.time())
            conn.execute(
                "INSERT INTO trading_deployments VALUES(?,?,?,'LIVE',0,?,?,?,?)",
                (dep, sid, s["version"], now, t[0], encode_base64(key.private_bytes_raw()), public_key(key)),
            )
            conn.execute("UPDATE strategies SET status='LIVE',updated_at=? WHERE strategy_id=?", (now, sid))
            self.control.event(
                conn,
                s["agent_id"],
                "strategy_deployed",
                {
                    "strategy_id": sid,
                    "version": s["version"],
                    "deployment_id": dep,
                    "mode": "paper",
                    "actor": owner_id,
                    "runner_public_key": public_key(key),
                    "baseline_test_id": t[0],
                },
            )
        return self.detail(sid, owner_id)

    def lifecycle(self, sid, owner_id, payload):
        with self.db.connect(write=True) as conn:
            s = self.get(sid, owner_id, conn=conn)
            if s["version"] != payload.expected_version:
                raise HTTPException(409, "Strategy version changed")
            if s["status"] == "ARCHIVED":
                raise HTTPException(409, "Archived strategy is immutable")
            if payload.status == "LIVE":
                dep = conn.execute(
                    "SELECT * FROM trading_deployments WHERE strategy_id=? AND strategy_version=?",
                    (sid, s["version"]),
                ).fetchone()
                if not dep or dep["step"] >= 96:
                    raise HTTPException(409, "No resumable deployment; test and deploy a new version")
                health = self.degradation.evaluate(conn, s, self.performance.snapshot(conn, s))
                if health["status"] == "CRITICAL":
                    raise HTTPException(
                        409, "Critical guardrail still applies; create a reviewed strategy version"
                    )
            conn.execute(
                "UPDATE strategies SET status=?,updated_at=? WHERE strategy_id=?",
                (payload.status, int(time.time()), sid),
            )
            conn.execute(
                "UPDATE trading_deployments SET status=? WHERE strategy_id=? AND strategy_version=?",
                ("LIVE" if payload.status == "LIVE" else "PAUSED", sid, s["version"]),
            )
            if payload.status in ("PAUSED", "ARCHIVED"):
                self.degradation.alert(
                    conn,
                    s,
                    "strategy_paused",
                    "WATCH",
                    "Strategy " + payload.status.lower() + " by its owner.",
                )
            self.control.event(
                conn,
                s["agent_id"],
                "strategy_status_changed",
                {"strategy_id": sid, "version": s["version"], "status": payload.status, "actor": owner_id},
            )
        return self.get(sid, owner_id)

    def detail(self, sid, owner_id=None, version=None, public=False):
        with self.db.connect() as conn:
            s = self.get(sid, owner_id, version, conn, public)
            perf = self.performance.snapshot(conn, s)
            health = self.degradation.evaluate(conn, s, perf)
            versions = [
                {
                    "version": r["version"],
                    "created_at": r["created_at"],
                    "change_note": json.loads(r["body"])["change_note"],
                }
                for r in conn.execute(
                    "SELECT * FROM strategy_versions WHERE strategy_id=? ORDER BY version DESC", (sid,)
                )
            ]
        if public:
            s = {k: v for k, v in s.items() if k not in ("owner_id",)}
        return {**s, "performance": perf, "health": health, "versions": versions}

    def list(self, owner_id):
        with self.db.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT strategy_id FROM strategies WHERE owner_id=? ORDER BY updated_at DESC,rowid DESC LIMIT 100",
                    (owner_id,),
                )
            ]
        return {"items": [self.detail(sid, owner_id) for sid in ids]}

    def tests(self, sid, owner_id, version=None, public=False):
        self.get(sid, owner_id, version, public=public)
        with self.db.connect() as conn:
            return {
                "items": [
                    json.loads(r[0])
                    for r in conn.execute(
                        "SELECT body FROM strategy_tests WHERE strategy_id=? AND (? IS NULL OR strategy_version=?) ORDER BY started_at DESC,rowid DESC LIMIT 100",
                        (sid, version, version),
                    )
                ]
            }

    def trades(self, sid, owner_id, version=None, public=False, limit=100, offset=0):
        self.get(sid, owner_id, version, public=public)
        with self.db.connect() as conn:
            query = """FROM paper_fills f JOIN trading_deployments d ON d.deployment_id=f.deployment_id
                     WHERE d.strategy_id=? AND (? IS NULL OR d.strategy_version=?)"""
            args = (sid, version, version)
            items = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT f.body " + query + " ORDER BY f.rowid DESC LIMIT ? OFFSET ?",
                    (*args, limit, offset),
                )
            ]
            total = conn.execute("SELECT count(*) " + query, args).fetchone()[0]
        return {"items": items, "total": total}

    def intents(self, sid, owner_id):
        self.get(sid, owner_id)
        with self.db.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT i.intent_id FROM trading_intents i JOIN trading_deployments d ON d.deployment_id=i.deployment_id WHERE d.strategy_id=? ORDER BY i.rowid DESC LIMIT 100",
                    (sid,),
                )
            ]
        return {"items": [self.trading.get(i, owner_id) for i in ids]}

    def publish(self, sid, owner_id, listed):
        with self.db.connect(write=True) as conn:
            s = self.get(sid, owner_id, conn=conn)
            conn.execute(
                "UPDATE strategies SET listed=?,updated_at=? WHERE strategy_id=?",
                (int(listed), int(time.time()), sid),
            )
            self.control.event(
                conn,
                s["agent_id"],
                "strategy_publication_changed",
                {"strategy_id": sid, "listed": listed, "actor": owner_id},
            )
        return self.get(sid, owner_id)

    def exchange(self, q=""):
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT s.strategy_id FROM strategies s JOIN agents a ON a.agent_id=s.agent_id
            WHERE s.listed=1 AND (s.name LIKE ? OR a.name LIKE ?) ORDER BY s.updated_at DESC LIMIT 100""",
                ("%" + q + "%", "%" + q + "%"),
            ).fetchall()
        return {"items": [self.detail(r[0], public=True) for r in rows]}

    def public_agent(self, agent_id):
        with self.db.connect() as conn:
            agent = conn.execute(
                "SELECT agent_id,name,description,public_key,created_at,listed AS legacy_listed FROM agents WHERE agent_id=? AND (listed=1 OR EXISTS(SELECT 1 FROM strategies s WHERE s.agent_id=agents.agent_id AND s.listed=1))",
                (agent_id,),
            ).fetchone()
            if not agent:
                raise HTTPException(404, "Published agent not found")
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT strategy_id FROM strategies WHERE agent_id=? AND listed=1 ORDER BY updated_at DESC",
                    (agent_id,),
                )
            ]
        return {**dict(agent), "strategies": [self.detail(sid, public=True) for sid in ids]}

    def alerts(self, owner_id):
        with self.db.connect() as conn:
            rows = conn.execute(
                """WITH ranked AS (
                SELECT d.*,s.name AS strategy_name,
                    row_number() OVER(PARTITION BY d.strategy_id,d.version,d.kind,d.severity ORDER BY d.created_at DESC,d.rowid DESC) AS rank,
                    count(*) OVER(PARTITION BY d.strategy_id,d.version,d.kind,d.severity) AS observations
                FROM degradation_alerts d JOIN strategies s ON s.strategy_id=d.strategy_id WHERE s.owner_id=?
            ) SELECT * FROM ranked WHERE rank=1 ORDER BY created_at DESC LIMIT 200""",
                (owner_id,),
            )
            return {"items": [{k: r[k] for k in r.keys() if k != "rank"} for r in rows]}

    def acknowledge(self, alert_id, owner_id):
        with self.db.connect(write=True) as conn:
            row = conn.execute(
                "SELECT d.* FROM degradation_alerts d JOIN strategies s ON s.strategy_id=d.strategy_id WHERE d.alert_id=? AND s.owner_id=?",
                (alert_id, owner_id),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Alert not found")
            conn.execute(
                """UPDATE degradation_alerts SET acknowledged=1
                WHERE strategy_id=? AND version=? AND kind=? AND severity=? AND created_at<=?""",
                (row["strategy_id"], row["version"], row["kind"], row["severity"], row["created_at"]),
            )
        return {"ok": True}
