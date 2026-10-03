import json

import pytest

from backend.blockchain.solana import PreflightRejected
from backend.control.connectors import DatabaseAdapter
from sdk.tracy.langchain import tools
from tests.test_control import get, setup, submit


def test_langchain_tool_is_guarded_and_requires_retry_key():
    pytest.importorskip("langchain_core")
    calls = []

    class Protected:
        def tool(self, action, resource_id):
            def invoke(params, request_id, reason=""):
                calls.append((action, resource_id, params, request_id))
                return {"status": "AWAITING_APPROVAL"}

            return invoke

    tool = tools(
        Protected(),
        [
            {
                "action": "database.insert",
                "resource_id": "records",
                "name": "record_result",
                "description": "Request a controlled database write",
            }
        ],
    )[0]
    assert (
        tool.invoke({"params": {"record": {"value": 1}}, "request_id": "stable-job"})["status"]
        == "AWAITING_APPROVAL"
    )
    assert calls == [("database.insert", "records", {"record": {"value": 1}}, "stable-job")]
    with pytest.raises(ValueError):
        tool.invoke({"params": {}})


async def test_provable_preflight_rejection_releases_reservation(env, monkeypatch):
    task, _, _ = setup(env)

    async def rejected(adapter, prepared):
        raise PreflightRejected("Explicit rejection before broadcast")

    monkeypatch.setattr(DatabaseAdapter, "execute", rejected)
    item = submit(env, task)
    await env.app.state.control.tick()
    result = get(env, item)
    assert result["status"] == "FAILED"
    assert result["reason"] == "preflight_rejected"
    assert result["reserved_units"] == 0
    assert result["receipt"]["verification"]["status"] == "not_executed"


async def test_queued_intent_is_charged_to_dispatch_day(env, monkeypatch):
    import backend.control.service as module

    task, _, _ = setup(env, daily=1)
    item = submit(env, task)
    monkeypatch.setattr(module, "utc_day", lambda: "2030-01-02")
    await env.app.state.control.tick()
    completed = get(env, item)
    assert completed["status"] == "VERIFIED"
    assert completed["budget_day"] == "2030-01-02"
    assert submit(env, task)["status"] == "REJECTED"


async def test_approval_queue_does_not_starve_later_jobs(env):
    task, _, _ = setup(env, approval=True, daily=100, rate=100)
    items = [submit(env, task) for _ in range(31)]
    last = items[-1]
    from backend.control.models import Decision

    env.app.state.control.decide(
        last["intent_id"],
        env.user["user_id"],
        Decision(decision="approve", intent_hash=last["intent_hash"], policy_version=last["policy_version"]),
    )
    await env.app.state.control.tick()
    await env.app.state.control.tick()
    assert get(env, last)["status"] == "VERIFIED"
    assert get(env, items[0])["status"] == "AWAITING_APPROVAL"


def test_operator_plugins_require_adapter_contract(env):
    registry = env.app.state.control.registry
    adapter = registry.adapter({"kind": "plugin", "adapter": "backend.control.connectors:DatabaseAdapter"})
    assert isinstance(adapter, DatabaseAdapter)
    with pytest.raises(ValueError):
        registry.adapter({"kind": "plugin", "adapter": "builtins:dict"})


async def test_resource_response_never_exposes_operator_credentials(env):
    _, _, resource = setup(env)
    resource["token_env"] = "SECRET_ENV_NAME"
    resource["private_note"] = "secret-config-value"
    env.settings.control_resources_path.write_text(json.dumps({"resources": [resource]}))
    response = env.client.get("/v2/resources")
    assert response.status_code == 200
    assert "secret-config-value" not in response.text and "SECRET_ENV_NAME" not in response.text
    assert resource["path"] not in response.text
