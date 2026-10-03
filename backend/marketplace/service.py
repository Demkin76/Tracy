import asyncio
import hashlib
import hmac
import json
import logging
import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException

from backend.actions.models import ActionRequest
from backend.crypto.hashing import canonical_bytes, digest
from backend.crypto.signatures import decode_base64, public_key, sign
from backend.platform.service import record_event
from backend.policies.engine import lamports

ACTIVE = ("QUEUED", "RUNNING", "WAITING")
logger = logging.getLogger("tracy.marketplace")


class Marketplace:
    def __init__(self, db, agents, actions, settings):
        self.db, self.agents, self.actions, self.settings = db, agents, actions, settings
        self.lock = asyncio.Lock()

    def key(self, agent_id):
        # Domain-separated deterministic keys survive restarts without storing plaintext seeds in SQLite.
        root = decode_base64(self.settings.signing_seed.get_secret_value(), 32)
        seed = hmac.new(root, b"tracy-managed-agent-v1:" + agent_id.encode(), hashlib.sha256).digest()
        return Ed25519PrivateKey.from_private_bytes(seed)

    def offer(self, agent_id, owner_id, payload):
        self.agents.get(agent_id, owner_id)
        with self.db.connect(write=True) as conn:
            conn.execute(
                """INSERT INTO agent_offers VALUES(?,?,1,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET kind=excluded.kind,version=version+1,
                enabled=excluded.enabled,updated_at=excluded.updated_at""",
                (agent_id, payload.kind, int(payload.enabled), int(time.time())),
            )
            record_event(conn, owner_id, "offer_updated", agent_id)
        return self.offer_info(agent_id, private=True)

    def offer_info(self, agent_id, private=False):
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT o.*,a.listed,a.active FROM agent_offers o
                JOIN agents a ON a.agent_id=o.agent_id WHERE o.agent_id=?""",
                (agent_id,),
            ).fetchone()
        if not row or (not private and not (row["listed"] and row["active"] and row["enabled"])):
            return None
        return {
            "kind": row["kind"],
            "version": row["version"],
            "enabled": bool(row["enabled"]),
            "runtime": "tracy-managed-v1",
            "network": "solana-devnet",
        }

    def validate_plan(self, plan, policy, kind):
        if kind == "batch_payout" and plan.max_cycles != 1:
            raise HTTPException(422, "Batch payouts run one cycle; choose scheduled payouts for repetition")
        if "solana.transfer" not in policy.allowed_actions:
            raise HTTPException(422, "Enable solana.transfer before configuring payouts")
        for item in plan.transfers:
            if item.to == self.actions.gateway.sender:
                raise HTTPException(422, "The execution wallet cannot be the recipient")
            if item.to not in policy.allowed_recipients or lamports(item.amount) > lamports(
                policy.max_transfer_sol
            ):
                raise HTTPException(
                    422, "Every planned transfer must fit your recipients and per-transfer limit"
                )
        if sum(t.lamports for t in plan.transfers) > lamports(policy.daily_budget_sol):
            raise HTTPException(422, "One payout cycle exceeds your daily budget")

    def install(self, payload, owner_id):
        now, agent_id = int(time.time()), "installed_" + uuid4().hex
        fingerprint = digest(payload.model_dump())
        with self.db.connect(write=True) as conn:
            previous = conn.execute(
                "SELECT * FROM installations WHERE owner_id=? AND install_request_id=?",
                (owner_id, payload.request_id),
            ).fetchone()
            if previous:
                if previous["install_hash"] != fingerprint:
                    raise HTTPException(409, "Installation request ID already used with different settings")
                agent_id = previous["agent_id"]
            else:
                source = conn.execute(
                    """SELECT a.name,o.kind,o.version FROM agents a JOIN agent_offers o
                    ON o.agent_id=a.agent_id WHERE a.agent_id=? AND a.listed=1 AND a.active=1 AND o.enabled=1""",
                    (payload.source_agent_id,),
                ).fetchone()
                if not source:
                    raise HTTPException(404, "This agent is not available for installation")
                if source["version"] != payload.expected_version:
                    raise HTTPException(409, "The offer changed; reload and review it before installing")
                self.validate_plan(payload.plan, payload.policy, source["kind"])
                if (
                    conn.execute("SELECT count(*) FROM agents WHERE owner_id=?", (owner_id,)).fetchone()[0]
                    >= 50
                ):
                    raise HTTPException(409, "Workspace limit: 50 agents")
                policy = json.dumps(payload.policy.model_dump())
                conn.execute(
                    """INSERT INTO agents(agent_id,name,public_key,created_at,policy,owner_id,description)
                    VALUES(?,?,?,?,?,?,?)""",
                    (
                        agent_id,
                        payload.name.strip(),
                        public_key(self.key(agent_id)),
                        now,
                        policy,
                        owner_id,
                        "Personal installation of " + source["name"] + ". Managed Devnet payouts.",
                    ),
                )
                conn.execute(
                    "INSERT INTO policy_versions VALUES(?,?,?,?,?)", (agent_id, 1, policy, now, owner_id)
                )
                conn.execute(
                    """INSERT INTO installations(agent_id,owner_id,source_agent_id,source_name,kind,
                    offer_version,plan,created_at,install_request_id,install_hash) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        agent_id,
                        owner_id,
                        payload.source_agent_id,
                        source["name"],
                        source["kind"],
                        source["version"],
                        json.dumps(payload.plan.model_dump()),
                        now,
                        payload.request_id,
                        fingerprint,
                    ),
                )
                record_event(conn, owner_id, "agent_installed", agent_id)
        return self.get(agent_id, owner_id)

    def get(self, agent_id, owner_id):
        agent = self.agents.get(agent_id, owner_id)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM installations WHERE agent_id=? AND owner_id=?", (agent_id, owner_id)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Installation not found")
        result = dict(row)
        result.pop("install_hash")
        result.pop("install_request_id")
        result["plan"] = json.loads(result["plan"])
        result["running"] = bool(result["running"])
        result["agent"] = agent
        return result

    def list(self, owner_id):
        with self.db.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT agent_id FROM installations WHERE owner_id=? ORDER BY created_at DESC,rowid DESC",
                    (owner_id,),
                )
            ]
        return {"items": [self.get(i, owner_id) for i in ids]}

    def edit(self, agent_id, owner_id, payload):
        from backend.policies.engine import Policy

        current = self.get(agent_id, owner_id)
        self.validate_plan(payload.plan, Policy.model_validate(current["agent"]["policy"]), current["kind"])
        with self.db.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM installations WHERE agent_id=?", (agent_id,)).fetchone()
            busy = conn.execute(
                "SELECT 1 FROM agent_runs WHERE agent_id=? AND status IN ('QUEUED','RUNNING','WAITING')",
                (agent_id,),
            ).fetchone()
            if row["running"] or busy:
                raise HTTPException(409, "Stop the agent before editing its payout plan")
            if row["revision"] != payload.expected_revision:
                raise HTTPException(409, "Plan changed in another session; reload before saving")
            conn.execute(
                "UPDATE installations SET plan=?,revision=revision+1 WHERE agent_id=?",
                (json.dumps(payload.plan.model_dump()), agent_id),
            )
            record_event(conn, owner_id, "payout_plan_updated", agent_id)
        return self.get(agent_id, owner_id)

    def queue(self, agent_id, owner_id, request_id):
        self.get(agent_id, owner_id)
        with self.db.connect(write=True) as conn:
            existing = conn.execute(
                "SELECT run_id FROM agent_runs WHERE agent_id=? AND request_id=?", (agent_id, request_id)
            ).fetchone()
            if existing:
                return self.run_view(conn, existing["run_id"])
            row = conn.execute(
                """SELECT i.*,a.active FROM installations i JOIN agents a
                ON a.agent_id=i.agent_id WHERE i.agent_id=?""",
                (agent_id,),
            ).fetchone()
            if not row["active"]:
                raise HTTPException(409, "Resume this agent before running")
            if (
                row["running"]
                or conn.execute(
                    "SELECT 1 FROM agent_runs WHERE agent_id=? AND status IN ('QUEUED','RUNNING','WAITING')",
                    (agent_id,),
                ).fetchone()
            ):
                raise HTTPException(409, "A run or schedule is already active")
            run_id = self.insert_run(conn, row, request_id)
            record_event(conn, owner_id, "run_requested", run_id)
            return self.run_view(conn, run_id)

    def insert_run(self, conn, row, request_id):
        run_id = "run_" + uuid4().hex
        conn.execute(
            "INSERT INTO agent_runs(run_id,agent_id,request_id,plan,status,created_at) VALUES(?,?,?,?,?,?)",
            (run_id, row["agent_id"], request_id, row["plan"], "QUEUED", int(time.time())),
        )
        return run_id

    def start(self, agent_id, owner_id):
        self.get(agent_id, owner_id)
        with self.db.connect(write=True) as conn:
            row = conn.execute(
                """SELECT i.*,a.active FROM installations i JOIN agents a
                ON a.agent_id=i.agent_id WHERE i.agent_id=?""",
                (agent_id,),
            ).fetchone()
            if row["kind"] != "scheduled_payout":
                raise HTTPException(422, "This agent supports Run once; it has no recurring schedule")
            if not row["active"]:
                raise HTTPException(409, "Resume this agent before starting its schedule")
            if row["running"]:
                return {"ok": True}
            if conn.execute(
                "SELECT 1 FROM agent_runs WHERE agent_id=? AND status IN ('QUEUED','RUNNING','WAITING')",
                (agent_id,),
            ).fetchone():
                raise HTTPException(409, "Wait for the current run to finish")
            conn.execute(
                "UPDATE installations SET running=1,next_run_at=?,cycles=0 WHERE agent_id=?",
                (int(time.time()), agent_id),
            )
            record_event(conn, owner_id, "schedule_started", agent_id)
        return {"ok": True}

    def stop(self, agent_id, owner_id):
        self.get(agent_id, owner_id)
        self.agents.status(agent_id, owner_id, False)
        return self.get(agent_id, owner_id)

    def run_view(self, conn, run_id):
        row = dict(conn.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone())
        row["plan"] = json.loads(row["plan"])
        row["actions"] = [
            dict(r)
            for r in conn.execute(
                """SELECT action_id,status,reason,receipt_id,tx_signature,request_id
            FROM actions WHERE agent_id=? AND request_id GLOB ? ORDER BY created_at,rowid""",
                (row["agent_id"], run_id + "_*"),
            )
        ]
        return row

    def history(self, agent_id, owner_id, limit=25, offset=0):
        self.get(agent_id, owner_id)
        with self.db.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    """SELECT run_id FROM agent_runs WHERE agent_id=?
                ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?""",
                    (agent_id, limit, offset),
                )
            ]
            return {
                "items": [self.run_view(conn, i) for i in ids],
                "total": conn.execute(
                    "SELECT count(*) FROM agent_runs WHERE agent_id=?", (agent_id,)
                ).fetchone()[0],
            }

    def finish(self, run_id, status, reason=""):
        with self.db.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
            if row["status"] == "CANCELLED":
                return
            conn.execute(
                "UPDATE agent_runs SET status=?,reason=?,completed_at=? WHERE run_id=?",
                (status, reason, int(time.time()), run_id),
            )
            if status in ("BLOCKED", "FAILED"):
                conn.execute(
                    "UPDATE installations SET running=0,next_run_at=NULL WHERE agent_id=?", (row["agent_id"],)
                )
            owner = conn.execute(
                "SELECT owner_id FROM installations WHERE agent_id=?", (row["agent_id"],)
            ).fetchone()[0]
            record_event(conn, owner, "run_" + status.lower(), run_id)

    async def tick(self):
        async with self.lock:
            now = int(time.time())
            with self.db.connect(write=True) as conn:
                due = conn.execute(
                    """SELECT i.* FROM installations i JOIN agents a ON a.agent_id=i.agent_id
                    WHERE i.running=1 AND a.active=1 AND i.next_run_at<=?
                    AND NOT EXISTS(SELECT 1 FROM agent_runs r WHERE r.agent_id=i.agent_id
                        AND r.status IN ('QUEUED','RUNNING','WAITING')) ORDER BY i.next_run_at LIMIT 20""",
                    (now,),
                ).fetchall()
                for row in due:
                    plan = json.loads(row["plan"])
                    self.insert_run(conn, row, "schedule_" + uuid4().hex)
                    cycles = row["cycles"] + 1
                    more = cycles < plan["max_cycles"]
                    conn.execute(
                        "UPDATE installations SET cycles=?,running=?,next_run_at=? WHERE agent_id=?",
                        (
                            cycles,
                            int(more),
                            now + plan["interval_seconds"] if more else None,
                            row["agent_id"],
                        ),
                    )
                runs = [
                    dict(r)
                    for r in conn.execute("""SELECT * FROM agent_runs
                    WHERE status IN ('QUEUED','RUNNING','WAITING') ORDER BY created_at,rowid LIMIT 20""")
                ]
            for run in runs:
                try:
                    await self.advance(run)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Managed run failed: %s", run["run_id"])
                    self.finish(
                        run["run_id"], "FAILED", "runner_error; inspect action history before retrying"
                    )

    async def advance(self, run):
        transfers = json.loads(run["plan"])["transfers"]
        for index, transfer in enumerate(transfers):
            request_id = run["run_id"] + "_" + str(index)
            with self.db.connect() as conn:
                state = conn.execute(
                    """SELECT r.status,a.active FROM agent_runs r JOIN agents a
                    ON a.agent_id=r.agent_id WHERE r.run_id=?""",
                    (run["run_id"],),
                ).fetchone()
                existing = conn.execute(
                    "SELECT * FROM actions WHERE agent_id=? AND request_id=?", (run["agent_id"], request_id)
                ).fetchone()
            if state["status"] == "CANCELLED" or not state["active"]:
                return
            if existing:
                result = dict(existing)
            else:
                with self.db.connect(write=True) as conn:
                    conn.execute(
                        "UPDATE agent_runs SET status='RUNNING' WHERE run_id=? AND status!='CANCELLED'",
                        (run["run_id"],),
                    )
                unsigned = {
                    "request_id": request_id,
                    "agent_id": run["agent_id"],
                    "action": "solana.transfer",
                    "params": transfer,
                    "timestamp": int(time.time()),
                }
                request = ActionRequest(
                    **unsigned, signature=sign(self.key(run["agent_id"]), canonical_bytes(unsigned))
                )
                # Existing action lookup + stable request IDs prevent a second broadcast after restart.
                result = await self.actions.submit(request)
            if result["status"] in ("PENDING", "PREPARING"):
                with self.db.connect(write=True) as conn:
                    conn.execute(
                        "UPDATE agent_runs SET status='WAITING' WHERE run_id=? AND status!='CANCELLED'",
                        (run["run_id"],),
                    )
                return
            if result["status"] != "VERIFIED":
                self.finish(
                    run["run_id"], "BLOCKED" if result["status"] == "REJECTED" else "FAILED", result["reason"]
                )
                return
        self.finish(run["run_id"], "COMPLETED")
