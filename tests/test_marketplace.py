import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend.blockchain.solana import Evidence
from backend.marketplace.service import Marketplace
from tests.test_platform import other_account, publish


def offer(env, kind="batch_payout"):
    publish(env)
    r = env.client.put("/v1/agents/agent_test/offer", json={"kind": kind})
    assert r.status_code == 200, r.text
    return r.json()


def payload(env, **kwargs):
    return {
        "request_id": "install_1",
        "source_agent_id": "agent_test",
        "expected_version": 1,
        "name": "My payouts",
        "policy": {**env.registration["policy"], "daily_budget_sol": 0.015},
        "plan": {"transfers": [{"to": env.recipient, "amount": 0.01}]},
        **kwargs,
    }


def install(env, **kwargs):
    r = env.client.post("/v1/installations", json=payload(env, **kwargs))
    assert r.status_code == 201, r.text
    return r.json()


def run(env, agent_id, request_id="job_1"):
    r = env.client.post(f"/v1/installations/{agent_id}/runs", json={"request_id": request_id})
    assert r.status_code == 202, r.text
    return r.json()


def history(env, agent_id):
    return env.client.get(f"/v1/installations/{agent_id}/runs").json()["items"]


async def test_install_run_proof_idempotency_and_budget(env):
    offer(env)
    item = install(env)
    agent_id = item["agent_id"]
    assert item["agent"]["public_key"] != env.keys["public_key"]
    assert not item["agent"]["listed"] and not item["running"]
    assert install(env)["agent_id"] == agent_id
    assert env.client.post("/v1/installations", json=payload(env, name="Different")).status_code == 409
    one = run(env, agent_id)
    assert run(env, agent_id)["run_id"] == one["run_id"]
    await env.app.state.marketplace.tick()
    saved = history(env, agent_id)[0]
    assert saved["status"] == "COMPLETED" and len(saved["actions"]) == 1
    proof = env.client.get("/v1/receipts/" + saved["actions"][0]["receipt_id"] + "/verify")
    assert proof.json()["valid"]
    run(env, agent_id, "job_2")
    await env.app.state.marketplace.tick()
    assert history(env, agent_id)[0]["status"] == "BLOCKED"
    assert history(env, agent_id)[0]["reason"] == "daily_budget_exceeded"
    assert len(env.gateway.broadcasts) == 1


def test_install_is_atomic_and_deduplicated_under_concurrency(env):
    offer(env)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: install(env), range(4)))
    assert len({r["agent_id"] for r in rows}) == 1
    assert env.client.get("/v1/installations").json()["items"][0]["agent_id"] == rows[0]["agent_id"]


def test_offer_availability_version_and_validation(env):
    assert env.client.post("/v1/installations", json=payload(env)).status_code == 404
    offer(env)
    assert env.client.get("/v1/public/agents/agent_test").json()["offer"]["kind"] == "batch_payout"
    p = payload(env)
    p["plan"]["transfers"][0]["amount"] = 0.2
    assert env.client.post("/v1/installations", json=p).status_code == 422
    p = payload(env)
    p["plan"]["max_cycles"] = 2
    assert env.client.post("/v1/installations", json=p).status_code == 422
    offer(env, "scheduled_payout")
    assert env.client.post("/v1/installations", json=payload(env)).status_code == 409
    publish(env, False)
    assert env.client.post("/v1/installations", json=payload(env, expected_version=2)).status_code == 404


async def test_two_customers_have_private_independent_installations(env):
    offer(env)
    first = install(env)
    with TestClient(env.app) as other:
        other_account(other)
        second = other.post("/v1/installations", json=payload(env)).json()
        assert second["agent_id"] != first["agent_id"]
        for path in ("", "/runs"):
            assert other.get("/v1/installations/" + first["agent_id"] + path).status_code == 404
        assert other.post("/v1/installations/" + first["agent_id"] + "/stop").status_code == 404
        assert other.put("/v1/agents/agent_test/offer", json={"kind": "batch_payout"}).status_code == 404
        assert env.client.get("/v1/installations/" + second["agent_id"]).status_code == 404
        run(env, first["agent_id"])
        await env.app.state.marketplace.tick()
        assert other.get("/v1/installations/" + second["agent_id"] + "/runs").json()["total"] == 0
    assert env.client.get("/v1/public/agents/" + first["agent_id"]).status_code == 404


async def test_schedule_is_bounded_and_does_not_catch_up_missed_cycles(env):
    offer(env, "scheduled_payout")
    item = install(
        env,
        plan={"transfers": [{"to": env.recipient, "amount": 0.001}], "interval_seconds": 60, "max_cycles": 2},
    )
    aid = item["agent_id"]
    assert env.client.post(f"/v1/installations/{aid}/start").status_code == 200
    assert env.client.post(f"/v1/installations/{aid}/start").status_code == 200
    await env.app.state.marketplace.tick()
    assert len(env.gateway.broadcasts) == 1
    await env.app.state.marketplace.tick()
    assert len(env.gateway.broadcasts) == 1
    with env.db.connect(write=True) as conn:
        conn.execute("UPDATE installations SET next_run_at=0 WHERE agent_id=?", (aid,))
    await env.app.state.marketplace.tick()
    assert len(env.gateway.broadcasts) == 2
    item = env.client.get(f"/v1/installations/{aid}").json()
    assert not item["running"] and item["cycles"] == 2
    await env.app.state.marketplace.tick()
    assert len(env.gateway.broadcasts) == 2


async def test_pending_restart_does_not_repeat_transfer_or_advance_batch(env):
    offer(env)
    item = install(
        env,
        plan={"transfers": [{"to": env.recipient, "amount": 0.001}, {"to": env.recipient, "amount": 0.002}]},
    )
    aid = item["agent_id"]
    env.gateway.evidence = Evidence("unavailable", "rpc_down")
    run(env, aid)
    await env.app.state.marketplace.tick()
    assert history(env, aid)[0]["status"] == "WAITING"
    replacement = Marketplace(env.db, env.app.state.actions.agents, env.app.state.actions, env.settings)
    await replacement.tick()
    assert len(env.gateway.broadcasts) == 1
    env.gateway.evidence = Evidence("verified", "exact_transfer_confirmed", 123)
    action_id = history(env, aid)[0]["actions"][0]["action_id"]
    await env.app.state.actions.reconcile(action_id)
    await replacement.tick()
    assert len(env.gateway.broadcasts) == 2
    assert history(env, aid)[0]["status"] == "COMPLETED"


async def test_stop_cancels_queued_and_schedule_resume_does_not_restart(env):
    offer(env, "scheduled_payout")
    aid = install(env)["agent_id"]
    run(env, aid)
    env.client.post(f"/v1/agents/{aid}/status", json={"active": False})
    await env.app.state.marketplace.tick()
    assert not env.gateway.broadcasts
    assert history(env, aid)[0]["status"] == "CANCELLED"
    env.client.post(f"/v1/agents/{aid}/status", json={"active": True})
    await env.app.state.marketplace.tick()
    assert not env.gateway.broadcasts
    env.client.post(f"/v1/installations/{aid}/start")
    env.client.post(f"/v1/installations/{aid}/stop")
    assert not env.client.get(f"/v1/installations/{aid}").json()["running"]


async def test_stop_during_prepare_prevents_broadcast(env):
    offer(env)
    aid = install(env)["agent_id"]
    original = env.gateway.prepare

    async def prepare(*args):
        result = await original(*args)
        env.app.state.marketplace.stop(aid, env.user["user_id"])
        return result

    env.gateway.prepare = prepare
    run(env, aid)
    await env.app.state.marketplace.tick()
    assert not env.gateway.broadcasts
    assert history(env, aid)[0]["status"] == "CANCELLED"
    assert history(env, aid)[0]["actions"][0]["status"] == "REJECTED"


async def test_author_edits_or_unpublishes_do_not_mutate_installed_agent(env):
    offer(env)
    item = install(env)
    offer(env, "scheduled_payout")
    publish(env, False)
    current = env.client.get("/v1/installations/" + item["agent_id"]).json()
    assert current["kind"] == "batch_payout" and current["offer_version"] == 1
    run(env, item["agent_id"])
    await env.app.state.marketplace.tick()
    assert len(env.gateway.broadcasts) == 1


def test_plan_edit_revision_and_busy_protection(env):
    offer(env)
    item = install(env)
    path = "/v1/installations/" + item["agent_id"] + "/plan"
    change = {"expected_revision": 1, "plan": {"transfers": [{"to": env.recipient, "amount": 0.001}]}}
    assert env.client.put(path, json=change).json()["revision"] == 2
    assert env.client.put(path, json=change).status_code == 409
    run(env, item["agent_id"])
    change["expected_revision"] = 2
    assert env.client.put(path, json=change).status_code == 409


async def test_worker_recovers_action_insert_before_run_progress_saved(env):
    offer(env)
    item = install(env)
    queued = run(env, item["agent_id"])
    # Mimic a process dying after action was admitted but before run progress persisted.
    import time

    from backend.actions.models import ActionRequest
    from backend.crypto.hashing import canonical_bytes
    from backend.crypto.signatures import sign

    unsigned = {
        "request_id": queued["run_id"] + "_0",
        "agent_id": item["agent_id"],
        "action": "solana.transfer",
        "params": {"to": env.recipient, "amount": 0.01},
        "timestamp": int(time.time()),
    }
    key = env.app.state.marketplace.key(item["agent_id"])
    await env.app.state.actions.submit(
        ActionRequest(**unsigned, signature=sign(key, canonical_bytes(unsigned)))
    )
    await env.app.state.marketplace.tick()
    assert len(env.gateway.broadcasts) == 1 and history(env, item["agent_id"])[0]["status"] == "COMPLETED"


async def test_two_ticks_do_not_double_broadcast(env):
    offer(env)
    aid = install(env)["agent_id"]
    run(env, aid)
    await asyncio.gather(env.app.state.marketplace.tick(), env.app.state.marketplace.tick())
    assert len(env.gateway.broadcasts) == 1


def test_install_and_runner_mutations_require_manage_scope_and_csrf(env):
    offer(env)
    aid = install(env)["agent_id"]
    readonly = env.client.post("/v1/account/api-keys", json={"name": "Reader", "scope": "read"}).json()
    with TestClient(env.app) as reader:
        reader.headers["Authorization"] = "Bearer " + readonly["token"]
        assert reader.get("/v1/installations/" + aid).status_code == 200
        for suffix in ("start", "stop", "runs"):
            assert (
                reader.post(
                    "/v1/installations/" + aid + "/" + suffix,
                    json={"request_id": "read_attempt"} if suffix == "runs" else {},
                ).status_code
                == 403
            )
        assert reader.post("/v1/installations", json=payload(env, request_id="other")).status_code == 403
    with TestClient(env.app) as guest:
        assert guest.get("/v1/installations").status_code == 401
        assert guest.post("/v1/installations", json=payload(env)).status_code == 401
    env.client.headers.pop("Authorization")
    assert (
        env.client.post("/v1/installations/" + aid + "/runs", json={"request_id": "csrf"}).status_code == 403
    )


async def test_failed_first_row_stops_rest_and_schedule(env):
    offer(env, "scheduled_payout")
    aid = install(
        env,
        plan={
            "transfers": [{"to": env.recipient, "amount": 0.001}, {"to": env.recipient, "amount": 0.002}],
            "interval_seconds": 60,
            "max_cycles": 3,
        },
    )["agent_id"]
    env.gateway.prepare_error = RuntimeError("RPC unavailable")
    env.client.post("/v1/installations/" + aid + "/start")
    await env.app.state.marketplace.tick()
    result = history(env, aid)[0]
    assert result["status"] == "FAILED" and len(result["actions"]) == 1
    assert not env.client.get("/v1/installations/" + aid).json()["running"]
    assert not env.gateway.broadcasts
    env.gateway.prepare_error = None
    await env.app.state.marketplace.tick()
    assert not env.gateway.broadcasts


async def test_stop_after_broadcast_retains_pending_action_and_never_sends_next(env):
    offer(env)
    aid = install(
        env,
        plan={"transfers": [{"to": env.recipient, "amount": 0.001}, {"to": env.recipient, "amount": 0.002}]},
    )["agent_id"]
    env.gateway.evidence = Evidence("pending", "awaiting_confirmation")
    run(env, aid)
    await env.app.state.marketplace.tick()
    env.app.state.marketplace.stop(aid, env.user["user_id"])
    original = history(env, aid)[0]["actions"][0]["action_id"]
    env.gateway.evidence = Evidence("verified", "exact_transfer_confirmed", 123)
    await env.app.state.actions.reconcile(original)
    await env.app.state.marketplace.tick()
    assert history(env, aid)[0]["status"] == "CANCELLED"
    assert history(env, aid)[0]["actions"][0]["status"] == "VERIFIED"
    assert len(env.gateway.broadcasts) == 1


async def test_graceful_worker_shutdown_drains_managed_action(env):
    from backend.platform.runtime import Reconciler

    worker = Reconciler(env.db, env.app.state.actions, 0.01)
    started, release = asyncio.Event(), asyncio.Event()

    class Managed:
        async def tick(self):
            started.set()
            await release.wait()

    worker.marketplace = Managed()
    worker.start()
    await started.wait()
    closing = asyncio.create_task(worker.stop())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    assert worker.task.done()
