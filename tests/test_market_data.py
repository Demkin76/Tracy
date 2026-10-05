import copy
import sqlite3

import pytest
from fastapi import HTTPException

from backend.config import Settings
from backend.market_data.provider import MarketData
from tests.test_agent_plans import make_plan


def raw_candles(start=1756684800, count=3):
    return [
        [
            (start + i * 3600) * 1000,
            "100",
            "103",
            "99",
            "101",
            "10",
            (start + (i + 1) * 3600) * 1000 - 1,
            "1010",
            10,
        ]
        for i in range(count)
    ]


@pytest.mark.parametrize("change", ["gap", "duplicate", "nan", "ohlc", "missing", "unfinished"])
def test_provider_rejects_corrupt_candles(change):
    raw = raw_candles()
    if change == "gap":
        raw[1][0] += 3600000
    elif change == "duplicate":
        raw[1] = copy.deepcopy(raw[0])
    elif change == "nan":
        raw[1][4] = "NaN"
    elif change == "ohlc":
        raw[1][2] = "98"
    elif change == "missing":
        raw.pop()
    else:
        raw[-1][6] -= 1
    with pytest.raises(HTTPException) as failure:
        MarketData.normalize(raw, 1756684800, 3, 3600)
    assert failure.value.status_code == 502


def test_snapshot_caching_and_immutability(env, monkeypatch):
    provider = env.app.state.strategies.market_data
    original, calls = provider._fetch, []

    def record(params):
        calls.append(params)
        return original(params)

    monkeypatch.setattr(provider, "_fetch", record)
    a = provider.window("SOL/USDC", "1h", 96, 1756684800)
    b = provider.window("SOL/USDC", "1h", 96, 1756684800)
    assert a == b and len(calls) == 1
    assert a["provider"] == "Binance Spot" and not a["synthetic"]
    assert all(not row["synthetic"] for row in a["bars"])
    with env.db.connect(write=True) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE market_snapshots SET body='{}'")


def test_provider_failure_never_generates_prices_or_plan(env, monkeypatch):
    def unavailable(params):
        raise HTTPException(503, "Market data unavailable")

    monkeypatch.setattr(env.app.state.strategies.market_data, "_fetch", unavailable)
    response = env.client.post(
        "/v1/agent-plans", json={"name": "No fallback", "goal": "Use actual recorded market prices"}
    )
    assert response.status_code == 503
    with env.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM agent_plans").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM market_snapshots").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM agents").fetchone()[0] == 1


def test_history_and_replay_are_separate_and_pinned(env):
    plan = make_plan(env)
    report = plan["report"]
    simulations = report["simulations"]
    assert all(s["source"] == "historical_exchange_backtest" for s in simulations)
    assert simulations[-1]["market_data"]["period_end"] == report["replay_market_data"]["period_start"]
    provider = env.app.state.strategies.market_data
    holdout = provider.get(report["replay_snapshot_id"])
    assert len(holdout["bars"]) == 96
    assert holdout["snapshot_id"] not in [s["market_data"]["snapshot_id"] for s in simulations]
    assert (
        simulations[0]["market_context"] == provider.get(simulations[0]["market_data"]["snapshot_id"])["bars"]
    )


def test_future_and_unaligned_periods_rejected(env):
    provider = env.app.state.strategies.market_data
    for start in (4000000000, 1756684801):
        with pytest.raises(HTTPException) as failure:
            provider.window("SOL/USDC", "1h", 96, start)
        assert failure.value.status_code == 422


def test_production_configuration_fails_closed(env):
    config = env.settings.model_dump()
    config["environment"] = "production"
    with pytest.raises(ValueError):
        Settings(_env_file=None, **config)
    config.update(
        cookie_secure=True,
        devnet_enabled=False,
        allowed_hosts=["tracy.example.com", "127.0.0.1"],
        cors_origins=["https://tracy.example.com"],
    )
    assert Settings(_env_file=None, **config).environment == "production"


def test_host_and_streamed_body_limits(env):
    assert env.client.get("/healthz", headers={"host": "evil.invalid"}).status_code == 400
    request = env.client.build_request(
        "POST", "http://testserver/v1/auth/login", content=iter([b"x" * 200000, b"y" * 100000])
    )
    assert "content-length" not in request.headers
    assert env.client.send(request).status_code == 413


def test_signup_can_be_closed(env):
    env.settings.signup_enabled = False
    response = env.client.post(
        "/v1/auth/signup",
        json={"email": "closed@example.test", "password": "long-enough-password", "name": "Closed"},
    )
    assert response.status_code == 403
