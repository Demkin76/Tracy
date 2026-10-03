import asyncio
import json
import sqlite3
import time
from uuid import uuid4

from fastapi import HTTPException

from backend.actions.models import ActionRequest
from backend.blockchain.solana import Evidence, PreflightRejected
from backend.crypto.hashing import canonical_bytes, digest
from backend.crypto.signatures import verify
from backend.policies.engine import evaluate, used_budget, utc_day


class ActionService:
    def __init__(self, settings, db, agents, receipts, gateway):
        self.settings, self.db, self.agents, self.receipts, self.gateway = (
            settings,
            db,
            agents,
            receipts,
            gateway,
        )

    def get(self, action_id):
        action = self.db.action(action_id)
        if action is None:
            raise HTTPException(404, "Action not found")
        return {
            **action,
            "receipt": self.receipts.get(action["receipt_id"]) if action["receipt_id"] else None,
        }

    async def submit(self, request: ActionRequest):
        try:
            agent = self.agents.get(request.agent_id)
        except HTTPException:
            self.db.audit("unknown_agent", request.agent_id, request.request_id)
            raise
        if not verify(agent["public_key"], request.signature, canonical_bytes(request.unsigned())):
            self.db.audit("invalid_signature", request.agent_id, request.request_id)
            raise HTTPException(401, "Invalid agent signature")
        now = int(time.time())
        if (
            not now - self.settings.request_max_age_seconds
            <= request.timestamp
            <= now + self.settings.request_future_skew_seconds
        ):
            self.db.audit("invalid_timestamp", request.agent_id, request.request_id)
            raise HTTPException(400, "Request timestamp is expired or too far in the future")
        if not agent["owner_id"]:
            raise HTTPException(403, "Legacy agent must be assigned to its owner before execution")
        action_id = "act_" + uuid4().hex
        # Admission, latest policy/status read, duplicate check and budget reservation are atomic.
        try:
            with self.db.connect(write=True) as conn:
                agent = conn.execute("SELECT * FROM agents WHERE agent_id=?", (request.agent_id,)).fetchone()
                if conn.execute("SELECT 1 FROM control_policies WHERE agent_id=?", (request.agent_id,)).fetchone():
                    raise HTTPException(403, "This agent is protected by Tracy control policies; use /v2/intents")
                policy = json.loads(agent["policy"])
                day = utc_day()
                context = {
                    "agent_active": bool(agent["active"]),
                    "status_version": agent["status_version"],
                    "execution_enabled": self.settings.execution_enabled,
                    "owner_limit_lamports": self.settings.owner_daily_lamports,
                    "platform_limit_lamports": self.settings.platform_daily_lamports,
                    "owner_used_lamports": conn.execute(
                        """SELECT COALESCE(sum(a.reserved_lamports),0)
                        FROM actions a JOIN agents g ON g.agent_id=a.agent_id
                        WHERE g.owner_id=? AND (a.budget_day=? OR a.status IN ('PENDING','PREPARING'))""",
                        (agent["owner_id"], day),
                    ).fetchone()[0],
                    "platform_used_lamports": conn.execute(
                        """SELECT COALESCE(sum(reserved_lamports),0)
                        FROM actions WHERE budget_day=? OR status IN ('PENDING','PREPARING')""",
                        (day,),
                    ).fetchone()[0],
                    "policy_version": agent["policy_version"],
                    "budget_day": day,
                    "daily_used_lamports": used_budget(conn, request.agent_id, day),
                }
                for scope in ("owner", "platform"):
                    extra_filter = " AND g.owner_id=?" if scope == "owner" else ""
                    extra_args = (agent["owner_id"],) if scope == "owner" else ()
                    context[scope + "_used_lamports"] += conn.execute(
                        """SELECT COALESCE(sum(i.reserved_units),0) FROM control_intents i JOIN agents g ON g.agent_id=i.agent_id
                        WHERE i.asset='SOL-lamports' AND (i.budget_day=? OR i.status NOT IN ('VERIFIED','REJECTED','FAILED'))""" + extra_filter,
                        (day, *extra_args)).fetchone()[0]
                approved, reason = evaluate(
                    request.action, request.params.model_dump(), policy, self.gateway.sender, context
                )
                conn.execute(
                    """INSERT INTO actions(action_id,agent_id,request_id,request,policy,sender,status,created_at,
                    policy_version,decision_context,reserved_lamports,budget_day) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        action_id,
                        request.agent_id,
                        request.request_id,
                        json.dumps(request.model_dump()),
                        json.dumps(policy),
                        self.gateway.sender,
                        "PREPARING",
                        now,
                        agent["policy_version"],
                        json.dumps(context),
                        request.params.lamports if approved else 0,
                        day,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            self.db.audit("replayed_request", request.agent_id, request.request_id)
            with self.db.connect() as conn:
                existing = conn.execute(
                    "SELECT action_id FROM actions WHERE agent_id=? AND request_id=?",
                    (request.agent_id, request.request_id),
                ).fetchone()
            raise HTTPException(
                409, {"reason": "request_id_already_used", "action_id": existing["action_id"]}
            ) from exc
        if not approved:
            self.receipts.finish(action_id, "REJECTED", reason, Evidence("not_executed", reason).to_dict())
            return self.get(action_id)
        try:
            prepared = await self.gateway.prepare(
                request.params.to, request.params.lamports, digest(request.unsigned())
            )
        except Exception:
            self.receipts.finish(
                action_id,
                "FAILED",
                "preparation_failed",
                Evidence("not_executed", "preparation_failed").to_dict(),
            )
            return self.get(action_id)

        # A stop/policy edit while prepare awaited RPC must prevent dispatch.
        with self.db.connect(write=True) as conn:
            current = conn.execute(
                "SELECT active,policy_version,status_version FROM agents WHERE agent_id=?",
                (request.agent_id,),
            ).fetchone()
            context["agent_active"] = bool(current["active"])
            context["dispatch_policy_version"] = current["policy_version"]
            context["dispatch_status_version"] = current["status_version"]
            approved, reason = evaluate(
                request.action, request.params.model_dump(), policy, self.gateway.sender, context
            )
            conn.execute(
                "UPDATE actions SET decision_context=? WHERE action_id=?", (json.dumps(context), action_id)
            )
            if approved:
                # This is the dispatch boundary: subsequent stops cannot cancel an already authorized broadcast.
                conn.execute(
                    "UPDATE actions SET status='PENDING',tx_signature=?,reason='awaiting_confirmation' WHERE action_id=?",
                    (prepared.signature, action_id),
                )
        if not approved:
            self.receipts.finish(action_id, "REJECTED", reason, Evidence("not_executed", reason).to_dict())
            return self.get(action_id)
        try:
            await self.gateway.broadcast(prepared)
        except PreflightRejected:
            self.receipts.finish(
                action_id,
                "FAILED",
                "preflight_rejected",
                Evidence("not_executed", "preflight_rejected").to_dict(),
            )
            return self.get(action_id)
        except Exception:
            self.db.update_action(action_id, reason="submission_uncertain")
        for attempt in range(self.settings.verification_attempts):
            result = await self.reconcile(action_id)
            if result["receipt_id"]:
                return result
            if attempt < self.settings.verification_attempts - 1:
                await asyncio.sleep(self.settings.verification_interval_seconds)
        return self.get(action_id)

    async def reconcile(self, action_id):
        action = self.get(action_id)
        if action["receipt_id"] or not action["tx_signature"]:
            return action
        request = ActionRequest.model_validate(action["request"])
        evidence = await self.gateway.verify_transfer(
            action["tx_signature"],
            action["sender"],
            request.params.to,
            request.params.lamports,
            digest(request.unsigned()),
        )
        with self.db.connect(write=True) as conn:
            attempts = action["check_attempts"] + 1
            conn.execute(
                """UPDATE actions SET check_attempts=check_attempts+1,last_checked_at=?,next_check_at=?
                WHERE action_id=? AND receipt_id IS NULL""",
                (int(time.time()), int(time.time()) + min(300, 5 * 2 ** min(attempts, 6)), action_id),
            )
        if evidence.status in ("verified", "mismatch", "failed"):
            self.receipts.finish(
                action_id,
                "VERIFIED" if evidence.status == "verified" else "FAILED",
                evidence.reason,
                evidence.to_dict(),
            )
        else:
            self.db.update_action(action_id, reason=evidence.reason)
        return self.get(action_id)

    def recover_unsubmitted(self):
        with self.db.connect() as conn:
            ids = [
                row["action_id"]
                for row in conn.execute("SELECT action_id FROM actions WHERE status='PREPARING'")
            ]
        for action_id in ids:
            action = self.db.action(action_id)
            approved, reason = evaluate(
                action["request"]["action"],
                action["request"]["params"],
                action["policy"],
                action["sender"],
                action["decision_context"],
            )
            if approved:
                reason = "interrupted_before_submission"
            self.receipts.finish(
                action_id,
                "FAILED" if approved else "REJECTED",
                reason,
                Evidence("not_executed", reason).to_dict(),
            )
