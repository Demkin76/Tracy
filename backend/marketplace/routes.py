from fastapi import APIRouter, Depends, Query

from backend.marketplace.models import EditPlan, Install, Offer, RunRequest


def marketplace_router(market, owner):
    router = APIRouter(prefix="/v1")

    @router.put("/agents/{agent_id}/offer")
    def offer(agent_id: str, payload: Offer, user=Depends(owner)):
        return market.offer(agent_id, user["user_id"], payload)

    @router.get("/agents/{agent_id}/offer")
    def own_offer(agent_id: str, user=Depends(owner)):
        market.agents.get(agent_id, user["user_id"])
        return {"offer": market.offer_info(agent_id, private=True)}

    @router.post("/installations", status_code=201)
    def install(payload: Install, user=Depends(owner)):
        return market.install(payload, user["user_id"])

    @router.get("/installations")
    def installations(user=Depends(owner)):
        return market.list(user["user_id"])

    @router.get("/installations/{agent_id}")
    def installation(agent_id: str, user=Depends(owner)):
        return market.get(agent_id, user["user_id"])

    @router.put("/installations/{agent_id}/plan")
    def plan(agent_id: str, payload: EditPlan, user=Depends(owner)):
        return market.edit(agent_id, user["user_id"], payload)

    @router.post("/installations/{agent_id}/runs", status_code=202)
    def run(agent_id: str, payload: RunRequest, user=Depends(owner)):
        return market.queue(agent_id, user["user_id"], payload.request_id)

    @router.get("/installations/{agent_id}/runs")
    def history(
        agent_id: str, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(owner)
    ):
        return market.history(agent_id, user["user_id"], limit, offset)

    @router.post("/installations/{agent_id}/start")
    def start(agent_id: str, user=Depends(owner)):
        return market.start(agent_id, user["user_id"])

    @router.post("/installations/{agent_id}/stop")
    def stop(agent_id: str, user=Depends(owner)):
        return market.stop(agent_id, user["user_id"])

    return router
