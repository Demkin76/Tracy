import asyncio
import json
import logging
import time
from uuid import uuid4

from fastapi import HTTPException

from backend.blockchain.solana import PreflightRejected
from backend.control.connectors import Registry
from backend.control.policy import evaluate
from backend.crypto.hashing import canonical_bytes, digest
from backend.crypto.signatures import sign, verify
from backend.policies.engine import utc_day

FINAL = ("VERIFIED", "REJECTED", "FAILED")
logger = logging.getLogger("tracy.control")


class ControlService:
    def __init__(self, db, agents, actions, receipts, settings):
        self.db, self.agents, self.actions, self.receipts, self.settings = (
            db,
            agents,
            actions,
            receipts,
            settings,
        )
        self.registry = Registry(settings, actions.gateway)
        self.lock = asyncio.Lock()

    def event(self, conn, agent_id, kind, data):
        head = conn.execute(
            "SELECT sequence,event_hash FROM control_events WHERE agent_id=? ORDER BY sequence DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        body = {
            "schema_version": "tracy.event/2",
            "agent_id": agent_id,
            "sequence": head["sequence"] + 1 if head else 1,
            "previous_hash": head["event_hash"] if head else None,
            "kind": kind,
            "data": data,
            "timestamp": int(time.time()),
            "public_key": self.receipts.public_key,
        }
        body["event_hash"] = digest(body)
        body["signature"] = sign(self.receipts.key, bytes.fromhex(body["event_hash"]))
        conn.execute(
            "INSERT INTO control_events VALUES(?,?,?,?)",
            (agent_id, body["sequence"], body["event_hash"], json.dumps(body)),
        )

    def policy(self, agent_id, owner_id):
        self.agents.get(agent_id, owner_id)
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM control_policies WHERE agent_id=?", (agent_id,)).fetchone()
        return (
            {"version": row["version"], "policy": json.loads(row["body"])}
            if row
            else {"version": 0, "policy": None}
        )

    def set_policy(self, agent_id, owner_id, payload):
        self.agents.get(agent_id, owner_id)
        for rule in payload.policy.rules:
            adapter = self.registry.adapter(self.registry.get(rule.resource_id, owner_id))
            if rule.action not in adapter.actions:
                raise HTTPException(422, "Action is not supported by its connector")
        with self.db.connect(write=True) as conn:
            old = conn.execute(
                "SELECT version FROM control_policies WHERE agent_id=?", (agent_id,)
            ).fetchone()
            version = old["version"] if old else 0
            if version != payload.expected_version:
                raise HTTPException(409, "Policy changed; reload before saving")
            conn.execute("UPDATE agents SET status_version=status_version+1 WHERE agent_id=?", (agent_id,))
            body, now = json.dumps(payload.policy.model_dump()), int(time.time())
            conn.execute(
                "INSERT INTO control_policy_versions VALUES(?,?,?,?)", (agent_id, version + 1, body, now)
            )
            conn.execute(
                """INSERT INTO control_policies VALUES(?,?,?,?) ON CONFLICT(agent_id)
                DO UPDATE SET version=excluded.version,body=excluded.body,updated_at=excluded.updated_at""",
                (agent_id, version + 1, body, now),
            )
            conn.execute("UPDATE installations SET running=0,next_run_at=NULL WHERE agent_id=?", (agent_id,))
            conn.execute(
                """UPDATE agent_runs SET status='CANCELLED',reason='control_layer_enabled',completed_at=?
                WHERE agent_id=? AND status IN ('QUEUED','RUNNING','WAITING')""",
                (now, agent_id),
            )
            self.event(
                conn,
                agent_id,
                "policy_updated",
                {"version": version + 1, "policy": payload.policy.model_dump(), "actor": owner_id},
            )
        return self.policy(agent_id, owner_id)

    def create_task(self, payload, owner_id):
        self.agents.get(payload.agent_id, owner_id)
        if not self.policy(payload.agent_id, owner_id)["policy"]:
            raise HTTPException(409, "Configure a control policy first")
        for resource in payload.allowed_resources:
            self.registry.get(resource, owner_id)
        task_id, now = "task_" + uuid4().hex, int(time.time())
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO control_tasks VALUES(?,?,?,?,?,1,?)",
                (
                    task_id,
                    payload.agent_id,
                    payload.purpose,
                    json.dumps(payload.model_dump()),
                    now + payload.expires_in_seconds,
                    now,
                ),
            )
            self.event(
                conn,
                payload.agent_id,
                "task_granted",
                {
                    "task_id": task_id,
                    "scope": payload.model_dump(),
                    "expires_at": now + payload.expires_in_seconds,
                    "actor": owner_id,
                },
            )
        return self.task(task_id, owner_id)

    def task(self, task_id, owner_id):
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT t.* FROM control_tasks t JOIN agents a ON a.agent_id=t.agent_id
                WHERE t.task_id=? AND a.owner_id=?""",
                (task_id, owner_id),
            ).fetchone()
        if not row:
            raise HTTPException(404, "Task not found")
        return {**dict(row), "body": json.loads(row["body"]), "active": bool(row["active"])}

    def revoke_task(self, task_id, owner_id):
        row = self.task(task_id, owner_id)
        with self.db.connect(write=True) as conn:
            conn.execute("UPDATE control_tasks SET active=0 WHERE task_id=?", (task_id,))
            self.event(conn, row["agent_id"], "task_revoked", {"task_id": task_id, "actor": owner_id})
        return {"ok": True}

    def authenticate_agent(self, agent_id, timestamp, signature, unsigned):
        agent = self.agents.get(agent_id)
        now = int(time.time())
        if (
            not now - self.settings.request_max_age_seconds
            <= timestamp
            <= now + self.settings.request_future_skew_seconds
        ):
            raise HTTPException(401, "Signed request timestamp expired")
        if not verify(agent["public_key"], signature, canonical_bytes(unsigned)):
            raise HTTPException(401, "Invalid agent signature")
        if not agent["owner_id"]:
            raise HTTPException(403, "Agent has no owner")
        return agent

    def get(self, intent_id, owner_id=None, agent_id=None):
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT i.*,a.owner_id FROM control_intents i JOIN agents a ON a.agent_id=i.agent_id
                WHERE i.intent_id=?""",
                (intent_id,),
            ).fetchone()
            if (
                not row
                or (owner_id and row["owner_id"] != owner_id)
                or (agent_id and row["agent_id"] != agent_id)
            ):
                raise HTTPException(404, "Intent not found")
            result = dict(row)
            result.pop("prepared")
            for name in ("request", "policy", "context", "approval", "result"):
                result[name] = json.loads(result[name]) if result[name] else None
            receipt = conn.execute(
                "SELECT body FROM control_receipts WHERE intent_id=?", (intent_id,)
            ).fetchone()
            result["receipt"] = json.loads(receipt["body"]) if receipt else None
        return result

    def submit(self, request):
        agent = self.authenticate_agent(
            request.agent_id, request.timestamp, request.signature, request.unsigned()
        )
        now, intent_id = int(time.time()), "intent_" + uuid4().hex
        fingerprint = digest(request.unsigned())
        semantic = {k: v for k, v in request.unsigned().items() if k != "timestamp"}
        with self.db.connect(write=True) as conn:
            previous = conn.execute(
                "SELECT intent_id,request FROM control_intents WHERE agent_id=? AND request_id=?",
                (request.agent_id, request.request_id),
            ).fetchone()
            if previous:
                if {
                    k: v
                    for k, v in json.loads(previous["request"]).items()
                    if k not in ("timestamp", "signature")
                } != semantic:
                    raise HTTPException(409, "Request ID already used for another intent")
                return self.get(previous["intent_id"], agent_id=request.agent_id)
            task = conn.execute(
                "SELECT * FROM control_tasks WHERE task_id=? AND agent_id=?",
                (request.task_id, request.agent_id),
            ).fetchone()
            policy = conn.execute(
                "SELECT * FROM control_policies WHERE agent_id=?", (request.agent_id,)
            ).fetchone()
            if not task or not policy:
                self.event(
                    conn,
                    request.agent_id,
                    "intent_refused",
                    {"request_hash": fingerprint, "reason": "unknown_task_or_policy"},
                )
                conn.commit()
                raise HTTPException(403, "Owner must grant task and policy")
            agent = conn.execute("SELECT * FROM agents WHERE agent_id=?", (request.agent_id,)).fetchone()
            target, units, asset, connector_hash, error = "", 0, "unknown", "", None
            try:
                resource = self.registry.get(request.resource_id, agent["owner_id"])
                adapter = self.registry.adapter(resource)
                target, units = adapter.validate(request.action, request.params)
                asset, connector_hash = adapter.asset, digest(resource)
                if not adapter.configured():
                    error = "connector_not_configured"
            except (ValueError, KeyError, TypeError, HTTPException):
                error = "unsupported_action_resource_or_parameters"
            day = utc_day()
            used = conn.execute(
                """SELECT coalesce(sum(reserved_units),0) FROM control_intents
                WHERE agent_id=? AND action=? AND resource_id=? AND (budget_day=? OR status NOT IN ('VERIFIED','REJECTED','FAILED'))""",
                (request.agent_id, request.action, request.resource_id, day),
            ).fetchone()[0]
            c = {
                "now": now,
                "agent_active": bool(agent["active"]),
                "status_version": agent["status_version"],
                "execution_enabled": self.settings.execution_enabled,
                "task_active": bool(task["active"]),
                "task_expires_at": task["expires_at"],
                "task": json.loads(task["body"]),
                "target": target,
                "units": units,
                "used_units": used,
                "policy_version": policy["version"],
                "validation_error": error,
                "recent_count": conn.execute(
                    "SELECT count(*) FROM control_intents WHERE agent_id=? AND created_at>?",
                    (request.agent_id, now - 60),
                ).fetchone()[0],
                "denial_count": conn.execute(
                    "SELECT count(*) FROM control_intents WHERE agent_id=? AND status='REJECTED' AND created_at>?",
                    (request.agent_id, now - 3600),
                ).fetchone()[0],
                "target_seen": bool(
                    conn.execute(
                        """SELECT 1 FROM control_intents WHERE agent_id=? AND resource_id=?
                     AND action=? AND target=? AND status='VERIFIED' LIMIT 1""",
                        (request.agent_id, request.resource_id, request.action, target),
                    ).fetchone()
                ),
            }
            if asset == "SOL-lamports":
                self.solana_quota(conn, c, agent["owner_id"], day)
            snapshot = json.loads(policy["body"])
            decision, reason = evaluate(snapshot, request.unsigned(), c)
            status = (
                "AWAITING_APPROVAL"
                if decision == "review"
                else "QUEUED"
                if decision == "allow"
                else "REJECTED"
            )
            conn.execute(
                """INSERT INTO control_intents(intent_id,agent_id,request_id,task_id,action,resource_id,
                request,intent_hash,policy,policy_version,context,connector_hash,status,reason,target,units,
                reserved_units,asset,budget_day,created_at,approval_expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    intent_id,
                    request.agent_id,
                    request.request_id,
                    request.task_id,
                    request.action,
                    request.resource_id,
                    json.dumps(request.model_dump()),
                    fingerprint,
                    policy["body"],
                    policy["version"],
                    json.dumps(c),
                    connector_hash,
                    status,
                    reason,
                    target,
                    units,
                    units if decision != "deny" else 0,
                    asset,
                    day,
                    now,
                    now + snapshot["approval_ttl_seconds"] if decision == "review" else None,
                ),
            )
            self.event(
                conn,
                request.agent_id,
                "intent_received",
                {
                    "intent_id": intent_id,
                    "intent_hash": fingerprint,
                    "request": request.model_dump(),
                    "decision": decision,
                    "reason": reason,
                    "context": c,
                },
            )
            if decision == "deny":
                self.finish(
                    conn,
                    intent_id,
                    "REJECTED",
                    reason,
                    {"status": "not_executed", "source": "policy_engine"},
                    True,
                )
        return self.get(intent_id, agent_id=request.agent_id)

    def solana_quota(self, conn, c, owner_id, day):
        for scope in ("owner", "platform"):
            clause, args = (" AND a.owner_id=?", (owner_id,)) if scope == "owner" else ("", ())
            legacy = conn.execute(
                """SELECT coalesce(sum(i.reserved_lamports),0) FROM actions i JOIN agents a
                ON a.agent_id=i.agent_id WHERE (i.budget_day=? OR i.status IN ('PREPARING','PENDING'))"""
                + clause,
                (day, *args),
            ).fetchone()[0]
            generic = conn.execute(
                """SELECT coalesce(sum(i.reserved_units),0) FROM control_intents i JOIN agents a
                ON a.agent_id=i.agent_id WHERE i.asset='SOL-lamports' AND
                (i.budget_day=? OR i.status NOT IN ('VERIFIED','REJECTED','FAILED'))"""
                + clause,
                (day, *args),
            ).fetchone()[0]
            c[scope + "_used"], c[scope + "_limit"] = (
                legacy + generic,
                getattr(self.settings, scope + "_daily_lamports"),
            )

    def finish(self, conn, intent_id, status, reason, evidence, release=False):
        row = conn.execute("SELECT * FROM control_intents WHERE intent_id=?", (intent_id,)).fetchone()
        if row["receipt_id"]:
            return
        key = conn.execute("SELECT public_key FROM agents WHERE agent_id=?", (row["agent_id"],)).fetchone()[0]
        head = conn.execute(
            "SELECT sequence,receipt_hash FROM control_receipts WHERE agent_id=? ORDER BY sequence DESC LIMIT 1",
            (row["agent_id"],),
        ).fetchone()
        body = {
            "schema_version": "tracy.receipt/2",
            "receipt_id": "proof_" + uuid4().hex,
            "intent_id": intent_id,
            "agent_id": row["agent_id"],
            "agent_public_key": key,
            "intent": json.loads(row["request"]),
            "intent_hash": row["intent_hash"],
            "task": json.loads(row["context"])["task"],
            "policy": {
                "version": row["policy_version"],
                "snapshot": json.loads(row["policy"]),
                "context": json.loads(row["context"]),
            },
            "approval": json.loads(row["approval"]) if row["approval"] else None,
            "connector_hash": row["connector_hash"],
            "status": status,
            "reason": reason,
            "execution": json.loads(row["result"]) if row["result"] else None,
            "verification": evidence,
            "timestamp": int(time.time()),
            "sequence": head["sequence"] + 1 if head else 1,
            "previous_receipt_hash": head["receipt_hash"] if head else None,
            "poa_public_key": self.receipts.public_key,
        }
        body["receipt_hash"] = digest(body)
        body["poa_signature"] = sign(self.receipts.key, bytes.fromhex(body["receipt_hash"]))
        conn.execute(
            "INSERT INTO control_receipts VALUES(?,?,?,?,?,?)",
            (
                body["receipt_id"],
                intent_id,
                row["agent_id"],
                body["sequence"],
                body["receipt_hash"],
                json.dumps(body),
            ),
        )
        conn.execute(
            """UPDATE control_intents SET status=?,reason=?,receipt_id=?,
            reserved_units=CASE WHEN ? THEN 0 ELSE reserved_units END WHERE intent_id=?""",
            (status, reason, body["receipt_id"], int(release), intent_id),
        )
        self.event(
            conn,
            row["agent_id"],
            "intent_finished",
            {
                "intent_id": intent_id,
                "status": status,
                "receipt_hash": body["receipt_hash"],
                "reason": reason,
            },
        )

    def decide(self, intent_id, owner_id, payload):
        self.get(intent_id, owner_id)
        with self.db.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM control_intents WHERE intent_id=?", (intent_id,)).fetchone()
            if row["status"] != "AWAITING_APPROVAL":
                raise HTTPException(409, "Intent is no longer awaiting approval")
            if payload.intent_hash != row["intent_hash"] or payload.policy_version != row["policy_version"]:
                raise HTTPException(409, "Approval does not match reviewed intent and policy")
            current = conn.execute(
                "SELECT version FROM control_policies WHERE agent_id=?", (row["agent_id"],)
            ).fetchone()
            if current["version"] != row["policy_version"] or row["approval_expires_at"] <= int(time.time()):
                raise HTTPException(409, "Approval expired or policy changed; submit a new intent")
            approval = {
                "decision": payload.decision,
                "actor": owner_id,
                "timestamp": int(time.time()),
                "note": payload.note,
                "intent_hash": row["intent_hash"],
                "policy_version": row["policy_version"],
                "expires_at": row["approval_expires_at"],
            }
            conn.execute(
                "UPDATE control_intents SET approval=?,status=?,next_check_at=0 WHERE intent_id=?",
                (
                    json.dumps(approval),
                    "QUEUED" if payload.decision == "approve" else "AWAITING_APPROVAL",
                    intent_id,
                ),
            )
            self.event(conn, row["agent_id"], "human_decision", {"intent_id": intent_id, **approval})
            if payload.decision == "deny":
                self.finish(
                    conn,
                    intent_id,
                    "REJECTED",
                    "human_denied",
                    {"status": "not_executed", "source": "human_approval"},
                    True,
                )
        return self.get(intent_id, owner_id)

    def recheck(self, conn, row):
        c = json.loads(row["context"])
        agent = conn.execute("SELECT * FROM agents WHERE agent_id=?", (row["agent_id"],)).fetchone()
        task = conn.execute("SELECT * FROM control_tasks WHERE task_id=?", (row["task_id"],)).fetchone()
        version = conn.execute(
            "SELECT version FROM control_policies WHERE agent_id=?", (row["agent_id"],)
        ).fetchone()[0]
        c.update(
            now=int(time.time()),
            agent_active=bool(agent["active"]),
            execution_enabled=self.settings.execution_enabled,
            task_active=bool(task["active"]),
            task_expires_at=task["expires_at"],
            dispatch_policy_version=version,
            dispatch_status_version=agent["status_version"],
        )
        try:
            resource = self.registry.get(row["resource_id"], agent["owner_id"])
            c["connector_changed"] = digest(resource) != row["connector_hash"]
            if not self.registry.adapter(resource).configured():
                c["validation_error"] = "connector_not_configured"
        except (HTTPException, ValueError, KeyError):
            c["connector_changed"] = True
        day = utc_day()
        c["used_units"] = conn.execute(
            """SELECT coalesce(sum(reserved_units),0) FROM control_intents
            WHERE agent_id=? AND action=? AND resource_id=? AND intent_id!=?
            AND (budget_day=? OR status NOT IN ('VERIFIED','REJECTED','FAILED'))""",
            (row["agent_id"], row["action"], row["resource_id"], row["intent_id"], day),
        ).fetchone()[0]
        if row["asset"] == "SOL-lamports":
            self.solana_quota(conn, c, agent["owner_id"], day)
            for scope in ("owner", "platform"):
                c[scope + "_used"] -= row["reserved_units"]
        c["budget_day"] = day
        conn.execute("UPDATE control_intents SET budget_day=? WHERE intent_id=?", (day, row["intent_id"]))
        decision, reason = evaluate(json.loads(row["policy"]), json.loads(row["request"]), c)
        if decision == "review":
            approval = json.loads(row["approval"]) if row["approval"] else None
            if not approval or approval["decision"] != "approve" or approval["expires_at"] <= c["now"]:
                decision, reason = "deny", "approval_expired_or_missing"
        conn.execute(
            "UPDATE control_intents SET context=? WHERE intent_id=?", (json.dumps(c), row["intent_id"])
        )
        return decision != "deny", reason

    async def advance(self, intent_id):
        with self.db.connect() as conn:
            row = dict(
                conn.execute("SELECT * FROM control_intents WHERE intent_id=?", (intent_id,)).fetchone()
            )
            owner_id = conn.execute(
                "SELECT owner_id FROM agents WHERE agent_id=?", (row["agent_id"],)
            ).fetchone()[0]
        if row["status"] in FINAL:
            return
        if row["status"] == "AWAITING_APPROVAL":
            with self.db.connect(write=True) as conn:
                a = conn.execute(
                    "SELECT active,status_version FROM agents WHERE agent_id=?", (row["agent_id"],)
                ).fetchone()
                t = conn.execute(
                    "SELECT active,expires_at FROM control_tasks WHERE task_id=?", (row["task_id"],)
                ).fetchone()
                v = conn.execute(
                    "SELECT version FROM control_policies WHERE agent_id=?", (row["agent_id"],)
                ).fetchone()[0]
                if (
                    row["approval_expires_at"] <= int(time.time())
                    or not a["active"]
                    or not t["active"]
                    or t["expires_at"] <= int(time.time())
                    or v != row["policy_version"]
                    or a["status_version"] != json.loads(row["context"])["status_version"]
                ):
                    self.finish(
                        conn,
                        intent_id,
                        "REJECTED",
                        "approval_invalidated",
                        {"status": "not_executed", "source": "control_plane"},
                        True,
                    )
                else:
                    conn.execute(
                        "UPDATE control_intents SET next_check_at=? WHERE intent_id=?",
                        (min(int(time.time()) + 30, row["approval_expires_at"]), intent_id),
                    )
            return
        if row["status"] == "QUEUED":
            with self.db.connect(write=True) as conn:
                allowed, reason = self.recheck(conn, row)
                if not allowed:
                    self.finish(
                        conn,
                        intent_id,
                        "REJECTED",
                        reason,
                        {"status": "not_executed", "source": "dispatch_policy"},
                        True,
                    )
                    return
            resource = self.registry.get(row["resource_id"], owner_id)
            adapter = self.registry.adapter(resource)
            try:
                prepared = await adapter.prepare(json.loads(row["request"]), intent_id, row["intent_hash"])
            except Exception:
                with self.db.connect(write=True) as conn:
                    self.finish(
                        conn,
                        intent_id,
                        "FAILED",
                        "preparation_failed",
                        {"status": "not_executed", "source": resource["kind"]},
                        True,
                    )
                return
            with self.db.connect(write=True) as conn:
                fresh = conn.execute(
                    "SELECT * FROM control_intents WHERE intent_id=?", (intent_id,)
                ).fetchone()
                allowed, reason = self.recheck(conn, fresh)
                if not allowed:
                    self.finish(
                        conn,
                        intent_id,
                        "REJECTED",
                        reason,
                        {"status": "not_executed", "source": "dispatch_policy"},
                        True,
                    )
                    return
                conn.execute(
                    "UPDATE control_intents SET status='DISPATCHED',prepared=?,reason='awaiting_evidence' WHERE intent_id=?",
                    (json.dumps(prepared), intent_id),
                )
                self.event(
                    conn,
                    row["agent_id"],
                    "execution_dispatched",
                    {"intent_id": intent_id, "intent_hash": row["intent_hash"]},
                )
            try:
                result = await adapter.execute(prepared)
                with self.db.connect(write=True) as conn:
                    conn.execute(
                        "UPDATE control_intents SET result=? WHERE intent_id=?",
                        (json.dumps(result), intent_id),
                    )
            except PreflightRejected:
                with self.db.connect(write=True) as conn:
                    self.finish(
                        conn,
                        intent_id,
                        "FAILED",
                        "preflight_rejected",
                        {"status": "not_executed", "source": resource["kind"]},
                        True,
                    )
                return
            except Exception:
                result = None  # Uncertain write: read back, never resend.
        else:
            resource = self.registry.get(row["resource_id"], owner_id)
            adapter = self.registry.adapter(resource)
            prepared = json.loads(row["prepared"])
            result = json.loads(row["result"]) if row["result"] else None
            if digest(resource) != row["connector_hash"]:
                with self.db.connect(write=True) as conn:
                    conn.execute(
                        "UPDATE control_intents SET status='UNCERTAIN',reason='connector_changed_after_dispatch',next_check_at=? WHERE intent_id=?",
                        (int(time.time()) + 60, intent_id),
                    )
                return
        try:
            evidence = await adapter.verify(prepared, result)
        except Exception:
            evidence = {
                "status": "unavailable",
                "reason": "verification_unavailable",
                "source": resource["kind"],
            }
        with self.db.connect(write=True) as conn:
            if evidence["status"] in ("verified", "mismatch", "failed"):
                self.finish(
                    conn,
                    intent_id,
                    "VERIFIED" if evidence["status"] == "verified" else "FAILED",
                    evidence["reason"],
                    evidence,
                    evidence["status"] == "failed",
                )
            else:
                attempts = row["attempts"] + 1
                conn.execute(
                    "UPDATE control_intents SET status='UNCERTAIN',reason=?,attempts=?,next_check_at=? WHERE intent_id=?",
                    (
                        evidence["reason"],
                        attempts,
                        int(time.time()) + min(300, 5 * 2 ** min(attempts, 6)),
                        intent_id,
                    ),
                )

    async def tick(self):
        async with self.lock:
            with self.db.connect() as conn:
                ids = [
                    r[0]
                    for r in conn.execute(
                        """SELECT intent_id FROM control_intents WHERE
                    status NOT IN ('VERIFIED','REJECTED','FAILED') AND next_check_at<=? ORDER BY created_at,rowid LIMIT 30""",
                        (int(time.time()),),
                    )
                ]
            for intent_id in ids:
                try:
                    await self.advance(intent_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Control intent processing failed: %s", intent_id)
                    with self.db.connect(write=True) as conn:
                        conn.execute(
                            "UPDATE control_intents SET next_check_at=?,reason='connector_unavailable' WHERE intent_id=? AND receipt_id IS NULL",
                            (int(time.time()) + 60, intent_id),
                        )

    def list(self, owner_id, status="", agent_id="", limit=50, offset=0):
        with self.db.connect() as conn:
            where = "a.owner_id=? AND (?='' OR i.status=?) AND (?='' OR i.agent_id=?)"
            args = (owner_id, status, status, agent_id, agent_id)
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT i.intent_id FROM control_intents i JOIN agents a ON a.agent_id=i.agent_id WHERE "
                    + where
                    + " ORDER BY i.created_at DESC,i.rowid DESC LIMIT ? OFFSET ?",
                    (*args, limit, offset),
                )
            ]
            total = conn.execute(
                "SELECT count(*) FROM control_intents i JOIN agents a ON a.agent_id=i.agent_id WHERE "
                + where,
                args,
            ).fetchone()[0]
        return {"items": [self.get(i, owner_id) for i in ids], "total": total}

    def audit(self, agent_id, owner_id):
        self.agents.get(agent_id, owner_id)
        with self.db.connect() as conn:
            return {
                "items": [
                    json.loads(r[0])
                    for r in conn.execute(
                        "SELECT body FROM control_events WHERE agent_id=? ORDER BY sequence", (agent_id,)
                    )
                ],
                "public_key": self.receipts.public_key,
            }

    async def verify_receipt(self, intent_id, owner_id):
        from backend.control.verify import verify_bundle

        item = self.get(intent_id, owner_id)
        if not item["receipt"]:
            raise HTTPException(409, "Intent has no terminal receipt yet")
        with self.db.connect() as conn:
            chain = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT body FROM control_receipts WHERE agent_id=? AND sequence<=? ORDER BY sequence",
                    (item["agent_id"], item["receipt"]["sequence"]),
                )
            ]
            raw = conn.execute(
                "SELECT prepared FROM control_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()[0]
        checks = verify_bundle(chain, self.receipts.public_key)
        evidence = {"status": "not_applicable", "source": "policy_engine"}
        if item["status"] == "VERIFIED":
            try:
                resource = self.registry.get(item["resource_id"], owner_id)
                if digest(resource) != item["connector_hash"]:
                    raise ValueError("Connector binding changed")
                evidence = await self.registry.adapter(resource).verify(json.loads(raw), item["result"])
            except Exception:
                evidence = {"status": "unavailable", "source": "external_readback"}
        return {
            **checks,
            "live_evidence": evidence,
            "verified_result": checks["valid"]
            and item["status"] == "VERIFIED"
            and evidence["status"] == "verified",
            "receipt_status": item["status"],
        }
