import copy

import pytest

from backend.control.models import Decision
from backend.degradation.rules import assess
from backend.trading.verify import valid_receipt, verify_chain
from tests.test_strategies import advance, deploy, order


def test_pending_orders_reserve_cash_and_position_limits(env):
    s, _ = deploy(env, guardrails={"human_approval_above": 1, "max_position_size": 200})
    first, _ = order(env, s)
    second, _ = order(env, s)
    assert first["status"] == "AWAITING_APPROVAL"
    assert second["status"] == "REJECTED" and second["reason"] == "max_position_size"


def test_human_approval_binds_hash_and_version_then_executes_once(env):
    s, _ = deploy(env, guardrails={"human_approval_above": 1})
    item, _ = order(env, s)
    service = env.app.state.strategies.trading
    with pytest.raises(Exception) as error:
        service.decide(
            item["intent_id"],
            env.user["user_id"],
            Decision(decision="approve", intent_hash="f" * 64, policy_version=1),
        )
    assert error.value.status_code == 409
    payload = Decision(decision="approve", intent_hash=item["intent_hash"], policy_version=1)
    approved = service.decide(item["intent_id"], env.user["user_id"], payload)
    assert approved["status"] == "VERIFIED"
    assert valid_receipt(approved["receipt"], env.app.state.control.receipts.public_key)
    with pytest.raises(Exception) as error:
        service.decide(item["intent_id"], env.user["user_id"], payload)
    assert error.value.status_code == 409


async def test_expiry_and_stop_resume_invalidate_approval(env):
    s, _ = deploy(env, guardrails={"human_approval_above": 1})
    item, _ = order(env, s)
    with env.db.connect(write=True) as conn:
        conn.execute(
            "UPDATE trading_intents SET approval_expires_at=0 WHERE intent_id=?", (item["intent_id"],)
        )
    await env.app.state.strategies.trading.tick()
    assert (
        env.app.state.strategies.trading.get(item["intent_id"], env.user["user_id"])["status"] == "REJECTED"
    )
    item, _ = order(env, s)
    with env.db.connect(write=True) as conn:
        conn.execute("UPDATE agents SET status_version=status_version+2 WHERE agent_id='agent_test'")
    result = env.app.state.strategies.trading.decide(
        item["intent_id"],
        env.user["user_id"],
        Decision(decision="approve", intent_hash=item["intent_hash"], policy_version=1),
    )
    assert result["status"] == "REJECTED" and result["reason"] == "agent_status_changed"


def test_baseline_does_not_change_after_deploy(env):
    s, _ = deploy(env)
    sid = s["strategy_id"]
    baseline = s["performance"]["baseline_test_id"]
    env.client.post("/v1/strategies/" + sid + "/tests", json={"dataset": "historical"}).raise_for_status()
    updated = env.client.get("/v1/strategies/" + sid).json()
    assert updated["performance"]["baseline_test_id"] == baseline


def test_public_copy_has_no_inherited_profits_or_trades(env):
    s, _ = deploy(env)
    advance(env, s, steps=12)
    sid = s["strategy_id"]
    env.client.put("/v1/strategies/" + sid + "/publication", json={"listed": True}).raise_for_status()
    r = env.client.post(
        "/v1/public/trading/strategies/" + sid + "/clone",
        json={"agent_id": "agent_test", "name": "Private copy"},
    )
    assert r.status_code == 201, r.text
    copied = env.client.get("/v1/strategies/" + r.json()["strategy_id"]).json()
    assert copied["status"] == "DRAFT" and copied["version"] == 1 and not copied["listed"]
    assert copied["performance"]["live_return"] is None and copied["performance"]["verified_trades"] == 0


def test_trading_proof_detects_tampering_and_pins_trust(env):
    s, _ = deploy(env)
    item, _ = order(env, s)
    proof = item["receipt"]
    key = env.app.state.control.receipts.public_key
    assert verify_chain([proof], key)
    tampered = copy.deepcopy(proof)
    tampered["trade"]["executed_price"] += 1
    assert not valid_receipt(tampered, key)
    tampered = copy.deepcopy(proof)
    tampered["execution"]["on_chain"] = True
    assert not valid_receipt(tampered, key)
    assert not valid_receipt(proof, env.keys["public_key"])


def test_guardrail_probe_rejects_without_a_fill(env):
    s, _ = deploy(env)
    sid = s["strategy_id"]
    r = env.client.post("/v1/strategies/" + sid + "/probe")
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    assert r.json()["reason"] == "max_trade_size"
    assert not env.client.get("/v1/strategies/" + sid + "/trades").json()["items"]


def test_degradation_formula_is_transparent_and_sample_gated():
    live = {
        "closed_trade_count": 30,
        "trade_count": 60,
        "max_drawdown": 14,
        "return_pct": 6.7,
        "recent_win_rate": 42,
        "recent_closed_count": 30,
        "rolling_return": -3,
        "average_slippage_bps": 40,
    }
    backtest = {"win_rate": 64, "average_slippage_bps": 8}
    h = assess(live, backtest, {"max_drawdown": 20}, 100, -11.5)
    assert h["status"] == "DEGRADED"
    assert sum(c["weight"] for c in h["components"].values()) == pytest.approx(1)
    assert h["score"] == round(sum(c["score"] * c["weight"] for c in h["components"].values()))
    assert {"backtest_live_gap_increased", "win_rate_dropped", "slippage_increased"} <= {
        r["kind"] for r in h["reasons"]
    }
    live["closed_trade_count"] = 2
    assert assess(live, backtest, {"max_drawdown": 20}, 100, -11.5)["score"] is None


def test_critical_drawdown_pauses_deployment(env):
    s, _ = deploy(env, guardrails={"max_drawdown": 0.1, "max_daily_loss": 100})
    advance(env, s, steps=24)
    detail = env.client.get("/v1/strategies/" + s["strategy_id"]).json()
    assert detail["status"] == "PAUSED"
    assert detail["health"]["status"] == "CRITICAL"
    assert (
        env.client.post(
            "/v1/strategies/" + s["strategy_id"] + "/status", json={"status": "LIVE", "expected_version": 1}
        ).status_code
        == 409
    )


def test_trade_lookup_uses_agent_signature_without_owner_key(env):
    import json

    import httpx

    from sdk.tracy import AgentIdentity, Tracy

    s, _ = deploy(env)

    def handler(request):
        assert "authorization" not in request.headers
        r = env.client.request(request.method, request.url.path, json=json.loads(request.content))
        return httpx.Response(r.status_code, json=r.json())

    client = Tracy(
        "http://testserver",
        task_id=s["performance"]["deployment"]["deployment_id"],
        transport=httpx.MockTransport(handler),
    )
    protected = client.protect(AgentIdentity("agent_test", env.keys["private_seed"]))
    quote = protected.quote(s["strategy_id"])
    assert quote["mode"] == "paper" and quote["context"]["synthetic"] is False
    assert quote["context"]["price"] == 146.16
    item = protected.intent(
        "trading.order",
        s["strategy_id"],
        {"strategy_version": 1, "side": "BUY", "quantity": 1, "requested_price": 146.16},
        request_id="sdk-trade",
    )
    assert protected.status(item["intent_id"])["status"] == "VERIFIED"
    client.close()


def test_future_version_and_arbitrary_params_rejected(env):
    s, _ = deploy(env)
    item, _ = order(
        env, s, params={"strategy_version": 2, "side": "BUY", "quantity": 1, "requested_price": 146.16}
    )
    assert item["status"] == "REJECTED" and item["reason"] == "strategy_version_changed"


def test_market_and_position_guardrails(env):
    s, _ = deploy(env, guardrails={"allowed_markets": ["ETH/USDC"], "allowed_tokens": ["ETH", "USDC"]})
    item, _ = order(env, s)
    assert item["reason"] == "market_or_token_not_allowed"
    s, _ = deploy(env)
    item, _ = order(
        env, s, params={"strategy_version": 1, "side": "SELL", "quantity": 1, "requested_price": 146.16}
    )
    assert item["reason"] == "insufficient_position"
