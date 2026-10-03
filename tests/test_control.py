import copy
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.control.connectors import DatabaseAdapter, GitHubAdapter, HttpAdapter
from backend.control.models import Decision
from backend.control.verify import verify_bundle, verify_events
from backend.crypto.hashing import canonical_bytes
from backend.crypto.signatures import private_key, sign
from tests.test_platform import other_account


def setup(env, approval=False, new_targets=False, daily=5, rate=10):
    env.settings.control_resources_path = env.settings.database_path.parent / "resources.json"
    resource = {
        "id": "records",
        "kind": "database",
        "path": str(env.settings.database_path.parent / "records.sqlite3"),
        "owner_ids": [env.user["user_id"]],
        "label": "Test database",
    }
    env.settings.control_resources_path.write_text(json.dumps({"resources": [resource]}))
    policy = {
        "rules": [
            {
                "action": "database.insert",
                "resource_id": "records",
                "allowed_targets": ["tracy_records"],
                "max_units_per_action": 1,
                "daily_units": daily,
                "require_approval": approval,
            }
        ],
        "review_new_targets": new_targets,
        "max_per_minute": rate,
    }
    r = env.client.put("/v2/agents/agent_test/policy", json={"expected_version": 0, "policy": policy})
    assert r.status_code == 200, r.text
    task = env.client.post(
        "/v2/tasks",
        json={
            "agent_id": "agent_test",
            "purpose": "Record approved test results",
            "allowed_resources": ["records"],
            "allowed_actions": ["database.insert"],
        },
    )
    assert task.status_code == 201, task.text
    return task.json()["task_id"], policy, resource


def signed(env, task, **kwargs):
    body = {
        "schema_version": "tracy.intent/2",
        "request_id": "req_" + uuid4().hex,
        "agent_id": "agent_test",
        "task_id": task,
        "action": "database.insert",
        "resource_id": "records",
        "params": {"record": {"message": "hello"}},
        "reason": "Save result",
        "timestamp": int(time.time()),
        **kwargs,
    }
    return {**body, "signature": sign(private_key(env.keys["private_seed"]), canonical_bytes(body))}


def submit(env, task, **kwargs):
    r = env.client.post("/v2/intents", json=signed(env, task, **kwargs))
    assert r.status_code == 202, r.text
    return r.json()


def get(env, item):
    return env.client.get("/v2/intents/" + item["intent_id"]).json()


async def test_database_actual_execution_chain_and_idempotency(env):
    task, _, resource = setup(env)
    body = signed(env, task)
    first = env.client.post("/v2/intents", json=body).json()
    assert first["status"] == "QUEUED" and "prepared" not in first
    assert env.client.post("/v2/intents", json=body).json()["intent_id"] == first["intent_id"]
    await env.app.state.control.tick()
    completed = get(env, first)
    assert completed["status"] == "VERIFIED"
    with sqlite3.connect(resource["path"]) as db:
        assert db.execute("SELECT count(*) FROM tracy_records").fetchone()[0] == 1
    receipt = completed["receipt"]
    assert verify_bundle([receipt], env.app.state.control.receipts.public_key)["valid"]
    checked = env.client.get("/v2/intents/" + first["intent_id"] + "/verify").json()
    assert checked["valid"] and checked["verified_result"]
    assert verify_events(
        env.client.get("/v2/agents/agent_test/audit").json()["items"], receipt["poa_public_key"]
    )
    tampered = copy.deepcopy(receipt)
    tampered["intent"]["params"]["record"]["message"] = "tampered"
    assert not verify_bundle([tampered], receipt["poa_public_key"])["valid"]
    await env.app.state.control.tick()
    with sqlite3.connect(resource["path"]) as db:
        assert db.execute("SELECT count(*) FROM tracy_records").fetchone()[0] == 1


def test_signature_binding_and_semantic_replay_conflict(env):
    task, _, _ = setup(env)
    body = signed(env, task)
    bad = {**body, "reason": "changed"}
    assert env.client.post("/v2/intents", json=bad).status_code == 401
    first = env.client.post("/v2/intents", json=body)
    assert first.status_code == 202
    retry = signed(env, task, request_id=body["request_id"])
    assert env.client.post("/v2/intents", json=retry).json()["intent_id"] == first.json()["intent_id"]
    conflict = signed(env, task, request_id=body["request_id"], params={"record": {"other": 1}})
    assert env.client.post("/v2/intents", json=conflict).status_code == 409


async def test_human_approval_bound_to_intent_and_session(env):
    task, _, _ = setup(env, approval=True)
    item = submit(env, task)
    assert item["status"] == "AWAITING_APPROVAL"
    await env.app.state.control.tick()
    assert not get(env, item)["receipt"]
    path = "/v2/intents/" + item["intent_id"] + "/decision"
    decision = {"decision": "approve", "intent_hash": item["intent_hash"], "policy_version": 1}
    assert env.client.post(path, json=decision).status_code == 403
    env.client.headers.pop("Authorization")
    env.client.headers["X-CSRF-Token"] = env.client.get("/v1/auth/me").json()["csrf_token"]
    assert env.client.post(path, json={**decision, "intent_hash": "0" * 64}).status_code == 409
    assert env.client.post(path, json=decision).status_code == 200
    assert env.client.post(path, json=decision).status_code == 409
    await env.app.state.control.tick()
    assert get(env, item)["status"] == "VERIFIED"
    assert env.client.get("/v2/intents/" + item["intent_id"] + "/verify").json()["verified_result"]


async def test_human_denial_releases_reserved_budget(env):
    task, _, _ = setup(env, approval=True, daily=1)
    item = submit(env, task)
    assert submit(env, task)["reason"] == "daily_budget_exceeded"
    env.app.state.control.decide(
        item["intent_id"],
        env.user["user_id"],
        Decision(decision="deny", intent_hash=item["intent_hash"], policy_version=1, note="Not needed"),
    )
    denied = get(env, item)
    assert denied["status"] == "REJECTED" and denied["reserved_units"] == 0
    assert denied["receipt"]["approval"]["note"] == "Not needed"
    assert submit(env, task)["status"] == "AWAITING_APPROVAL"


async def test_expired_approval_and_task_revocation_fail_closed(env):
    task, _, _ = setup(env, approval=True)
    item = submit(env, task)
    with env.db.connect(write=True) as db:
        db.execute("UPDATE control_intents SET approval_expires_at=0")
    await env.app.state.control.tick()
    assert get(env, item)["status"] == "REJECTED"
    next_item = submit(env, task)
    env.client.post("/v2/tasks/" + task + "/revoke")
    await env.app.state.control.tick()
    assert get(env, next_item)["status"] == "REJECTED"


def test_limits_are_atomic_and_new_target_triggers_review(env):
    task, _, _ = setup(env, new_targets=True, daily=2)
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(lambda _: submit(env, task), range(4)))
    assert sum(x["status"] == "AWAITING_APPROVAL" for x in items) == 2
    assert sum(x["reason"] == "daily_budget_exceeded" for x in items) == 2
    assert any(x["reason"] == "anomaly_new_target" for x in items)


def test_rate_detector_and_unsupported_actions_are_blocked(env):
    task, _, _ = setup(env, rate=1)
    assert submit(env, task)["status"] == "QUEUED"
    assert submit(env, task)["reason"] == "anomaly_request_rate"
    assert submit(env, task, action="database.delete")["status"] == "REJECTED"
    assert submit(env, task, params={"sql": "DROP TABLE users"})["status"] == "REJECTED"


async def test_control_policy_prevents_legacy_bypass_and_policy_race(env):
    task, policy, _ = setup(env)
    assert env.client.post("/v1/actions", json=env.signed()).status_code == 403
    item = submit(env, task)
    env.client.put("/v2/agents/agent_test/policy", json={"expected_version": 1, "policy": policy})
    await env.app.state.control.tick()
    assert get(env, item)["status"] == "REJECTED"
    assert get(env, item)["reason"] == "policy_changed_before_execution"
    assert not env.gateway.broadcasts


async def test_stop_during_preparation_prevents_write(env, monkeypatch):
    task, _, resource = setup(env)
    original = DatabaseAdapter.prepare

    async def prepare(adapter, *args):
        result = await original(adapter, *args)
        env.app.state.control.agents.status("agent_test", env.user["user_id"], False)
        env.app.state.control.agents.status("agent_test", env.user["user_id"], True)
        return result

    monkeypatch.setattr(DatabaseAdapter, "prepare", prepare)
    item = submit(env, task)
    await env.app.state.control.tick()
    assert get(env, item)["reason"] == "agent_state_changed_before_execution"
    assert not __import__("pathlib").Path(resource["path"]).exists()


async def test_lost_response_is_read_back_without_repeating_write(env, monkeypatch):
    task, _, resource = setup(env)
    original = DatabaseAdapter.execute
    calls = []

    async def execute(adapter, p):
        calls.append(p)
        await original(adapter, p)
        raise TimeoutError("response lost")

    monkeypatch.setattr(DatabaseAdapter, "execute", execute)
    item = submit(env, task)
    await env.app.state.control.tick()
    assert get(env, item)["status"] == "VERIFIED"
    await env.app.state.control.tick()
    assert len(calls) == 1


async def test_uncertain_dispatch_never_retries_on_restart(env, monkeypatch):
    task, _, _ = setup(env)
    calls = []

    async def execute(adapter, p):
        calls.append(p)
        raise TimeoutError()

    monkeypatch.setattr(DatabaseAdapter, "execute", execute)
    item = submit(env, task)
    await env.app.state.control.tick()
    assert get(env, item)["status"] == "UNCERTAIN"
    from backend.control.service import ControlService

    replacement = ControlService(
        env.db,
        env.app.state.actions.agents,
        env.app.state.actions,
        env.app.state.actions.receipts,
        env.settings,
    )
    with env.db.connect(write=True) as db:
        db.execute("UPDATE control_intents SET next_check_at=0")
    await replacement.tick()
    assert len(calls) == 1 and get(env, item)["reserved_units"] == 1


async def test_resource_edit_invalidates_queued_intent(env):
    task, _, resource = setup(env)
    item = submit(env, task)
    resource["label"] = "Changed binding"
    env.settings.control_resources_path.write_text(json.dumps({"resources": [resource]}))
    await env.app.state.control.tick()
    assert get(env, item)["reason"] == "connector_changed_before_execution"


def test_tenant_isolation_and_signed_lookup(env):
    task, _, _ = setup(env)
    item = submit(env, task)
    with TestClient(env.app) as other:
        other_account(other)
        assert other.get("/v2/intents/" + item["intent_id"]).status_code == 404
        assert other.get("/v2/agents/agent_test/audit").status_code == 404
        assert other.post("/v2/tasks/" + task + "/revoke").status_code == 404
        assert other.get("/v2/resources").json()["items"] == [
            env.client.get("/v2/resources").json()["items"][0]
        ]
    lookup = {
        "domain": "tracy.lookup/2",
        "agent_id": "agent_test",
        "intent_id": item["intent_id"],
        "timestamp": int(time.time()),
    }
    lookup["signature"] = sign(private_key(env.keys["private_seed"]), canonical_bytes(lookup))
    with TestClient(env.app) as guest:
        assert guest.get("/v2/intents/" + item["intent_id"]).status_code == 401
        assert guest.post("/v2/intents/lookup", json=lookup).json()["intent_id"] == item["intent_id"]


async def test_database_mismatched_readback_is_failure_not_success(env, monkeypatch):
    task, _, resource = setup(env)
    original = DatabaseAdapter.execute

    async def execute(adapter, p):
        result = await original(adapter, p)
        with sqlite3.connect(resource["path"]) as db:
            db.execute("UPDATE tracy_records SET payload='{}'")
        return result

    monkeypatch.setattr(DatabaseAdapter, "execute", execute)
    item = submit(env, task)
    await env.app.state.control.tick()
    result = get(env, item)
    assert result["status"] == "FAILED" and result["reserved_units"] == 1


async def test_http_readback_must_match_request_hash_and_params(env, monkeypatch):
    registry = env.app.state.control.registry
    config = {
        "id": "api",
        "kind": "http",
        "token_env": "TRACY_TEST_TOKEN",
        "base_url": "https://example.com",
        "allowed_fields": ["prompt"],
        "required_fields": ["prompt"],
        "operation": "generate",
        "units_per_call": 100,
    }
    adapter = HttpAdapter(config, registry)
    prepared = {"intent_id": "intent_1", "intent_hash": "a" * 64, "params": {"prompt": "hello"}}
    calls = []

    async def call(method, path, **kwargs):
        calls.append((method, path))
        if method == "POST":
            return {"status": "success"}
        return {"request_hash": "wrong", "params": prepared["params"], "status": "completed"}

    monkeypatch.setattr(adapter, "call", call)
    result = await adapter.execute(prepared)
    assert (await adapter.verify(prepared, result))["status"] == "mismatch"
    assert [c[0] for c in calls] == ["POST", "GET"]


async def test_github_verification_pins_repository_commit_and_body(env, monkeypatch):
    adapter = GitHubAdapter(
        {"id": "github", "kind": "github", "repository": "owner/repo"}, env.app.state.control.registry
    )
    p = {"head": "fix", "base": "main", "head_sha": "a" * 40, "title": "Fix", "body": "Details"}
    adapter.validate("github.pull_request", p)

    async def call(method, path, **kwargs):
        if "/commits/" in path:
            return {"sha": p["head_sha"]}
        if method == "POST":
            return {"number": 12}
        return {
            "number": 12,
            "draft": True,
            "title": "Fix",
            "body": "Details\n\n<!-- tracy:i:h -->",
            "head": {"sha": "a" * 40, "ref": "fix"},
            "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
        }

    monkeypatch.setattr(adapter, "call", call)
    prepared = await adapter.prepare({"params": p}, "i", "h")
    result = await adapter.execute(prepared)
    assert (await adapter.verify(prepared, result))["status"] == "verified"
    prepared["params"]["head_sha"] = "b" * 40
    assert (await adapter.verify(prepared, result))["status"] == "mismatch"


async def test_new_control_solana_receipt_and_shared_quota(env):
    task, policy, _ = setup(env)
    policy["rules"] = [
        {
            "action": "solana.transfer",
            "resource_id": "devnet-wallet",
            "allowed_targets": [env.recipient],
            "max_units_per_action": 10000000,
            "daily_units": 20000000,
            "require_approval": False,
        }
    ]
    env.client.put("/v2/agents/agent_test/policy", json={"expected_version": 1, "policy": policy})
    task = env.client.post(
        "/v2/tasks",
        json={
            "agent_id": "agent_test",
            "purpose": "Controlled payout",
            "allowed_resources": ["devnet-wallet"],
            "allowed_actions": ["solana.transfer"],
        },
    ).json()["task_id"]
    item = submit(
        env,
        task,
        action="solana.transfer",
        resource_id="devnet-wallet",
        params={"to": env.recipient, "amount": 0.01},
    )
    await env.app.state.control.tick()
    assert get(env, item)["status"] == "VERIFIED"
    assert env.client.get("/v2/intents/" + item["intent_id"] + "/verify").json()["verified_result"]
    assert len(env.gateway.broadcasts) == 1
