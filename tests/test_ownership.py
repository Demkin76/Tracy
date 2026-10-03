from fastapi.testclient import TestClient

from backend.auth.service import token_hash


def signup(client, email="other@example.test"):
    result = client.post(
        "/v1/auth/signup", json={"email": email, "password": "safe-long-password", "name": "Other owner"}
    )
    assert result.status_code == 201, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result.json()


def test_owner_isolation_every_resource(env):
    action = env.client.post("/v1/actions", json=env.signed()).json()
    aid, rid = action["action_id"], action["receipt_id"]
    with TestClient(env.app) as other:
        signup(other)
        assert other.get("/v1/agents").json()["items"] == []
        for path in [
            "/agents/agent_test",
            "/agents/agent_test/actions",
            "/agents/agent_test/policy/versions",
            f"/agents/agent_test/requests/{action['request_id']}",
            f"/actions/{aid}",
            f"/receipts/{rid}",
            f"/receipts/{rid}/verify",
            f"/receipts/{rid}/chain",
        ]:
            assert other.get("/v1" + path).status_code == 404, path
        for method, path, payload in [
            ("PATCH", "/agents/agent_test", {"name": "Stolen", "description": ""}),
            ("POST", "/agents/agent_test/status", {"active": False}),
            (
                "PUT",
                "/agents/agent_test/policy",
                {"expected_version": 1, "policy": env.registration["policy"]},
            ),
            ("POST", f"/actions/{aid}/reconcile", {}),
        ]:
            assert other.request(method, "/v1" + path, json=payload).status_code == 404
        key_id = env.client.get("/v1/account/api-keys").json()["items"][0]["key_id"]
        assert other.delete("/v1/account/api-keys/" + key_id).status_code == 404
        owned = {**env.registration, "agent_id": "agent_other"}
        assert other.post("/v1/agents", json=owned).status_code == 201
        assert len(other.get("/v1/agents").json()["items"]) == 1
    assert len(env.client.get("/v1/agents").json()["items"]) == 1
    assert env.client.get("/v1/agents/agent_test").json()["active"]


def test_sessions_csrf_logout_and_password_storage(env):
    with TestClient(env.app) as client:
        r = signup(client, "Mixed@Example.Test")
        assert r["user"]["email"] == "mixed@example.test"
        assert "password" not in str(r["user"])
        raw = client.cookies.get("tracy_session")
        with env.db.connect() as conn:
            stored = conn.execute(
                "SELECT password_hash FROM users WHERE user_id=?", (r["user"]["user_id"],)
            ).fetchone()[0]
            tokens = [x[0] for x in conn.execute("SELECT token_hash FROM sessions")]
        assert stored.startswith("pbkdf2_sha256$600000$") and "safe-long-password" not in stored
        assert raw not in tokens and token_hash(raw) in tokens
        assert client.get("/v1/auth/me").status_code == 200
        assert (
            client.post("/v1/agents", json=env.registration, headers={"X-CSRF-Token": ""}).status_code == 403
        )
        assert client.post("/v1/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/v1/auth/logout").status_code == 200
        assert client.get("/v1/auth/me").status_code == 401
        client.cookies.set("tracy_session", raw)
        assert client.get("/v1/auth/me").status_code == 401
        assert (
            client.post(
                "/v1/auth/login", json={"email": "mixed@example.test", "password": "incorrect-password"}
            ).status_code
            == 401
        )
        response = client.post(
            "/v1/auth/login", json={"email": "MIXED@example.test", "password": "safe-long-password"}
        )
        assert response.status_code == 200
        assert (
            "HttpOnly" in response.headers["set-cookie"]
            and "SameSite=strict" in response.headers["set-cookie"]
        )
        assert response.json()["csrf_token"] != r["csrf_token"]


def test_personal_key_revocation_expiry_and_no_admin_bypass(env):
    with TestClient(env.app) as client:
        signup(client)
        result = client.post("/v1/account/api-keys", json={"name": "Bot"}).json()
        token = result["token"]
        assert token not in str(client.get("/v1/account/api-keys").json())
        client.cookies.clear()
        client.headers["Authorization"] = "Bearer " + token
        assert client.get("/v1/agents").status_code == 200
        assert client.delete("/v1/account/api-keys/" + result["key_id"]).status_code == 200
        assert client.get("/v1/agents").status_code == 401
        client.headers["Authorization"] = "Bearer test-admin-token-long-enough"
        assert client.post("/v1/agents", json=env.registration).status_code == 401
    with env.db.connect(write=True) as conn:
        conn.execute("UPDATE api_keys SET expires_at=0")
    assert env.client.get("/v1/agents").status_code == 401


def test_session_expiry_and_login_throttle(env):
    with TestClient(env.app) as client:
        signup(client)
        with env.db.connect(write=True) as conn:
            conn.execute("UPDATE sessions SET expires_at=0")
        assert client.get("/v1/auth/me").status_code == 401
        for _ in range(12):
            assert (
                client.post(
                    "/v1/auth/login", json={"email": "nobody@example.test", "password": "wrong-password"}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/v1/auth/login", json={"email": "nobody@example.test", "password": "wrong-password"}
            ).status_code
            == 429
        )


def test_public_signed_request_needs_no_owner_token(env):
    with TestClient(env.app) as client:
        assert client.get("/v1/agents").status_code == 401
        assert client.post("/v1/actions", json=env.signed()).json()["status"] == "VERIFIED"
        assert client.get("/v1/agents/agent_test/actions").status_code == 401
