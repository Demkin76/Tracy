import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.adaptive.engine import experiment, initial_state, new_account, step
from backend.adaptive.models import Blueprint
from backend.adaptive.pine import EXAMPLE
from backend.blockchain.solana import MEMO_PROGRAM, inspect_memo
from backend.crypto.hashing import digest
from tests.test_platform import other_account


def create(env):
    r = env.client.post(
        "/v1/adaptive/agents",
        json={"name": "Learning BTC", "intent": "Test bounded threshold learning without real funds"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def train(env, agent):
    payload = {
        "request_id": "experiment_one",
        "expected_revision": agent["revision"],
        "training_bars": 192,
        "validation_bars": 96,
    }
    path = "/v1/adaptive/agents/" + agent["agent_id"] + "/experiments"
    r = env.client.post(path, json=payload)
    assert r.status_code == 201, r.text
    assert env.client.post(path, json=payload).json() == r.json()
    return r.json()


def test_baseline_immutable_learning_gate_and_bundle_transfer(env):
    agent = create(env)
    report = train(env, agent)
    body = report["body"]
    assert digest(body) == report["hash"]
    assert body["training_end"] == body["validation_start"]
    updated = env.client.get("/v1/adaptive/agents/" + agent["agent_id"]).json()
    assert updated["strategy_hash"] == agent["strategy_hash"]
    assert updated["revision"] == 2 and updated["state"]["active_arm"] == 0
    assert (
        sum(a["closed_trades"] for a in updated["state"]["arms"])
        == body["training"]["metrics"]["closed_trade_count"]
    )
    response = env.client.post(
        "/v1/adaptive/agents/" + agent["agent_id"] + "/activate",
        json={"expected_revision": 2, "report_hash": report["hash"]},
    )
    assert response.status_code == (200 if body["gate"]["passed"] else 409)
    revision = 3 if body["gate"]["passed"] else 2
    bundle = env.client.post(
        "/v1/adaptive/agents/" + agent["agent_id"] + f"/bundles?revision={revision}"
    ).json()
    bid = bundle["bundle_id"]
    assert env.client.get("/v1/public/bundles/" + bid).status_code == 404
    assert (
        env.client.put("/v1/adaptive/bundles/" + bid + "/publication", json={"listed": True}).status_code
        == 200
    )
    assert env.client.get("/v1/public/bundles/" + bid).status_code == 200
    other = TestClient(env.app)
    other_account(other)
    cloned = other.post(
        "/v1/adaptive/bundles/" + bid + "/clone", json={"name": "My learned instance", "mode": "bundle"}
    )
    assert cloned.status_code == 201, cloned.text
    clone = cloned.json()
    assert clone["runs"] == [] and clone["state"]["personal_closed_trades"] == 0
    assert clone["strategy_hash"] == agent["strategy_hash"]
    assert clone["state"]["arms"] == bundle["envelope"]["body"]["agent_apr"]["arms"]
    assert clone["state"]["observed_until"] == updated["state"]["observed_until"]
    assert other.get("/v1/adaptive/agents/" + agent["agent_id"]).status_code == 404
    assert (
        other.put("/v1/adaptive/bundles/" + bid + "/publication", json={"listed": False}).status_code == 404
    )
    fresh = env.client.post(
        "/v1/adaptive/bundles/" + bid + "/clone", json={"name": "Rules only", "mode": "strategy"}
    ).json()
    assert all(a["closed_trades"] == 0 for a in fresh["state"]["arms"])
    assert env.client.post("/v1/adaptive/bundles/" + bid + "/anchor").status_code == 409
    with env.db.connect(write=True) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE adaptive_states SET body='{}'")
    other.close()


def test_no_repeated_learning_on_seen_data_or_stale_revision(env):
    agent = create(env)
    train(env, agent)
    path = "/v1/adaptive/agents/" + agent["agent_id"] + "/experiments"
    p = {"request_id": "experiment_two", "expected_revision": 2, "training_bars": 192, "validation_bars": 96}
    assert env.client.post(path, json=p).status_code == 409
    p["expected_revision"] = 1
    assert env.client.post(path, json=p).status_code == 409


def test_validation_cannot_change_training_posterior_or_candidate(env):
    bp = Blueprint(name="Causal", intent="Causal training and validation separation").model_dump()
    snapshot = env.app.state.strategies.market_data.window("BTC/USDC", "1h", 288)
    original = experiment(bp, snapshot, initial_state(bp), 192)
    changed = deepcopy(snapshot)
    for bar in changed["bars"][192:]:
        for key in ("price", "open", "high", "low", "close"):
            bar[key] *= 0.5
    altered = experiment(bp, changed, initial_state(bp), 192)
    assert original["training"] == altered["training"]
    assert original["candidate_arm"] == altered["candidate_arm"]
    assert original["next_state"]["arms"] == altered["next_state"]["arms"]


def test_pine_subset_rejects_unknown_statements_and_source_mismatch(env):
    r = env.client.post("/v1/adaptive/import-pine", json={"source": EXAMPLE})
    assert r.status_code == 200 and r.json()["program"]["kind"] == "sma_cross"
    for invalid in (
        EXAMPLE + '\nstrategy.entry("Short", strategy.short)',
        EXAMPLE.replace("ta.sma", "request.security"),
        EXAMPLE.replace("    strategy.close", "strategy.close"),
    ):
        assert env.client.post("/v1/adaptive/import-pine", json={"source": invalid}).status_code == 422
    assert (
        env.client.post(
            "/v1/adaptive/agents",
            json={
                "name": "Mismatch",
                "intent": "Should fail closed for source mismatch",
                "pine_source": EXAMPLE,
            },
        ).status_code
        == 422
    )


def test_reduce_only_exit_bypasses_entry_notional_limits():
    bp = Blueprint(
        name="Risk exit", intent="Close existing inventory even after a large price rise"
    ).model_dump()
    account = new_account()
    account["fills"] = [
        {
            "trade_id": "initial",
            "side": "BUY",
            "quantity": 1,
            "executed_price": 100,
            "requested_price": 100,
            "fee": 0.1,
            "timestamp": 0,
            "market_context": {"price": 100},
        }
    ]
    bar = {"price": 300, "timestamp": 3600, "close_timestamp": 7200}
    step(bp, account, initial_state(bp), [], bar, 1, 0, force_exit=True)
    assert account["fills"][-1]["side"] == "SELL"
    assert account["fills"][-1]["quantity"] == 1


def test_forward_stop_closes_and_signed_chain_detects_tamper(env, monkeypatch):
    agent = create(env)
    train(env, agent)
    forward = env.app.state.adaptive_forward
    quote = {
        "price": 100,
        "bid": 99.9,
        "ask": 100.1,
        "bid_qty": 10000,
        "ask_qty": 10000,
        "timestamp": 2000000000,
    }
    monkeypatch.setattr(forward, "quote", lambda market: deepcopy(quote))
    review = env.app.state.adaptive.get(agent["agent_id"], env.user["user_id"])["review_report"]
    assert (
        env.client.post(
            f"/v1/adaptive/agents/{agent['agent_id']}/review",
            json={
                "expected_revision": 2,
                "report_hash": review["hash"],
                "policy_mode": "frozen",
                "acknowledged": True,
            },
        ).status_code
        == 200
    )
    started = forward.start(agent["agent_id"], env.user["user_id"], 2)
    fid = started["forward_id"]
    assert started["proof_valid"] and started["agent_metrics"]["trade_count"] == 0
    assert (
        env.client.post(
            "/v1/adaptive/agents/" + agent["agent_id"] + "/experiments",
            json={"request_id": "while_running", "expected_revision": 2},
        ).status_code
        == 409
    )
    forward.stop(fid, env.user["user_id"])
    completed = forward.advance(fid, env.user["user_id"])
    assert completed["status"] == "COMPLETED" and completed["proof_valid"]
    assert forward.advance(fid, env.user["user_id"])["events"] == completed["events"]
    with env.db.connect(write=True) as conn:
        conn.execute("UPDATE adaptive_forward SET body='{}' WHERE forward_id=?", (fid,))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        forward.get(fid, env.user["user_id"])
    assert exc.value.status_code == 409


def test_memo_requires_exact_hash_signer_and_instruction():
    hashed = "a" * 64
    tx = {
        "slot": 123,
        "meta": {"err": None},
        "transaction": {
            "signatures": ["sig"],
            "message": {
                "accountKeys": [{"pubkey": "wallet", "signer": True}],
                "instructions": [{"programId": MEMO_PROGRAM, "parsed": "tracy-bundle:" + hashed}],
            },
        },
    }
    assert inspect_memo(tx, "sig", "wallet", hashed)["valid"]
    assert not inspect_memo(tx, "sig", "wallet", "b" * 64)["valid"]
    tx["transaction"]["message"]["instructions"].append({"programId": "other"})
    assert not inspect_memo(tx, "sig", "wallet", hashed)["valid"]


def test_forward_new_candle_executes_once_then_closes_on_stop(env, monkeypatch):
    import backend.adaptive.forward as module

    agent = create(env)
    train(env, agent)
    forward = env.app.state.adaptive_forward
    snapshot = env.app.state.strategies.market_data.window("BTC/USDC", "1h", 21)
    now = snapshot["period_end"] + 5
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: now))
    monkeypatch.setattr(forward.a.s.market_data, "window", lambda *args, **kw: deepcopy(snapshot))
    quote = {"price": 110, "bid": 109.9, "ask": 110.1, "bid_qty": 1000, "ask_qty": 1000, "timestamp": now}
    monkeypatch.setattr(forward, "quote", lambda market: deepcopy(quote))
    review = env.app.state.adaptive.get(agent["agent_id"], env.user["user_id"])["review_report"]
    assert (
        env.client.post(
            f"/v1/adaptive/agents/{agent['agent_id']}/review",
            json={
                "expected_revision": 2,
                "report_hash": review["hash"],
                "policy_mode": "frozen",
                "acknowledged": True,
            },
        ).status_code
        == 200
    )
    started = forward.start(agent["agent_id"], env.user["user_id"], 2)
    fid = started["forward_id"]
    snapshot["period_end"] += 3600
    for i, bar in enumerate(snapshot["bars"]):
        bar.update(price=100 + i, close=100 + i)
    snapshot["bars"][-1]["close_timestamp"] = snapshot["period_end"]
    now += 3600
    quote["timestamp"] = now
    advanced = forward.advance(fid, env.user["user_id"])
    assert advanced["agent_metrics"]["trade_count"] == 1
    assert advanced["baseline_metrics"]["trade_count"] == 1
    assert advanced["agent_metrics"]["position_value"] > 0
    assert advanced["agent"]["fills"][0]["executed_price"] > quote["ask"]
    assert forward.advance(fid, env.user["user_id"])["events"] == advanced["events"]
    assert sum(a["closed_trades"] for a in advanced["state"]["arms"]) == sum(
        a["closed_trades"] for a in started["state"]["arms"]
    )
    forward.stop(fid, env.user["user_id"])
    now += 10
    quote["timestamp"] = now
    closed = forward.advance(fid, env.user["user_id"])
    assert closed["status"] == "COMPLETED"
    assert closed["agent_metrics"]["position_value"] == 0
    assert closed["agent_metrics"]["closed_trade_count"] == 1
    assert closed["baseline_metrics"] == closed["agent_metrics"]
    assert (
        sum(a["closed_trades"] for a in closed["state"]["arms"])
        == sum(a["closed_trades"] for a in started["state"]["arms"]) + 1
    )
    bundle = env.app.state.adaptive.bundle(agent["agent_id"], env.user["user_id"], 3)
    assert (
        bundle["envelope"]["body"]["forward_evidence"][0]["state"]["agent"]["fills"]
        == closed["agent"]["fills"]
    )


def test_forward_missing_quote_does_not_fabricate_completion(env, monkeypatch):
    from fastapi import HTTPException

    agent = create(env)
    train(env, agent)
    forward = env.app.state.adaptive_forward
    quote = {
        "price": 100,
        "bid": 99.9,
        "ask": 100.1,
        "bid_qty": 1000,
        "ask_qty": 1000,
        "timestamp": 2000000000,
    }
    monkeypatch.setattr(forward, "quote", lambda market: deepcopy(quote))
    review = env.app.state.adaptive.get(agent["agent_id"], env.user["user_id"])["review_report"]
    assert (
        env.client.post(
            f"/v1/adaptive/agents/{agent['agent_id']}/review",
            json={
                "expected_revision": 2,
                "report_hash": review["hash"],
                "policy_mode": "frozen",
                "acknowledged": True,
            },
        ).status_code
        == 200
    )
    started = forward.start(agent["agent_id"], env.user["user_id"], 2)
    fid = started["forward_id"]
    forward.stop(fid, env.user["user_id"])

    def outage(market):
        raise HTTPException(503, "Feed unavailable")

    monkeypatch.setattr(forward, "quote", outage)
    with pytest.raises(HTTPException):
        forward.advance(fid, env.user["user_id"])
    assert forward.get(fid, env.user["user_id"])["status"] == "STOPPING"


def test_copilot_private_learning_context_is_owner_scoped(env):
    # Exercise through the public HTTP interface, which authenticates context.
    agent = create(env)
    path = "/lab/" + agent["agent_id"]
    result = env.client.post(
        "/v1/copilot/message", json={"message": "Explain this learning state", "page": path}
    )
    assert result.status_code == 200, result.text
    assert result.json()["context_used"]
    anonymous = TestClient(env.app)
    public = anonymous.post(
        "/v1/copilot/message", json={"message": "Explain this learning state", "page": path}
    )
    assert public.status_code in (200, 401)
    if public.status_code == 200:
        assert not public.json()["context_used"]
    anonymous.close()
