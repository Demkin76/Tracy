import copy
import sqlite3
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.crypto.hashing import canonical_bytes
from backend.crypto.signatures import private_key, sign
from backend.performance.metrics import calculate
from tests.test_platform import other_account


def create(env, **extra):
    payload = {"agent_id": "agent_test", "name": "SOL Momentum", **extra}
    r = env.client.post("/v1/strategies", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def run_test(env, **extra):
    s = create(env, **extra)
    r = env.client.post("/v1/strategies/" + s["strategy_id"] + "/tests", json={})
    assert r.status_code == 201, r.text
    return s, r.json()


def deploy(env, **extra):
    s, t = run_test(env, **extra)
    r = env.client.post("/v1/strategies/" + s["strategy_id"] + "/deploy", json={"expected_version": 1})
    assert r.status_code == 201, r.text
    return r.json(), t


def order(env, s, **overrides):
    dep = s["performance"]["deployment"]
    body = {
        "schema_version": "tracy.intent/2",
        "request_id": "r_" + uuid4().hex,
        "agent_id": "agent_test",
        "task_id": dep["deployment_id"],
        "action": "trading.order",
        "resource_id": s["strategy_id"],
        "params": {"strategy_version": s["version"], "side": "BUY", "quantity": 1, "requested_price": 146.16},
        "reason": "Test controlled trade",
        "timestamp": int(time.time()),
    }
    body.update(overrides)
    body["signature"] = sign(private_key(env.keys["private_seed"]), canonical_bytes(body))
    r = env.client.post("/v2/intents", json=body)
    assert r.status_code == 202, r.text
    return r.json(), body


def advance(env, s, step=0, steps=48):
    r = env.client.post(
        "/v1/strategies/" + s["strategy_id"] + "/advance", json={"expected_step": step, "steps": steps}
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_complete_strategy_lifecycle_and_proof(env):
    s, t = deploy(env)
    assert t["metrics"]["trade_count"] > 0 and t["source"] == "deterministic_synthetic_runner"
    assert (
        env.client.post(
            "/v1/strategies/" + s["strategy_id"] + "/deploy", json={"expected_version": 1}
        ).status_code
        == 409
    )
    a = advance(env, s)
    detail = env.client.get("/v1/strategies/" + s["strategy_id"]).json()
    assert detail["performance"]["verified_trades"] > 0
    assert detail["performance"]["performance_gap"] == pytest.approx(
        detail["performance"]["live_return"] - detail["performance"]["backtest_return"]
    )
    trades = env.client.get("/v1/strategies/" + s["strategy_id"] + "/trades").json()["items"]
    proof = env.client.get("/v1/trades/" + trades[0]["trade_id"] + "/proof").json()
    assert proof["checks"]["valid"] and not proof["checks"]["on_chain"]
    assert proof["receipt"]["trade"]["tx_signature"] is None
    assert proof["receipt"]["strategy_version"] == 1
    assert (
        env.client.post(
            "/v1/strategies/" + s["strategy_id"] + "/advance", json={"expected_step": 0}
        ).status_code
        == 409
    )
    assert a["step"] > 0


def test_backtest_is_reproducible_and_metrics_recomputed(env):
    s, t = run_test(env)
    repeated = env.client.post("/v1/strategies/" + s["strategy_id"] + "/tests", json={}).json()
    assert t["metrics"] == repeated["metrics"]
    assert t["metrics"] == calculate(t["trades"], t["starting_capital"], t["market_context"])
    assert len(t["market_context"]) == 96


def test_strategy_versions_are_immutable_and_separate(env):
    s, t = deploy(env)
    advance(env, s, steps=12)
    env.client.post(
        "/v1/strategies/" + s["strategy_id"] + "/status", json={"status": "PAUSED", "expected_version": 1}
    ).raise_for_status()
    v = {
        k: s[k]
        for k in ("market", "symbols", "timeframe", "starting_capital", "strategy_config", "guardrails")
    }
    v["strategy_config"]["lookback"] = 5
    r = env.client.post(
        "/v1/strategies/" + s["strategy_id"] + "/versions",
        json={**v, "expected_version": 1, "change_note": "Longer lookback"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 2 and r.json()["status"] == "DRAFT"
    old = env.client.get("/v1/strategies/" + s["strategy_id"] + "?version=1").json()
    assert old["strategy_config"]["lookback"] == 3 and old["performance"]["verified_trades"] > 0
    new = env.client.get("/v1/strategies/" + s["strategy_id"]).json()
    assert new["performance"]["verified_trades"] == 0 and new["performance"]["backtest"] is None
    assert (
        env.client.post(
            "/v1/strategies/" + s["strategy_id"] + "/deploy", json={"expected_version": 2}
        ).status_code
        == 409
    )
    with env.db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE strategy_versions SET body='{}'")


def test_trade_signature_idempotency_guardrails_and_readback(env):
    s, _ = deploy(env)
    item, body = order(env, s)
    assert item["status"] == "VERIFIED", item
    same = env.client.post("/v2/intents", json=body)
    assert same.json()["intent_id"] == item["intent_id"]
    invalid = copy.deepcopy(body)
    invalid["params"]["quantity"] = 2
    assert env.client.post("/v2/intents", json=invalid).status_code == 401
    invalid["signature"] = sign(
        private_key(env.keys["private_seed"]),
        canonical_bytes({k: v for k, v in invalid.items() if k != "signature"}),
    )
    assert env.client.post("/v2/intents", json=invalid).status_code == 409
    danger, _ = order(
        env, s, params={"strategy_version": 1, "side": "BUY", "quantity": 100, "requested_price": 146.16}
    )
    assert danger["status"] == "REJECTED" and danger["reason"] == "max_trade_size"
    assert env.client.get("/v1/degradation/alerts").json()["items"]


def test_trading_requires_browser_approval_and_rechecks_pause(env):
    s, _ = deploy(env, guardrails={"human_approval_above": 1})
    item, _ = order(env, s)
    assert item["status"] == "AWAITING_APPROVAL"
    body = {"decision": "approve", "intent_hash": item["intent_hash"], "policy_version": 1}
    assert (
        env.client.post("/v1/trading/intents/" + item["intent_id"] + "/decision", json=body).status_code
        == 403
    )
    env.client.post(
        "/v1/strategies/" + s["strategy_id"] + "/status", json={"status": "PAUSED", "expected_version": 1}
    )
    from backend.control.models import Decision

    result = env.app.state.strategies.trading.decide(item["intent_id"], env.user["user_id"], Decision(**body))
    assert result["status"] == "REJECTED" and result["reason"] == "strategy_not_live"


def test_strategy_tenant_isolation_and_private_proofs(env):
    s, _ = deploy(env)
    item, _ = order(env, s)
    tid = item["receipt"]["trade_id"]
    with TestClient(env.app) as other:
        other_account(other)
        assert other.get("/v1/strategies/" + s["strategy_id"]).status_code == 404
        assert other.get("/v1/trades/" + tid + "/proof").status_code == 404
        assert other.get("/v1/trading/intents/" + item["intent_id"]).status_code == 404
        assert other.get("/v1/public/trading/strategies/" + s["strategy_id"]).status_code == 404
        assert other.get("/v1/public/trading/trades/" + tid + "/proof").status_code == 404


def test_publish_compare_and_unpublish(env):
    s, _ = deploy(env)
    item, _ = order(env, s)
    env.client.put(
        "/v1/strategies/" + s["strategy_id"] + "/publication", json={"listed": True}
    ).raise_for_status()
    # Publishing a trading strategy must not disclose unrelated v1 action history.
    assert not env.client.get("/v1/agents/agent_test").json()["listed"]
    assert env.client.get("/v1/public/agents/agent_test").status_code == 404
    assert env.client.get("/v1/public/trading/agents/agent_test").status_code == 200
    second = create(env, name="Another strategy")
    env.client.put(
        "/v1/strategies/" + second["strategy_id"] + "/publication", json={"listed": True}
    ).raise_for_status()
    assert (
        len(
            env.client.get(
                "/v1/public/trading/compare", params={"ids": s["strategy_id"] + "," + second["strategy_id"]}
            ).json()["items"]
        )
        == 2
    )
    assert (
        env.client.get("/v1/public/trading/trades/" + item["receipt"]["trade_id"] + "/proof").status_code
        == 200
    )
    env.client.put(
        "/v1/strategies/" + s["strategy_id"] + "/publication", json={"listed": False}
    ).raise_for_status()
    assert (
        env.client.get("/v1/public/trading/trades/" + item["receipt"]["trade_id"] + "/proof").status_code
        == 404
    )


def test_metrics_account_for_fees_open_positions_and_drawdown():
    fills = [
        {
            "trade_id": "buy",
            "timestamp": 1,
            "side": "BUY",
            "quantity": 2,
            "executed_price": 100,
            "requested_price": 99,
            "fee": 2,
            "market_context": {"price": 100},
        },
        {
            "trade_id": "sell",
            "timestamp": 3,
            "side": "SELL",
            "quantity": 1,
            "executed_price": 120,
            "requested_price": 121,
            "fee": 1,
            "market_context": {"price": 120},
        },
    ]
    m = calculate(fills, 1000, [{"timestamp": 2, "price": 80}, {"timestamp": 4, "price": 110}])
    assert m["realized_pnl"] == 18 and m["unrealized_pnl"] == 9
    assert m["pnl"] == 27 and m["return_pct"] == 2.7
    assert m["fees"] == 3 and m["slippage"] == 3 and m["win_rate"] == 100
    assert m["max_drawdown"] == 4.2
    assert m["profit_factor"] is None


def test_invalid_configuration_fails_closed(env):
    assert (
        env.client.post(
            "/v1/strategies",
            json={"agent_id": "agent_test", "name": "bad", "strategy_config": {"runner": "exec"}},
        ).status_code
        == 422
    )
    assert (
        env.client.post(
            "/v1/strategies", json={"agent_id": "agent_test", "name": "bad", "market": "BTC/USDC"}
        ).status_code
        == 422
    )
    assert (
        env.client.post(
            "/v1/strategies", json={"agent_id": "agent_test", "name": "bad", "starting_capital": True}
        ).status_code
        == 422
    )
