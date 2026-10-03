import json
import time

from fastapi.testclient import TestClient

from backend.blockchain.solana import Evidence
from backend.platform.service import metrics


def publish(env, listed=True):
    r = env.client.put(
        "/v1/agents/agent_test/publication",
        json={
            "listed": listed,
            "category": "payouts",
            "tagline": "Verified payouts",
            "disclose_history": listed,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_catalog_is_opt_in_and_unpublish_revokes_all_public_routes(env):
    action = env.client.post("/v1/actions", json=env.signed()).json()
    rid = action["receipt_id"]
    with TestClient(env.app) as guest:
        assert guest.get("/v1/public/agents").json()["total"] == 0
        for path in (
            "/agents/agent_test",
            "/agents/agent_test/receipts",
            "/receipts/" + rid,
            "/receipts/" + rid + "/verify",
        ):
            assert guest.get("/v1/public" + path).status_code == 404
        assert env.client.put("/v1/agents/agent_test/publication", json={"listed": True}).status_code == 422
        publish(env)
        result = guest.get("/v1/public/agents?q=verified&category=payouts&sort=reliability").json()
        assert result["total"] == 1
        public = result["items"][0]
        assert public["metrics"]["counts"]["VERIFIED"] == 1
        assert public["metrics"]["reliability_score"] is None
        assert "owner_id" not in public and "policy" not in public and "email" not in public
        assert guest.get("/v1/public/receipts/" + rid).json() == action["receipt"]
        assert guest.get("/v1/public/receipts/" + rid + "/verify").json()["valid"]
        assert len(guest.get("/v1/public/receipts/" + rid + "/chain").json()["items"]) == 1
        publish(env, False)
        assert guest.get("/v1/public/agents").json()["total"] == 0
        for suffix in ("", "/verify", "/chain"):
            assert guest.get("/v1/public/receipts/" + rid + suffix).status_code == 404
    assert env.client.get("/v1/receipts/" + rid).status_code == 200


def test_share_is_scoped_expiring_and_revocable_without_publishing_agent(env):
    first = env.client.post("/v1/actions", json=env.signed()).json()
    second = env.client.post("/v1/actions", json=env.signed(amount=5)).json()
    payload = {"receipt_id": second["receipt_id"], "disclose_receipt": True, "expires_days": 1}
    assert env.client.post("/v1/shares", json={**payload, "disclose_receipt": False}).status_code == 422
    share = env.client.post("/v1/shares", json=payload).json()
    path = "/v1/public/proofs/" + share["share_id"]
    with TestClient(env.app) as guest:
        assert guest.get(path).json() == second["receipt"]
        assert guest.get(path + "/verify").json()["valid"]
        assert guest.get(path + "/chain").status_code == 404
        assert guest.get("/v1/public/receipts/" + first["receipt_id"]).status_code == 404
        assert guest.get("/v1/public/agents").json()["total"] == 0
        assert env.client.delete("/v1/shares/" + share["share_id"]).status_code == 200
        assert guest.get(path).status_code == 404
        share2 = env.client.post("/v1/shares", json=payload).json()
        with env.db.connect(write=True) as conn:
            conn.execute("UPDATE proof_shares SET expires_at=0 WHERE share_id=?", (share2["share_id"],))
        assert guest.get("/v1/public/proofs/" + share2["share_id"]).status_code == 404


def other_account(client):
    r = client.post(
        "/v1/auth/signup",
        json={"email": "second@example.test", "name": "Second", "password": "long-safe-password"},
    )
    assert r.status_code == 201
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]


def test_other_owner_cannot_publish_share_or_revoke(env):
    a = env.client.post("/v1/actions", json=env.signed()).json()
    share = env.client.post(
        "/v1/shares", json={"receipt_id": a["receipt_id"], "disclose_receipt": True}
    ).json()
    with TestClient(env.app) as other:
        other_account(other)
        assert (
            other.put(
                "/v1/agents/agent_test/publication", json={"listed": True, "disclose_history": True}
            ).status_code
            == 404
        )
        assert (
            other.post(
                "/v1/shares", json={"receipt_id": a["receipt_id"], "disclose_receipt": True}
            ).status_code
            == 404
        )
        assert other.delete("/v1/shares/" + share["share_id"]).status_code == 404
        for url in ("/history", "/analytics", "/shares", "/notifications", "/account/events", "/favorites"):
            body = other.get("/v1" + url).json()
            assert "agent_test" not in json.dumps(body)
        assert other.get("/v1/history?agent_id=agent_test").status_code == 404


def test_watchlist_hides_unpublished_agents(env):
    assert env.client.put("/v1/favorites/agent_test").status_code == 404
    publish(env)
    assert env.client.put("/v1/favorites/agent_test").status_code == 200
    assert env.client.put("/v1/favorites/agent_test").status_code == 200
    assert len(env.client.get("/v1/favorites").json()["items"]) == 1
    publish(env, False)
    assert env.client.get("/v1/favorites").json()["items"] == []
    assert env.client.delete("/v1/favorites/agent_test").status_code == 200


def test_history_filters_pagination_csv_and_analytics(env):
    env.client.patch("/v1/agents/agent_test", json={"name": "=formula", "description": ""})
    one = env.client.post("/v1/actions", json=env.signed(request_id="find_me")).json()
    env.client.post("/v1/actions", json=env.signed(amount=3))
    env.gateway.evidence = Evidence("pending", "unconfirmed")
    env.client.post("/v1/actions", json=env.signed())
    result = env.client.get("/v1/history?limit=1").json()
    assert result["total"] == 3 and len(result["items"]) == 1
    assert (
        env.client.get("/v1/history?status=VERIFIED&q=find_me").json()["items"][0]["action_id"]
        == one["action_id"]
    )
    assert env.client.get("/v1/history?since=" + str(int(time.time()) + 100)).json()["total"] == 0
    assert env.client.get("/v1/history?since=100&until=1").status_code == 422
    assert env.client.get("/v1/history?status=HACKED").status_code == 422
    csv = env.client.get("/v1/history/export?status=VERIFIED").text
    assert "'=formula" in csv and "find_me" not in csv
    analytics = env.client.get("/v1/analytics?days=7").json()
    assert (
        analytics["counts"]["VERIFIED"]
        == analytics["counts"]["REJECTED"]
        == analytics["counts"]["PENDING"]
        == 1
    )
    assert analytics["verified_lamports"] == 10_000_000 and len(analytics["daily"]) == 7
    assert analytics["success_rate"] == 100 and analytics["reliability_score"] is None


def test_notifications_read_state_and_new_outcomes(env):
    env.client.post("/v1/actions", json=env.signed())
    assert env.client.get("/v1/notifications").json()["unread"] == 1
    assert env.client.post("/v1/notifications/read").status_code == 200
    assert env.client.get("/v1/notifications").json()["unread"] == 0
    env.client.post("/v1/actions", json=env.signed(amount=3))
    notifications = env.client.get("/v1/notifications").json()
    assert notifications["unread"] == 1 and len(notifications["items"]) == 2


def test_reliability_formula_does_not_reward_rejections_or_volume():
    def row(status, amount=0.01):
        return {
            "status": status,
            "request": json.dumps({"params": {"amount": amount}}),
            "created_at": 10,
            "completed_at": 12,
        }

    perfect = [row("VERIFIED") for _ in range(5)]
    base = metrics(perfect)
    assert base["reliability_score"] == 56.6
    augmented = metrics(perfect + [row("REJECTED", 100) for _ in range(20)] + [row("PENDING")])
    assert augmented["reliability_score"] == base["reliability_score"]
    assert metrics(perfect + [row("FAILED")])["reliability_score"] < base["reliability_score"]
    assert metrics([row("VERIFIED", 100) for _ in range(5)])["reliability_score"] == base["reliability_score"]


def test_public_verifier_never_uses_old_success_when_rpc_unavailable(env):
    action = env.client.post("/v1/actions", json=env.signed()).json()
    publish(env)
    env.gateway.evidence = Evidence("unavailable", "offline")
    result = env.client.get("/v1/public/receipts/" + action["receipt_id"] + "/verify").json()
    assert not result["valid"] and result["evidence_valid"] is None and result["signature_valid"]
