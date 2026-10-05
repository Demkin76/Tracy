import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.control.models import Decision
from backend.strategies.models import (
    Advance,
    Clone,
    Deploy,
    Lifecycle,
    NewVersion,
    Publish,
    StrategyCreate,
    TestRequest,
)
from backend.trading.models import QuoteRequest


def strategy_router(service, owner):
    router = APIRouter(prefix="/v1")

    @router.get("/strategy-tests")
    def all_tests(user=Depends(owner)):
        with service.db.connect() as conn:
            rows = conn.execute(
                "SELECT t.body,s.name FROM strategy_tests t JOIN strategies s ON s.strategy_id=t.strategy_id WHERE s.owner_id=? ORDER BY t.started_at DESC,t.rowid DESC LIMIT 100",
                (user["user_id"],),
            ).fetchall()
        return {
            "items": [
                {
                    **{
                        k: v
                        for k, v in json.loads(r[0]).items()
                        if k
                        in (
                            "test_id",
                            "strategy_id",
                            "strategy_version",
                            "started_at",
                            "dataset",
                            "metrics",
                            "market_data",
                        )
                    },
                    "strategy_name": r[1],
                }
                for r in rows
            ]
        }

    @router.get("/trading/queue")
    def queue(user=Depends(owner)):
        with service.db.connect() as conn:
            rows = conn.execute(
                "SELECT i.intent_id,i.reason,s.name AS strategy_name FROM trading_intents i JOIN trading_deployments d ON d.deployment_id=i.deployment_id JOIN strategies s ON s.strategy_id=d.strategy_id WHERE s.owner_id=? AND i.status='AWAITING_APPROVAL' ORDER BY i.created_at LIMIT 100",
                (user["user_id"],),
            ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @router.post("/strategies", status_code=201)
    def create(payload: StrategyCreate, user=Depends(owner)):
        return service.create(payload, user["user_id"])

    @router.get("/strategies")
    def listing(user=Depends(owner)):
        return service.list(user["user_id"])

    @router.get("/strategies/{sid}")
    def detail(sid: str, version: int | None = Query(None, ge=1), user=Depends(owner)):
        return service.detail(sid, user["user_id"], version)

    @router.get("/strategies/{sid}/market-data")
    def source_data(
        sid: str,
        kind: str = Query("backtest", pattern="^(backtest|replay)$"),
        version: int | None = Query(None, ge=1),
        user=Depends(owner),
    ):
        item = service.detail(sid, user["user_id"], version)
        source = item["performance"]["market_data" if kind == "backtest" else "replay_market_data"]
        if not source:
            raise HTTPException(404, "No recorded data for this version")
        return service.market_data.get(source["snapshot_id"])

    @router.get("/public/trading/strategies/{sid}/market-data")
    def public_source_data(
        sid: str,
        kind: str = Query("backtest", pattern="^(backtest|replay)$"),
        version: int | None = Query(None, ge=1),
    ):
        item = service.detail(sid, version=version, public=True)
        source = item["performance"]["market_data" if kind == "backtest" else "replay_market_data"]
        if not source:
            raise HTTPException(404, "No recorded data for this version")
        return service.market_data.get(source["snapshot_id"])

    @router.post("/strategies/{sid}/versions", status_code=201)
    def version(sid: str, payload: NewVersion, user=Depends(owner)):
        return service.new_version(sid, user["user_id"], payload)

    @router.post("/strategies/{sid}/tests", status_code=201)
    def test(sid: str, payload: TestRequest, user=Depends(owner)):
        return service.test(sid, user["user_id"], payload)

    @router.get("/strategies/{sid}/tests")
    def tests(sid: str, version: int | None = Query(None, ge=1), user=Depends(owner)):
        return service.tests(sid, user["user_id"], version)

    @router.post("/strategies/{sid}/deploy", status_code=201)
    def deploy(sid: str, payload: Deploy, user=Depends(owner)):
        return service.deploy(sid, user["user_id"], payload)

    @router.post("/strategies/{sid}/status")
    def status(sid: str, payload: Lifecycle, user=Depends(owner)):
        return service.lifecycle(sid, user["user_id"], payload)

    @router.post("/strategies/{sid}/advance")
    def advance(sid: str, payload: Advance, user=Depends(owner)):
        return service.trading.advance(sid, user["user_id"], payload)

    @router.post("/strategies/{sid}/probe")
    def probe(sid: str, user=Depends(owner)):
        return service.trading.probe(sid, user["user_id"])

    @router.get("/strategies/{sid}/performance")
    def performance(sid: str, version: int | None = Query(None, ge=1), user=Depends(owner)):
        return service.detail(sid, user["user_id"], version)["performance"]

    @router.get("/strategies/{sid}/health")
    def health(sid: str, version: int | None = Query(None, ge=1), user=Depends(owner)):
        return service.detail(sid, user["user_id"], version)["health"]

    @router.get("/strategies/{sid}/trades")
    def trades(
        sid: str,
        version: int | None = Query(None, ge=1),
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user=Depends(owner),
    ):
        return service.trades(sid, user["user_id"], version, limit=limit, offset=offset)

    @router.get("/strategies/{sid}/intents")
    def intents(sid: str, user=Depends(owner)):
        return service.intents(sid, user["user_id"])

    @router.put("/strategies/{sid}/publication")
    def publish(sid: str, payload: Publish, user=Depends(owner)):
        return service.publish(sid, user["user_id"], payload.listed)

    @router.post("/trading/quote")
    def quote(payload: QuoteRequest):
        return service.trading.quote(payload)

    @router.get("/trading/intents/{iid}")
    def intent(iid: str, user=Depends(owner)):
        return service.trading.get(iid, user["user_id"])

    @router.post("/trading/intents/{iid}/decision")
    def decision(iid: str, payload: Decision, request: Request, user=Depends(owner)):
        if request.headers.get("authorization") or not user.get("csrf_token"):
            raise HTTPException(403, "Human approval requires browser session and CSRF token")
        return service.trading.decide(iid, user["user_id"], payload)

    @router.get("/trades/{tid}/proof")
    def proof(tid: str, user=Depends(owner)):
        return service.trading.proof(tid, user["user_id"])

    @router.get("/degradation/alerts")
    def alerts(user=Depends(owner)):
        return service.alerts(user["user_id"])

    @router.post("/degradation/alerts/{aid}/acknowledge")
    def ack(aid: str, user=Depends(owner)):
        return service.acknowledge(aid, user["user_id"])

    @router.get("/public/trading/strategies")
    def exchange(q: str = Query("", max_length=100)):
        return service.exchange(q)

    @router.get("/public/trading/strategies/{sid}")
    def public_strategy(sid: str, version: int | None = Query(None, ge=1)):
        return service.detail(sid, version=version, public=True)

    @router.get("/public/trading/strategies/{sid}/trades")
    def public_trades(
        sid: str,
        version: int | None = Query(None, ge=1),
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        return service.trades(sid, None, version, public=True, limit=limit, offset=offset)

    @router.get("/public/trading/agents/{aid}")
    def public_agent(aid: str):
        return service.public_agent(aid)

    @router.get("/public/trading/trades/{tid}/proof")
    def public_proof(tid: str):
        return service.trading.proof(tid, public=True)

    @router.get("/public/trading/compare")
    def compare(ids: str = Query(..., max_length=500)):
        selection = ids.split(",")
        if not 2 <= len(selection) <= 4 or len(set(selection)) != len(selection):
            raise HTTPException(422, "Choose two to four distinct strategies")
        return {
            "items": [service.detail(sid, public=True) for sid in selection],
            "note": "Compare the same evidence mode and time horizon. Returns are not risk-adjusted rankings.",
        }

    @router.post("/public/trading/strategies/{sid}/clone", status_code=201)
    def clone(sid: str, payload: Clone, user=Depends(owner)):
        from backend.strategies.models import VersionInput

        original = service.get(sid, public=True)
        config = {k: original[k] for k in VersionInput.model_fields}
        config["change_note"] = "Copied published strategy " + sid + " v" + str(original["version"])
        return service.create(
            StrategyCreate(
                **config, agent_id=payload.agent_id, name=payload.name, description=original["description"]
            ),
            user["user_id"],
        )

    return router
