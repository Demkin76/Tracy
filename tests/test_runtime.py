from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.agents.service import AgentService
from backend.blockchain.solana import Evidence
from backend.platform.runtime import Reconciler, SingleWorkerLock


async def test_background_reconciliation_finishes_without_resending(env):
    env.gateway.evidence = Evidence("pending", "not_yet_confirmed")
    action = env.client.post("/v1/actions", json=env.signed()).json()
    env.gateway.evidence = Evidence("verified", "exact_transfer_confirmed", 123)
    with env.db.connect(write=True) as conn:
        conn.execute("UPDATE actions SET next_check_at=0")
    worker = Reconciler(env.db, env.app.state.actions, 0.05)
    await worker.tick()
    final = env.client.get("/v1/actions/" + action["action_id"]).json()
    assert final["status"] == "VERIFIED" and final["check_attempts"] == 2
    assert worker.last_tick_at and len(env.gateway.broadcasts) == 1
    await worker.tick()
    assert len(env.gateway.broadcasts) == 1


async def test_worker_backs_off_unavailable_rpc_and_keeps_reservation(env):
    env.gateway.evidence = Evidence("unavailable", "rpc_down")
    action = env.client.post("/v1/actions", json=env.signed()).json()
    with env.db.connect(write=True) as conn:
        conn.execute("UPDATE actions SET next_check_at=0")
    await env.app.state.runtime.tick()
    saved = env.db.action(action["action_id"])
    assert saved["status"] == "PENDING" and saved["reserved_lamports"] == 10_000_000
    lookups = len(env.gateway.lookups)
    await env.app.state.runtime.tick()
    assert len(env.gateway.lookups) == lookups and len(env.gateway.broadcasts) == 1


def test_runtime_lock_prevents_second_worker_and_releases(tmp_path):
    one, two = SingleWorkerLock(tmp_path / "db"), SingleWorkerLock(tmp_path / "db")
    one.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another Tracy worker"):
            two.acquire()
    finally:
        one.release()
    two.acquire()
    two.release()


def test_owner_quota_is_atomic_across_agents(env):
    env.settings.owner_daily_lamports = 20_000_000
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: env.client.post("/v1/actions", json=env.signed()).json(), range(6)))
    assert sum(r["status"] == "VERIFIED" for r in results) == 2
    assert all(r["status"] == "VERIFIED" or r["reason"] == "owner_daily_budget_exceeded" for r in results)
    assert env.client.get("/v1/funding").json()["remaining_lamports"] == 0
    for r in results:
        assert env.client.get("/v1/receipts/" + r["receipt_id"] + "/verify").json()["valid"]


def test_platform_quota_and_execution_pause(env):
    env.settings.platform_daily_lamports = 1
    action = env.client.post("/v1/actions", json=env.signed()).json()
    assert action["reason"] == "platform_daily_budget_exceeded" and not env.gateway.broadcasts
    env.settings.execution_enabled = False
    action = env.client.post("/v1/actions", json=env.signed()).json()
    assert action["reason"] == "platform_execution_paused"
    assert env.client.get("/v1/receipts/" + action["receipt_id"] + "/verify").json()["valid"]


def test_stop_then_resume_during_prepare_still_cancels_old_intent(env):
    original = env.gateway.prepare

    async def prepare(*args):
        result = await original(*args)
        service = AgentService(env.db)
        service.status("agent_test", env.user["user_id"], False)
        service.status("agent_test", env.user["user_id"], True)
        return result

    env.gateway.prepare = prepare
    result = env.client.post("/v1/actions", json=env.signed()).json()
    assert result["reason"] == "agent_state_changed_before_submission"
    assert not env.gateway.broadcasts
    assert env.client.get("/v1/receipts/" + result["receipt_id"] + "/verify").json()["valid"]
