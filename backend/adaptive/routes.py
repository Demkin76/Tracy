from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from backend.adaptive.models import (
    Blueprint,
    BuilderRequest,
    CloneBundle,
    Experiment,
    ForkStrategy,
    PineImport,
    Program,
    Publication,
    Review,
    StartReview,
)
from backend.adaptive.pine import EXAMPLE, parse


def adaptive_router(service, forward, anchors, owner, auth):
    router = APIRouter(prefix="/v1", tags=["Adaptive devnet lab"])

    @router.get("/adaptive/capabilities")
    def capabilities():
        return {
            "execution": "paper",
            "evidence_network": "solana-devnet",
            "devnet_anchors_enabled": service.s.settings.adaptive_devnet_anchors_enabled,
            "forward_worker_enabled": service.s.settings.reconciler_enabled,
            "pine_example": EXAMPLE,
            "mainnet_enabled": False,
        }

    @router.post("/adaptive/import-pine")
    def pine(payload: PineImport, user=Depends(owner)):
        return parse(payload.source)

    @router.post("/adaptive/export-pine")
    def export_pine(payload: Program, user=Depends(owner)):
        from backend.adaptive.pine import export

        return export(payload)

    @router.post("/adaptive/agents", status_code=201)
    def create(payload: Blueprint, user=Depends(owner)):
        return service.create(payload, user["user_id"])

    @router.post("/adaptive/from-strategy", status_code=201)
    def fork(payload: ForkStrategy, user=Depends(owner)):
        try:
            return service.fork(payload, user["user_id"])
        except ValidationError as exc:
            raise HTTPException(
                422,
                "Strategy is outside the devnet learning bounds: use allocation <=25%, positive threshold and sufficient automatic approval allowance",
            ) from exc

    @router.get("/adaptive/agents")
    def listing(user=Depends(owner)):
        with service.db.connect() as conn:
            return {
                "items": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT agent_id,name,revision,created_at FROM adaptive_agents WHERE owner_id=? ORDER BY created_at DESC",
                        (user["user_id"],),
                    )
                ]
            }

    @router.get("/adaptive/agents/{aid}")
    def get(aid: str, user=Depends(owner)):
        result = service.get(aid, user["user_id"])
        with service.db.connect() as conn:
            result["forward_runs"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT forward_id,status FROM adaptive_forward WHERE agent_id=? ORDER BY rowid DESC",
                    (aid,),
                )
            ]
        return result

    @router.post("/adaptive/agents/{aid}/experiments", status_code=201)
    def train(aid: str, payload: Experiment, user=Depends(owner)):
        return service.train(aid, user["user_id"], payload)

    @router.post("/adaptive/agents/{aid}/activate")
    def activate(aid: str, payload: Review, user=Depends(owner)):
        return service.activate(aid, user["user_id"], payload)

    @router.post("/adaptive/agents/{aid}/bundles", status_code=201)
    def freeze(aid: str, revision: int, user=Depends(owner)):
        return service.bundle(aid, user["user_id"], revision)

    @router.get("/adaptive/bundles/{bid}")
    def own_bundle(bid: str, user=Depends(owner)):
        return service.get_bundle(bid, user["user_id"])

    @router.put("/adaptive/bundles/{bid}/publication")
    def publish(bid: str, payload: Publication, user=Depends(owner)):
        return service.publish(bid, user["user_id"], payload.listed)

    @router.post("/adaptive/bundles/{bid}/clone", status_code=201)
    def clone(bid: str, payload: CloneBundle, user=Depends(owner)):
        return service.clone(bid, user["user_id"], payload)

    @router.post("/adaptive/bundles/{bid}/anchor")
    async def anchor(bid: str, user=Depends(owner)):
        return await anchors.anchor(bid, user["user_id"])

    @router.get("/public/bundles")
    def catalog():
        return service.catalog()

    @router.get("/public/bundles/{bid}")
    def public_bundle(bid: str):
        return service.get_bundle(bid)

    @router.post("/adaptive/agents/{aid}/review")
    def review_start(aid: str, payload: StartReview, user=Depends(owner)):
        return service.review_start(aid, user["user_id"], payload)

    @router.get("/adaptive/agents/{aid}/evolution")
    def evolution(aid: str, user=Depends(owner)):
        return service.learning.evolution(aid, user["user_id"])

    @router.post("/adaptive/agents/{aid}/forward", status_code=201)
    def start(aid: str, revision: int, user=Depends(owner)):
        if not service.s.settings.reconciler_enabled:
            raise HTTPException(
                409, "Start the background worker before scheduling a 24-hour forward experiment"
            )
        return forward.start(aid, user["user_id"], revision)

    @router.get("/adaptive/forward/{fid}")
    def forward_result(fid: str, user=Depends(owner)):
        return forward.get(fid, user["user_id"])

    @router.post("/adaptive/forward/{fid}/stop")
    def stop(fid: str, user=Depends(owner)):
        return forward.stop(fid, user["user_id"])

    @router.post("/adaptive/forward/{fid}/refresh")
    def refresh(fid: str, user=Depends(owner)):
        return forward.advance(fid, user["user_id"])

    from backend.adaptive import product

    @router.post("/adaptive/build")
    def builder(payload: BuilderRequest, user=Depends(owner)):
        auth.throttle("adaptive-builder:" + user["user_id"], 10)
        return product.build(service, payload)

    @router.get("/adaptive/compare")
    def compare(first: str, second: str, user=Depends(owner)):
        return product.compare(service, first, second, user["user_id"])

    @router.get("/public/catalog")
    def unified_catalog():
        return product.catalog(service)

    @router.get("/public/creators/{uid}")
    def creator(uid: str):
        return product.creator(service, uid)

    @router.get("/public/bundles/{bid}/intelligence")
    def intelligence(bid: str):
        return product.intelligence(service, bid)

    from backend.adaptive.payments import Checkout, Confirm, Price, SignedTransaction

    @router.get("/public/bundles/{bid}/price")
    def price(bid: str):
        return service.payments.pricing(bid)

    @router.put("/adaptive/bundles/{bid}/price")
    def set_price(bid: str, payload: Price, user=Depends(owner)):
        return service.payments.set_price(bid, user["user_id"], payload)

    @router.post("/adaptive/bundles/{bid}/checkout", status_code=201)
    async def checkout(bid: str, payload: Checkout, user=Depends(owner)):
        auth.throttle("checkout:" + user["user_id"], 20)
        return await service.payments.checkout(bid, user["user_id"], payload)

    @router.get("/adaptive/invoices/{iid}")
    def invoice(iid: str, user=Depends(owner)):
        return service.payments.invoice(iid, user["user_id"])

    @router.post("/adaptive/invoices/{iid}/prepare")
    async def prepare(iid: str, user=Depends(owner)):
        return await service.payments.prepare(iid, user["user_id"])

    @router.post("/adaptive/invoices/{iid}/submit")
    async def submit(iid: str, payload: SignedTransaction, user=Depends(owner)):
        return await service.payments.submit(iid, user["user_id"], payload.transaction)

    @router.post("/adaptive/invoices/{iid}/confirm")
    async def confirm(iid: str, payload: Confirm, user=Depends(owner)):
        return await service.payments.confirm(iid, user["user_id"], payload.signature)

    from backend.adaptive.dex import POOL, TOKEN, SwapRequest

    @router.get("/adaptive/dex")
    def dex_info(user=Depends(owner)):
        return {
            "enabled": service.s.settings.adaptive_devnet_dex_enabled,
            "network": "solana-devnet",
            "pool": POOL,
            "test_token": TOKEN,
            "max_test_sol": 0.001,
        }

    @router.post("/adaptive/dex/quotes", status_code=201)
    async def quote_swap(payload: SwapRequest, user=Depends(owner)):
        auth.throttle("dex:" + user["user_id"], 20)
        return await service.dex.quote(user["user_id"], payload)

    @router.get("/adaptive/dex/{qid}")
    def get_swap(qid: str, user=Depends(owner)):
        return service.dex.get(qid, user["user_id"])

    @router.post("/adaptive/dex/{qid}/submit")
    async def submit_swap(qid: str, payload: SignedTransaction, user=Depends(owner)):
        return await service.dex.submit(qid, user["user_id"], payload.transaction)

    @router.post("/adaptive/dex/{qid}/confirm")
    async def confirm_swap(qid: str, payload: Confirm, user=Depends(owner)):
        return await service.dex.confirm(qid, user["user_id"], payload.signature)

    return router
