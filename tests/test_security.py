from fastapi.testclient import TestClient

from backend.auth.service import token_hash


def test_read_only_api_key_cannot_change_or_issue_access(env):
    r = env.client.post("/v1/account/api-keys", json={"name": "Observer", "scope": "read"}).json()
    headers = {"Authorization": "Bearer " + r["token"]}
    assert env.client.get("/v1/agents", headers=headers).status_code == 200
    assert env.client.get("/v1/analytics", headers=headers).status_code == 200
    for url, payload in [
        ("/agents/agent_test/status", {"active": False}),
        ("/account/api-keys", {"name": "Escalate"}),
    ]:
        assert env.client.post("/v1" + url, json=payload, headers=headers).status_code == 403
    keys = env.client.get("/v1/account/api-keys").json()["items"]
    assert next(k for k in keys if k["key_id"] == r["key_id"])["last_used_at"] is not None


def test_password_change_revokes_all_sessions_and_keys(env):
    bad = env.client.post(
        "/v1/account/password", json={"current_password": "wrong", "new_password": "another-long-password"}
    )
    assert bad.status_code == 401
    good = env.client.post(
        "/v1/account/password",
        json={"current_password": "long-test-password", "new_password": "another-long-password"},
    )
    assert good.status_code == 200
    assert env.client.get("/v1/agents").status_code == 401
    with TestClient(env.app) as client:
        assert (
            client.post(
                "/v1/auth/login", json={"email": "owner@example.test", "password": "long-test-password"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/v1/auth/login", json={"email": "owner@example.test", "password": "another-long-password"}
            ).status_code
            == 200
        )


def test_recovery_code_rotates_is_hashed_and_consumed_once(env):
    def issue():
        r = env.client.post("/v1/account/recovery-code", json={"current_password": "long-test-password"})
        assert r.status_code == 200
        return r.json()["recovery_code"]

    first, second = issue(), issue()
    with env.db.connect() as conn:
        stored = conn.execute(
            "SELECT recovery_hash FROM users WHERE user_id=?", (env.user["user_id"],)
        ).fetchone()[0]
    assert stored == token_hash(second) and stored != second
    with TestClient(env.app) as guest:
        payload = {
            "email": "owner@example.test",
            "recovery_code": first,
            "new_password": "new-recovered-password",
        }
        assert guest.post("/v1/auth/recover", json=payload).status_code == 401
        payload["recovery_code"] = second
        assert guest.post("/v1/auth/recover", json=payload).status_code == 200
        assert guest.post("/v1/auth/recover", json=payload).status_code == 401
        assert (
            guest.post(
                "/v1/auth/login", json={"email": "owner@example.test", "password": "new-recovered-password"}
            ).status_code
            == 200
        )
    assert env.client.get("/v1/agents").status_code == 401


def test_security_events_do_not_contain_secrets(env):
    r = env.client.post("/v1/account/api-keys", json={"name": "Temporary"}).json()
    env.client.delete("/v1/account/api-keys/" + r["key_id"])
    env.client.post("/v1/account/recovery-code", json={"current_password": "long-test-password"})
    events = env.client.get("/v1/account/events").json()["items"]
    assert any(x["kind"] == "api_key_revoked" for x in events)
    assert r["token"] not in str(events) and "long-test-password" not in str(events)
