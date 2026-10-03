import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.agents.models import RegisterAgent
from backend.control.models import Decision, Identity, Intent, Lookup, Policy, PolicyUpdate, TaskCreate


def control_router(control, owner):
    router = APIRouter(prefix="/v2")

    @router.post("/agents", status_code=201)
    def enroll(payload: Identity, user=Depends(owner)):
        from pydantic import ValidationError

        try:
            legacy = RegisterAgent(
                **payload.model_dump(),
                policy={
                    "allowed_actions": [],
                    "allowed_recipients": [control.actions.gateway.sender],
                    "max_transfer_sol": 0.000000001,
                    "daily_budget_sol": 0.000000001,
                },
            )
        except ValidationError:
            raise HTTPException(422, "Invalid agent identity")
        agent = control.agents.register(legacy, user["user_id"])
        control.set_policy(
            agent["agent_id"], user["user_id"], PolicyUpdate(expected_version=0, policy=Policy(rules=[]))
        )
        return agent

    @router.get("/resources")
    def resources(user=Depends(owner)):
        return {"items": control.registry.public(user["user_id"])}

    @router.get("/agents/{agent_id}/policy")
    def policy(agent_id: str, user=Depends(owner)):
        return control.policy(agent_id, user["user_id"])

    @router.put("/agents/{agent_id}/policy")
    def update_policy(agent_id: str, payload: PolicyUpdate, user=Depends(owner)):
        return control.set_policy(agent_id, user["user_id"], payload)

    @router.post("/tasks", status_code=201)
    def task(payload: TaskCreate, user=Depends(owner)):
        return control.create_task(payload, user["user_id"])

    @router.get("/tasks")
    def tasks(agent_id: str = "", user=Depends(owner)):
        with control.db.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    """SELECT t.task_id FROM control_tasks t JOIN agents a
                ON a.agent_id=t.agent_id WHERE a.owner_id=? AND (?='' OR t.agent_id=?)
                ORDER BY t.created_at DESC,t.rowid DESC LIMIT 100""",
                    (user["user_id"], agent_id, agent_id),
                )
            ]
        return {"items": [control.task(t, user["user_id"]) for t in ids]}

    @router.post("/tasks/{task_id}/revoke")
    def revoke(task_id: str, user=Depends(owner)):
        return control.revoke_task(task_id, user["user_id"])

    @router.post("/intents", status_code=202)
    def submit(payload: Intent):
        return control.submit(payload)

    @router.post("/intents/lookup")
    def lookup(payload: Lookup):
        control.authenticate_agent(
            payload.agent_id, payload.timestamp, payload.signature, payload.model_dump(exclude={"signature"})
        )
        return control.get(payload.intent_id, agent_id=payload.agent_id)

    @router.get("/intents")
    def intents(
        status: str = "",
        agent_id: str = "",
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user=Depends(owner),
    ):
        return control.list(user["user_id"], status, agent_id, limit, offset)

    @router.get("/intents/{intent_id}")
    def intent(intent_id: str, user=Depends(owner)):
        return control.get(intent_id, user["user_id"])

    @router.post("/intents/{intent_id}/decision")
    def decide(intent_id: str, payload: Decision, request: Request, user=Depends(owner)):
        if request.headers.get("authorization") or not user.get("csrf_token"):
            raise HTTPException(
                403, "Human approval requires an authenticated browser session and CSRF token"
            )
        return control.decide(intent_id, user["user_id"], payload)

    @router.get("/intents/{intent_id}/verify")
    async def verify(intent_id: str, user=Depends(owner)):
        return await control.verify_receipt(intent_id, user["user_id"])

    @router.get("/agents/{agent_id}/audit")
    def audit(agent_id: str, user=Depends(owner)):
        return control.audit(agent_id, user["user_id"])

    @router.get("/agents/{agent_id}/export")
    def export(agent_id: str, user=Depends(owner)):
        bundle = control.audit(agent_id, user["user_id"])
        with control.db.connect() as conn:
            bundle["receipts"] = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT body FROM control_receipts WHERE agent_id=? ORDER BY sequence", (agent_id,)
                )
            ]
        return bundle

    return router
