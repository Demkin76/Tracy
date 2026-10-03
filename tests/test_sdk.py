import httpx
import pytest

from sdk.poa import PoAClient


def sdk(env):
    client = PoAClient()
    client.http.close()

    def handle(request):
        response = env.client.request(
            request.method, str(request.url), content=request.content, headers=dict(request.headers)
        )
        return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))

    client.http = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handle))
    return client


def test_sdk_resume_same_job_and_reject_different_payload(env):
    client = sdk(env)
    first = client.payout(env.keys["private_seed"], "agent_test", env.recipient, 0.01, "job_001")
    # Resume reads saved state instead of submitting another signed transfer.
    second = client.payout(env.keys["private_seed"], "agent_test", env.recipient, 0.01, "job_001")
    assert first["action_id"] == second["action_id"] and len(env.gateway.broadcasts) == 1
    with pytest.raises(ValueError, match="different payout"):
        client.payout(env.keys["private_seed"], "agent_test", env.recipient, 0.02, "job_001")
    assert client.verify(first["receipt_id"])["valid"]


def test_sdk_cannot_manage_without_owner_key(env):
    client = sdk(env)
    env.client.cookies.clear()
    env.client.headers.pop("Authorization")
    with pytest.raises(httpx.HTTPStatusError):
        client.agent("agent_test")
