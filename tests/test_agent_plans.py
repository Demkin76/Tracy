import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.crypto.hashing import digest
from backend.crypto.signatures import verify
from tests.test_platform import other_account


def payload(**changes):
    return {"name": "Reviewed SOL", "goal": "Trade SOL carefully with approval for larger orders", **changes}


def make_plan(env, **changes):
    r = env.client.post("/v1/agent-plans", json=payload(**changes))
    assert r.status_code == 201, r.text
    return r.json()


def deploy(env, plan, **changes):
    return env.client.post(
        "/v1/agent-plans/" + plan["plan_id"] + "/deploy",
        json={"reviewed_hash": plan["review_hash"], "acknowledged": True, **changes},
    )


def test_no_agent_until_review_and_exactly_one_after_retry(env):
    before = env.client.get("/v1/agents").json()["items"]
    plan = make_plan(env)
    assert plan["report"]["ready"]
    assert plan["report"]["passed"] == plan["report"]["total"] == 12
    assert len(plan["report"]["simulations"]) == 3
    assert env.client.get("/v1/agents").json()["items"] == before
    assert env.client.get("/v1/strategies").json()["items"] == []
    assert deploy(env, plan, acknowledged=False).status_code == 422
    assert deploy(env, plan, reviewed_hash="0" * 64).status_code == 409
    response = deploy(env, plan)
    assert response.status_code == 200, response.text
    assert deploy(env, plan).json() == response.json()
    assert len(env.client.get("/v1/agents").json()["items"]) == len(before) + 1
    sid, aid = response.json()["strategy_id"], response.json()["agent_id"]
    detail = env.client.get("/v1/strategies/" + sid).json()
    assert detail["status"] == "LIVE" and not detail["listed"]
    assert detail["description"] == plan["configuration"]["goal"]
    assert detail["guardrails"] == plan["configuration"]["guardrails"]
    assert detail["performance"]["deployment"]["step"] == 0
    assert env.client.get("/v1/agents/" + aid).json()["policy"]["allowed_actions"] == []
    assert env.client.get("/v2/agents/" + aid + "/policy").json()["policy"]["rules"] == []
    baseline = env.client.get("/v1/strategies/" + sid + "/tests").json()["items"][0]
    body = {k: v for k, v in baseline.items() if k not in ("result_hash", "public_key", "signature")}
    assert digest(body) == baseline["result_hash"]
    assert verify(baseline["public_key"], baseline["signature"], bytes.fromhex(baseline["result_hash"]))
    advance = env.client.post("/v1/strategies/" + sid + "/advance", json={"expected_step": 0, "steps": 24})
    assert advance.status_code == 200, advance.text
    assert advance.json()["step"] > 0


def test_plan_owner_isolation_and_read_only_key(env):
    plan = make_plan(env)
    other = TestClient(env.app)
    other_account(other)
    path = "/v1/agent-plans/" + plan["plan_id"]
    assert other.get(path).status_code == 404
    assert (
        other.post(
            path + "/deploy", json={"reviewed_hash": plan["review_hash"], "acknowledged": True}
        ).status_code
        == 404
    )
    other.close()
    key = env.client.post("/v1/account/api-keys", json={"name": "Read", "scope": "read"}).json()
    response = env.client.post(
        "/v1/agent-plans", json=payload(), headers={"Authorization": "Bearer " + key["token"]}
    )
    assert response.status_code == 403


def test_tested_snapshot_is_immutable_and_edits_require_new_test(env):
    plan = make_plan(env)
    changed = make_plan(env, goal="A different intent with smaller exposure")
    assert changed["review_hash"] != plan["review_hash"]
    assert deploy(env, changed, reviewed_hash=plan["review_hash"]).status_code == 409
    with env.db.connect(write=True) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE agent_plans SET configuration='{}' WHERE plan_id=?", (plan["plan_id"],))
    stored = env.client.get("/v1/agent-plans/" + plan["plan_id"]).json()
    assert stored["configuration"] == plan["configuration"]


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"forbidden": []},
        {"starting_capital": 100},
        {"guardrails": {"allowed_markets": ["ETH/USDC"]}},
        {"guardrails": {"max_trade_size": 20000}},
        {"starting_capital": "NaN"},
    ],
)
def test_incoherent_configuration_is_rejected(env, changes):
    assert env.client.post("/v1/agent-plans", json=payload(**changes)).status_code == 422


def test_atomic_deployment_rolls_back_and_can_retry(env, monkeypatch):
    plan = make_plan(env)
    original = env.app.state.control.event

    def failure(*args, **kwargs):
        raise RuntimeError("Injected audit failure")

    monkeypatch.setattr(env.app.state.control, "event", failure)
    with pytest.raises(RuntimeError, match="Injected audit failure"):
        deploy(env, plan)
    with env.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM agents").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM strategies").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM trading_deployments").fetchone()[0] == 0
    monkeypatch.setattr(env.app.state.control, "event", original)
    assert deploy(env, plan).status_code == 200


def test_disabled_execution_and_failed_checks_cannot_deploy(env, monkeypatch):
    plan = make_plan(env)
    env.settings.execution_enabled = False
    assert deploy(env, plan).status_code == 409
    env.settings.execution_enabled = True
    original = env.app.state.strategies.trading.evaluate
    monkeypatch.setattr(
        env.app.state.strategies.trading, "evaluate", lambda *a, **kw: ("allow", "broken", {})
    )
    broken = make_plan(env)
    assert not broken["report"]["ready"]
    assert deploy(env, broken).status_code == 409
    monkeypatch.setattr(env.app.state.strategies.trading, "evaluate", original)
    with env.db.connect() as conn:
        assert (
            json.loads(
                conn.execute(
                    "SELECT report FROM agent_plans WHERE plan_id=?", (broken["plan_id"],)
                ).fetchone()[0]
            )["ready"]
            is False
        )
