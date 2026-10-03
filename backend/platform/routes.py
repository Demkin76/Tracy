from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from backend.platform.account import AccountService
from backend.platform.models import (
    AccountRecovery,
    PasswordChange,
    ProfileEdit,
    Publication,
    RecoveryIssue,
    ShareProof,
)
from backend.platform.service import PlatformService

Status = Literal["", "VERIFIED", "REJECTED", "FAILED", "PENDING", "PREPARING"]


def platform_router(db, agents, receipts, verifier, auth, owner, manager, settings, runtime, gateway):
    router = APIRouter(prefix="/v1")
    platform = PlatformService(db, agents, receipts, verifier, settings)
    accounts = AccountService(db, auth)

    def public_verification_limit(request: Request):
        auth.throttle("public-verify:" + (request.client.host if request.client else "unknown"), 120)

    @router.get("/public/agents")
    def catalog(
        q: str = Query("", max_length=100),
        category: Literal["", "payouts", "automation", "research", "other"] = "",
        sort: Literal["recent", "verified", "reliability"] = "recent",
        limit: int = Query(12, ge=1, le=50),
        offset: int = Query(0, ge=0, le=100000),
    ):
        return platform.catalog(q, category, sort, limit, offset)

    @router.get("/public/agents/{agent_id}")
    def public_agent(agent_id: str):
        return platform.public_agent(agent_id)

    @router.get("/public/agents/{agent_id}/receipts")
    def public_history(
        agent_id: str, status: Status = "", limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        return platform.public_history(agent_id, status, limit, offset)

    @router.get("/public/receipts/{receipt_id}")
    def public_receipt(receipt_id: str):
        return platform.public_receipt(receipt_id)

    @router.get("/public/receipts/{receipt_id}/verify", dependencies=[Depends(public_verification_limit)])
    async def public_verify(receipt_id: str):
        platform.public_receipt(receipt_id)
        return await verifier.verify(receipt_id)

    @router.get("/public/receipts/{receipt_id}/chain")
    def public_chain(receipt_id: str):
        receipt = platform.public_receipt(receipt_id)
        import json

        with db.connect() as conn:
            rows = conn.execute(
                "SELECT body FROM receipts WHERE agent_id=? AND sequence<=? ORDER BY sequence",
                (receipt["agent_id"], receipt["sequence"]),
            ).fetchall()
        return {"items": [json.loads(r["body"]) for r in rows]}

    @router.get("/public/proofs/{share_id}")
    def shared_receipt(share_id: str):
        return platform.shared_receipt(share_id)

    @router.get("/public/proofs/{share_id}/verify", dependencies=[Depends(public_verification_limit)])
    async def shared_verify(share_id: str):
        receipt = platform.shared_receipt(share_id)
        return await verifier.verify(receipt["receipt_id"])

    @router.put("/agents/{agent_id}/publication")
    def publication(agent_id: str, payload: Publication, user=Depends(manager)):
        return platform.publish(agent_id, user["user_id"], payload)

    @router.post("/shares", status_code=201)
    def share(payload: ShareProof, user=Depends(manager)):
        return platform.share(user["user_id"], payload)

    @router.get("/shares")
    def shares(user=Depends(owner)):
        return platform.shares(user["user_id"])

    @router.delete("/shares/{share_id}")
    def unshare(share_id: str, user=Depends(manager)):
        platform.revoke_share(user["user_id"], share_id)
        return {"ok": True}

    @router.get("/favorites")
    def favorites(user=Depends(owner)):
        return platform.favorites(user["user_id"])

    @router.put("/favorites/{agent_id}")
    def favorite(agent_id: str, user=Depends(manager)):
        platform.favorite(user["user_id"], agent_id, True)
        return {"ok": True}

    @router.delete("/favorites/{agent_id}")
    def unfavorite(agent_id: str, user=Depends(manager)):
        platform.favorite(user["user_id"], agent_id, False)
        return {"ok": True}

    def history_filters(
        agent_id: str = Query("", max_length=80),
        status: Status = "",
        q: str = Query("", max_length=100),
        since: int = Query(0, ge=0),
        until: int = Query(0, ge=0),
    ):
        if until and until < since:
            raise HTTPException(422, "End date must be after start date")
        return dict(agent_id=agent_id, status=status, q=q, since=since, until=until)

    @router.get("/history")
    def history(
        filters=Depends(history_filters),
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user=Depends(owner),
    ):
        return platform.history(user["user_id"], limit=limit, offset=offset, **filters)

    @router.get("/history/export")
    def csv_export(filters=Depends(history_filters), user=Depends(owner)):
        return Response(
            platform.export_csv(user["user_id"], **filters),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="tracy-history.csv"'},
        )

    @router.get("/analytics")
    def analytics(days: int = Query(30, ge=1, le=90), user=Depends(owner)):
        return platform.analytics(user["user_id"], days)

    @router.get("/notifications")
    def notifications(user=Depends(owner)):
        return platform.notifications(user["user_id"])

    @router.post("/notifications/read")
    def read_notifications(user=Depends(manager)):
        platform.read_notifications(user["user_id"])
        return {"ok": True}

    @router.get("/funding")
    async def funding(user=Depends(owner)):
        result = platform.funding(user["user_id"])
        try:
            health = await gateway.health()
        except Exception:
            health = {"rpc_available": False, "balance_lamports": None}
        return {**result, **health, "execution_wallet": gateway.sender}

    @router.get("/runtime")
    def runtime_status(user=Depends(owner)):
        with db.connect() as conn:
            pending = conn.execute(
                """SELECT count(*) FROM actions a JOIN agents g ON g.agent_id=a.agent_id
                                      WHERE g.owner_id=? AND a.status='PENDING'""",
                (user["user_id"],),
            ).fetchone()[0]
        return {
            "reconciler_enabled": settings.reconciler_enabled,
            "last_tick_at": runtime.last_tick_at,
            "last_error_at": runtime.last_error_at,
            "pending_actions": pending,
        }

    @router.patch("/account/profile")
    def profile(payload: ProfileEdit, user=Depends(manager)):
        return accounts.profile(user["user_id"], payload)

    @router.post("/account/password")
    def password(payload: PasswordChange, user=Depends(manager)):
        auth.throttle("password:" + user["user_id"], 10)
        accounts.change_password(user["user_id"], payload)
        return {"ok": True, "sign_in_required": True}

    @router.post("/account/recovery-code")
    def recovery_code(payload: RecoveryIssue, user=Depends(manager)):
        auth.throttle("recovery-issue:" + user["user_id"], 10)
        return accounts.issue_recovery(user["user_id"], payload.current_password)

    @router.post("/auth/recover")
    def recover(payload: AccountRecovery, request: Request):
        auth.throttle("recovery:" + (request.client.host if request.client else "unknown"), 10)
        return accounts.recover(payload)

    @router.get("/account/events")
    def events(user=Depends(owner)):
        return accounts.events(user["user_id"])

    return router
