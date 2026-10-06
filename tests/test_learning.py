"""Isolated deterministic fixtures; never advertised as market evidence."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.adaptive.engine import experiment, initial_state, new_account, step
from backend.adaptive.learning import attribution, decision_contract, evaluate, upgrade_state
from backend.adaptive.models import Blueprint
from tests.test_adaptive import create, train


def test_attribution_abstains_before_reward():
    base = dict(
        signal_return_pct=1,
        execution_abnormal=False,
        regime_changed=False,
        noise_band_pct=0.3,
        max_adverse_pct=-0.5,
        invalidation_pct=-1.5,
        expected_return_pct=0.5,
    )
    assert attribution(base)["decision_signal"] == 1
    for overrides, reason in [
        ({"execution_abnormal": True}, "execution_issue"),
        ({"regime_changed": True}, "regime_shift_uncertain"),
        ({"signal_return_pct": 0.1}, "inside_noise_band"),
    ]:
        result = attribution(base | overrides)
        assert result["reason"] == reason and not result["eligible_for_learning"]
    assert attribution(base | {"max_adverse_pct": -2})["decision_signal"] == -1


def seed_outcomes(env, agent, positive=True, count=3):
    a = env.app.state.adaptive
    bp, state = agent["strategy_apr"]["blueprint"], agent["state"]
    with env.db.connect(write=True) as conn:
        for i in range(count):
            did = f"{agent['agent_id']}_{i}"
            d = decision_contract(
                bp,
                state,
                1,
                {"signal_as_of": 3600},
                dict(
                    timestamp=3600, arm=0, side="BUY", requested_price=100, executed_price=100.1, quantity=1
                ),
                [],
                did,
                agent["agent_id"],
                "fixture",
            )
            price = 101 if positive else 99
            bars = [
                dict(
                    timestamp=3600 + j * 3600,
                    close_timestamp=7200 + j * 3600,
                    price=price,
                    high=max(100, price),
                    low=min(100, price),
                )
                for j in range(4)
            ]
            outcome = evaluate(d, dict(period_start=d["evaluation_start"], period_end=d["due_at"], bars=bars))
            de = a.signed(d)
            outcome["decision_hash"] = de["hash"]
            oe = a.signed(outcome)
            conn.execute(
                "INSERT INTO learning_decisions VALUES(?,?,?,?,?,?)",
                (did, agent["agent_id"], env.user["user_id"], d["due_at"], json.dumps(de), de["hash"]),
            )
            conn.execute(
                "INSERT INTO learning_outcomes VALUES(?,?,?,?,?)",
                (did, agent["agent_id"], env.user["user_id"], json.dumps(oe), oe["hash"]),
            )
        a.learning.feedback(conn, agent["agent_id"], env.user["user_id"])
    return a.get(agent["agent_id"], env.user["user_id"])


def test_two_clones_learn_only_their_own_outcomes_and_no_double_count(env):
    a = env.app.state.adaptive
    bp = Blueprint(
        name="Independent", intent="Isolated outcome feedback experiment", learning={"minimum_samples": 3}
    )
    first = a.create(bp, env.user["user_id"])
    train(env, first)
    bundle = a.bundle(first["agent_id"], env.user["user_id"], 2)
    from backend.adaptive.models import CloneBundle

    clones = [
        a.clone(bundle["bundle_id"], env.user["user_id"], CloneBundle(name=f"Clone {i}", mode="strategy"))
        for i in range(3)
    ]
    good = seed_outcomes(env, clones[0], True)
    bad = seed_outcomes(env, clones[1], False)
    same = seed_outcomes(env, clones[2], True)
    assert good["state"]["apr"][0]["probability"] > 0.5 > bad["state"]["apr"][0]["probability"]
    assert same["state"]["apr"] == good["state"]["apr"]
    assert good["strategy_hash"] == bad["strategy_hash"] == first["strategy_hash"]
    with env.db.connect(write=True) as conn:
        a.learning.feedback(conn, good["agent_id"], env.user["user_id"])
    assert a.get(good["agent_id"], env.user["user_id"])["revision"] == 2
    evolution = a.learning.evolution(bad["agent_id"], env.user["user_id"])
    assert len(evolution["changes"]) == 1 and len(evolution["outcomes"]) == 3
    # A failed rule must affect admission even when recording forward statistics.
    account = new_account()
    history = [dict(price=100 + i, close_timestamp=i * 3600) for i in range(7)]
    step(
        bp.model_dump(),
        account,
        bad["state"],
        history,
        dict(price=110, timestamp=36000),
        10,
        0,
        training=True,
    )
    assert not account["fills"]
    assert account["decisions"][-1]["reason"] == "attributed_probability_below_entry_floor"


def test_review_and_platform_switch_gate_forward(env, monkeypatch):
    agent = create(env)
    report = train(env, agent)
    a, f = env.app.state.adaptive, env.app.state.adaptive_forward
    monkeypatch.setattr(
        f,
        "quote",
        lambda _: dict(price=100, bid=99, ask=101, bid_qty=1000, ask_qty=1000, timestamp=2000000000),
    )
    with pytest.raises(HTTPException) as error:
        f.start(agent["agent_id"], env.user["user_id"], 2)
    assert error.value.status_code == 409
    path = f"/v1/adaptive/agents/{agent['agent_id']}/review"
    payload = dict(expected_revision=2, report_hash=report["hash"], policy_mode="adaptive", acknowledged=True)
    assert env.client.post(path, json=payload | {"report_hash": "0" * 64}).status_code == 409
    assert env.client.post(path, json=payload).status_code == 200
    monkeypatch.setattr(a.s.settings, "execution_enabled", False)
    with pytest.raises(HTTPException):
        f.start(agent["agent_id"], env.user["user_id"], 2)
    monkeypatch.setattr(a.s.settings, "execution_enabled", True)
    started = f.start(agent["agent_id"], env.user["user_id"], 2)
    monkeypatch.setattr(a.s.settings, "execution_enabled", False)
    with pytest.raises(HTTPException):
        f.advance(started["forward_id"], env.user["user_id"])
    assert f.get(started["forward_id"], env.user["user_id"])["agent_metrics"]["trade_count"] == 0


def test_v2_holdout_does_not_leak_into_apr(env):
    bp = Blueprint(name="Holdout", intent="Keep future observations isolated").model_dump()
    data = env.app.state.strategies.market_data.window("BTC/USDC", "1h", 288)
    prior = upgrade_state(bp, initial_state(bp))
    before = experiment(bp, data, prior, 192)
    changed = deepcopy(data)
    for bar in changed["bars"][192:]:
        for key in ("price", "open", "close", "high", "low"):
            bar[key] *= 0.5
    after = experiment(bp, changed, prior, 192)
    assert before["training"] == after["training"]
    assert before["candidate_arm"] == after["candidate_arm"]


def test_outcome_worker_waits_for_horizon_and_is_idempotent(env, monkeypatch):
    import backend.adaptive.learning as module

    a = env.app.state.adaptive
    agent = create(env)
    bp = agent["strategy_apr"]["blueprint"]
    snapshot = a.s.market_data.window(bp["market"], bp["timeframe"], 4)
    fill = {
        "timestamp": snapshot["period_start"],
        "arm": 0,
        "side": "BUY",
        "requested_price": snapshot["bars"][0]["open"],
        "executed_price": snapshot["bars"][0]["open"] * 1.001,
        "quantity": 1,
        "trade_id": "entry",
    }
    with env.db.connect(write=True) as conn:
        a.learning.record(
            conn,
            "test_forward",
            agent["agent_id"],
            env.user["user_id"],
            bp,
            agent["state"],
            1,
            {"signal_as_of": fill["timestamp"]},
            fill,
            [],
        )
        did = conn.execute("SELECT decision_id FROM learning_decisions").fetchone()[0]
    now = snapshot["period_end"] - 1
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: now))
    a.learning.resolve(did)
    with env.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM learning_outcomes").fetchone()[0] == 0
    now += 4
    a.learning.resolve(did)
    a.learning.resolve(did)
    with env.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM learning_outcomes").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM learning_jobs").fetchone()[0] == "DONE"
    assert (
        a.get(agent["agent_id"], env.user["user_id"])["revision"] == 1
    )  # Insufficient sample must not learn.
