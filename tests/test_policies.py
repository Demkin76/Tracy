import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.agents.models import UpdatePolicy
from backend.agents.service import AgentService
from backend.blockchain.solana import Evidence
from backend.policies.engine import utc_day


def update(env, **changes):
    current = env.client.get("/v1/agents/agent_test").json()
    response = env.client.put(
        "/v1/agents/agent_test/policy",
        json={
            "expected_version": current["policy_version"],
            "policy": {**current["policy"], **changes},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def used(env):
    return env.client.get("/v1/agents/agent_test").json()["budget"]["used_lamports"]


def test_atomic_daily_budget_under_parallel_requests(env):
    update(env, daily_budget_sol=0.03)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(lambda _: env.client.post("/v1/actions", json=env.signed()).json(), range(8))
        )
    assert sorted(r["status"] for r in responses) == ["REJECTED"] * 5 + ["VERIFIED"] * 3
    assert len(env.gateway.broadcasts) == 3 and used(env) == 30_000_000
    for r in responses:
        if r["status"] == "REJECTED":
            assert r["reason"] == "daily_budget_exceeded"
        assert env.client.get("/v1/receipts/" + r["receipt_id"] + "/verify").json()["valid"]


def test_pending_reservation_failure_release_and_mismatch_hold(env):
    update(env, daily_budget_sol=0.01)
    env.gateway.evidence = Evidence("pending", "not_confirmed")
    pending = env.client.post("/v1/actions", json=env.signed()).json()
    assert used(env) == 10_000_000 and pending["status"] == "PENDING"
    assert env.client.post("/v1/actions", json=env.signed()).json()["reason"] == "daily_budget_exceeded"
    env.gateway.evidence = Evidence("failed", "transaction_failed")
    assert env.client.post("/v1/actions/" + pending["action_id"] + "/reconcile").json()["status"] == "FAILED"
    assert used(env) == 0
    env.gateway.evidence = Evidence("mismatch", "wrong_transfer")
    assert env.client.post("/v1/actions", json=env.signed()).json()["status"] == "FAILED"
    assert used(env) == 10_000_000


def test_utc_day_rollover_keeps_unresolved_reservations(env, monkeypatch):
    update(env, daily_budget_sol=0.02)
    env.client.post("/v1/actions", json=env.signed())
    env.gateway.evidence = Evidence("pending", "not_confirmed")
    env.client.post("/v1/actions", json=env.signed())
    assert used(env) == 20_000_000
    tomorrow = "2099-01-02"
    monkeypatch.setattr("backend.actions.service.utc_day", lambda: tomorrow)
    monkeypatch.setattr("backend.agents.service.utc_day", lambda: tomorrow)
    assert used(env) == 10_000_000
    env.gateway.evidence = Evidence("verified", "exact_transfer_confirmed", 123)
    result = env.client.post("/v1/actions", json=env.signed()).json()
    assert result["status"] == "VERIFIED"
    assert result["receipt"]["policy"]["context"]["budget_day"] == tomorrow
    assert used(env) == 20_000_000
    assert utc_day() != tomorrow


def test_policy_versions_conflict_immutability_and_old_receipt(env):
    action = env.client.post("/v1/actions", json=env.signed()).json()
    receipt = action["receipt"]
    revised = update(env, daily_budget_sol=0.005, max_transfer_sol=0.005)
    assert revised["policy_version"] == 2 and revised["budget"]["remaining_lamports"] == 0
    assert env.client.get("/v1/receipts/" + receipt["receipt_id"]).json() == receipt
    assert env.client.get("/v1/receipts/" + receipt["receipt_id"] + "/verify").json()["valid"]
    assert (
        env.client.put(
            "/v1/agents/agent_test/policy", json={"expected_version": 1, "policy": env.registration["policy"]}
        ).status_code
        == 409
    )
    versions = env.client.get("/v1/agents/agent_test/policy/versions").json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    for sql in ("UPDATE policy_versions SET version=99", "DELETE FROM policy_versions"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"), env.db.connect(write=True) as conn:
            conn.execute(sql)


def test_stop_and_resume_do_not_erase_history(env):
    assert env.client.post("/v1/agents/agent_test/status", json={"active": False}).status_code == 200
    rejected = env.client.post("/v1/actions", json=env.signed()).json()
    assert rejected["reason"] == "agent_stopped" and not env.gateway.prepared
    assert env.client.get("/v1/receipts/" + rejected["receipt_id"] + "/verify").json()["valid"]
    assert used(env) == 0
    env.client.post("/v1/agents/agent_test/status", json={"active": True})
    assert env.client.post("/v1/actions", json=env.signed()).json()["status"] == "VERIFIED"
    assert env.client.get("/v1/agents/agent_test/actions").json()["total"] == 2


@pytest.mark.parametrize("change", ["stop", "policy"])
def test_change_during_rpc_prepare_prevents_broadcast(env, change):
    original = env.gateway.prepare

    async def prepare(*args):
        prepared = await original(*args)
        agents = AgentService(env.db)
        if change == "stop":
            agents.status("agent_test", env.user["user_id"], False)
        else:
            agents.update_policy(
                "agent_test",
                env.user["user_id"],
                UpdatePolicy(
                    expected_version=1,
                    policy={**env.registration["policy"], "daily_budget_sol": 0.001},
                ),
            )
        return prepared

    env.gateway.prepare = prepare
    action = env.client.post("/v1/actions", json=env.signed()).json()
    assert action["status"] == "REJECTED"
    assert action["reason"] == ("agent_stopped" if change == "stop" else "policy_changed_before_submission")
    assert not env.gateway.broadcasts and used(env) == 0
    assert env.client.get("/v1/receipts/" + action["receipt_id"] + "/verify").json()["valid"]


def test_stop_cannot_recall_pending_dispatch(env):
    env.gateway.evidence = Evidence("pending", "not_confirmed")
    action = env.client.post("/v1/actions", json=env.signed()).json()
    env.client.post("/v1/agents/agent_test/status", json={"active": False})
    env.gateway.evidence = Evidence("verified", "exact_transfer_confirmed", 123)
    assert env.client.post("/v1/actions/" + action["action_id"] + "/reconcile").json()["status"] == "VERIFIED"
    assert len(env.gateway.broadcasts) == 1
