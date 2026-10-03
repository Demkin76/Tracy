import json

import httpx

from sdk.tracy import AgentIdentity, Tracy
from sdk.tracy.mcp import MCPServer
from tests.test_control import setup


async def test_sdk_protect_uses_only_agent_signature_and_task(env):
    task, _, _ = setup(env)

    def handler(request):
        assert "authorization" not in request.headers
        response = env.client.request(request.method, request.url.path, json=json.loads(request.content))
        return httpx.Response(response.status_code, json=response.json())

    tracy = Tracy("http://testserver", task_id=task, transport=httpx.MockTransport(handler))
    agent = tracy.protect(AgentIdentity("agent_test", env.keys["private_seed"]))
    first = agent.intent("database.insert", "records", {"record": {"sdk": True}}, request_id="sdk_job")
    second = agent.intent("database.insert", "records", {"record": {"sdk": True}}, request_id="sdk_job")
    assert first["intent_id"] == second["intent_id"]
    await env.app.state.control.tick()
    assert agent.status(first["intent_id"])["status"] == "VERIFIED"
    tracy.close()


def test_mcp_handshake_tools_and_no_approval_capability():
    class Agent:
        def intent(self, **kwargs):
            return {"status": "AWAITING_APPROVAL", **kwargs}

        def status(self, intent_id):
            return {"intent_id": intent_id, "status": "VERIFIED"}

    mcp = MCPServer(Agent())

    def call(method, params=None):
        return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})

    assert "error" in call("tools/list")
    assert call("initialize")["result"]["protocolVersion"] == "2025-11-25"
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert {t["name"] for t in call("tools/list")["result"]["tools"]} == {"tracy_intent", "tracy_status"}
    result = call(
        "tools/call",
        {
            "name": "tracy_intent",
            "arguments": {
                "action": "database.insert",
                "resource_id": "records",
                "params": {"record": {}},
                "request_id": "job",
            },
        },
    )
    assert not result["result"]["isError"]
    assert "AWAITING_APPROVAL" in result["result"]["content"][0]["text"]
    assert "error" in call("tools/call", {"name": "approve", "arguments": {}})
    assert "error" in call("tools/call", {"name": "tracy_intent", "arguments": {"owner_token": "leak"}})


def test_protect_rejects_unrecognized_agent_object():
    import pytest

    tracy = Tracy()
    with pytest.raises(TypeError):
        tracy.protect(object(), task_id="task")
    tracy.close()
