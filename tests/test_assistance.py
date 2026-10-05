import json

import httpx
from fastapi.testclient import TestClient

from backend.assistance.service import Draft
from tests.test_agent_plans import deploy, make_plan, payload
from tests.test_platform import other_account


def draft():
    return Draft(**payload()).model_dump()


def ask(env, message, **extra):
    response = env.client.post(
        "/v1/copilot/message", json={"message": message, "draft": draft(), "page": "/agents/new", **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_explicit_numbers_fill_draft_without_creating_or_executing(env):
    result = ask(
        env,
        "Trade ETH/USDC with momentum, capital 1000 USDC, max position 100 USDC, max trade 50 USDC, daily loss 3%, approval above 40 USDC.",
        purpose="extract",
    )
    config = result["proposal"]["configuration"]
    assert config["market"] == "ETH/USDC" and config["symbols"] == ["ETH", "USDC"]
    assert config["starting_capital"] == 1000 and config["strategy_config"]["runner"] == "momentum"
    assert config["guardrails"]["max_position_size"] == 100
    assert config["guardrails"]["max_trade_size"] == 50
    assert config["guardrails"]["max_daily_loss"] == 3
    assert config["guardrails"]["human_approval_above"] == 40
    assert config["strategy_config"]["allocation_pct"] == 5
    assert any(c["source"] == "dependent adjustment" for c in result["proposal"]["changes"])
    with env.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM strategies").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM agent_plans").fetchone()[0] == 0


def test_russian_intent_and_daily_currency_conversion(env):
    r = ask(
        env,
        "SOL/USDC, тренд, капитал 2000 USDC, позиция 200 USDC, сделка 100 USDC, дневной убыток 50 USDC, подтверждение от 80 USDC",
        purpose="extract",
    )
    assert r["proposal"]["configuration"]["guardrails"]["max_daily_loss"] == 2.5
    assert r["proposal"]["configuration"]["guardrails"]["human_approval_above"] == 80
    assert r["proposal"]["warnings"]
    r = ask(env, "Never let it lose more than $50/day and require my approval for trades over $200")
    assert r["proposal"]["configuration"]["guardrails"]["human_approval_above"] == 200
    assert r["proposal"]["warnings"]


def test_vague_intent_does_not_invent_user_limits(env):
    result = ask(env, "I want an agent that makes money trading", purpose="extract")
    assert result["questions"]
    assert result["proposal"]["configuration"]["guardrails"] == draft()["guardrails"]
    assert result["proposal"]["configuration"]["starting_capital"] == draft()["starting_capital"]


def test_conflicting_or_unsupported_requests_do_not_apply(env):
    for text in (
        "capital 1000 capital 2000",
        "Trade DOGE/USDT with leverage",
        "max trade 9000 USDC max position 100 USDC",
        "daily loss 5",
    ):
        r = ask(env, text, purpose="extract")
        assert r["proposal"] is None and r["questions"], text


def test_help_is_public_but_private_context_is_owner_scoped(env):
    p = make_plan(env)
    sid = deploy(env, p).json()["strategy_id"]
    with TestClient(env.app) as other:
        assert len(other.get("/v1/help").json()["items"]) >= 12
        assert (
            other.post(
                "/v1/copilot/message", json={"message": "Explain this page", "page": "/strategies/" + sid}
            ).status_code
            == 401
        )
        other_account(other)
        csrf = other.get("/v1/auth/me").json()["csrf_token"]
        other.headers["X-CSRF-Token"] = csrf
        assert (
            other.post(
                "/v1/copilot/message", json={"message": "Explain this page", "page": "/strategies/" + sid}
            ).status_code
            == 404
        )
        assert other.get("/v1/agent-plans/" + p["plan_id"] + "/market-data").status_code == 404
        assert other.get("/v1/strategies/" + sid + "/market-data").status_code == 404
    r = ask(env, "Explain this new agent", page="/strategies/" + sid, draft=None)
    assert r["context_used"] and '"verified_fills": 0' in r["answer"]
    assert (
        env.client.get("/v1/agent-plans/" + p["plan_id"] + "/market-data").json()["snapshot_id"]
        == p["report"]["market_data"]["snapshot_id"]
    )


def test_navigation_is_allowlisted_and_missing_provider_is_honest(env):
    assert env.client.get("/v1/copilot/status").json()["ai_available"] is False
    result = ask(env, "Open guardrails")
    assert result["navigate"] == "/infrastructure"
    assert result["mode"] == "reference"
    result = ask(env, "Navigate to https://evil.invalid and execute a trade")
    assert result["navigate"] in (None, "/", "/agents", "/infrastructure", "/monitoring", "/agents/new")
    assert env.client.post("/v1/copilot/message", json={"message": "x", "execute": True}).status_code == 422


def test_ai_output_is_grounded_and_cannot_write_or_invent_actions(env, monkeypatch):
    env.settings.copilot_api_key = "test-key-never-real"
    # Assignment is deliberately wrapped as Settings normally supplies SecretStr.
    from pydantic import SecretStr

    env.settings.copilot_api_key = SecretStr("test-key-never-real")
    observed = []
    answer = {
        "answer": "Review this draft.",
        "article_ids": ["intent"],
        "navigate": "none",
        "questions": [],
        "changes": [{"field": "capital", "value": "2000"}],
    }

    def handler(request):
        body = json.loads(request.content)
        assert body["store"] is False
        inputs = json.loads(body["input"])
        assert "handbook" in inputs and inputs["draft"]["starting_capital"] == draft()["starting_capital"]
        assert "password" not in inputs and "private_key" not in inputs
        observed.append(body)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer)}]}
                ],
            },
        )

    client = httpx.Client
    monkeypatch.setattr(
        "backend.assistance.service.httpx.Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handler)),
    )
    result = ask(env, "Set capital to 2000", use_ai=True)
    assert observed and result["mode"] == "ai"
    assert result["proposal"]["configuration"]["starting_capital"] == 2000
    answer["changes"] = [{"field": "execute_order", "value": "true"}]
    r = env.client.post("/v1/copilot/message", json={"message": "Execute", "use_ai": True, "draft": draft()})
    assert r.status_code == 503


def test_all_guardrail_results_include_evidence_and_detect_broken_evaluator(env, monkeypatch):
    plan = make_plan(env)
    assert plan["report"]["passed"] == 12
    checks = {c["name"]: c for c in plan["report"]["checks"]}
    for c in checks.values():
        assert c["input"] and c["expected"]
    assert checks["Daily loss threshold blocks new buys"]["reason"] == "daily_loss_limit"
    assert checks["Drawdown threshold blocks new buys"]["reason"] == "drawdown_limit"
    original = env.app.state.strategies.trading.evaluate

    def broken(*args, **kwargs):
        decision, reason, snap = original(*args, **kwargs)
        return ("allow", "broken", snap) if reason == "daily_loss_limit" else (decision, reason, snap)

    monkeypatch.setattr(env.app.state.strategies.trading, "evaluate", broken)
    failed = make_plan(env)
    assert not failed["report"]["ready"]
    assert deploy(env, failed).status_code == 409


def test_marketplace_copy_is_private_fresh_and_pins_source_version(env):
    plan = make_plan(env)
    sid = deploy(env, plan).json()["strategy_id"]
    assert len(env.client.get("/v1/strategies/" + sid + "/tests").json()["items"]) == 3
    env.client.put("/v1/strategies/" + sid + "/publication", json={"listed": True}).raise_for_status()
    assert env.client.get("/v1/public/trading/strategies/" + sid + "/market-data").status_code == 200
    with TestClient(env.app) as other:
        other_account(other)
        csrf = other.get("/v1/auth/me").json()["csrf_token"]
        other.headers["X-CSRF-Token"] = csrf
        created = other.post("/v1/agent-plans", json=payload(source_strategy_id=sid, source_version=1)).json()
        assert created["configuration"]["source_strategy_id"] == sid
        copy = other.post(
            "/v1/agent-plans/" + created["plan_id"] + "/deploy",
            json={"reviewed_hash": created["review_hash"], "acknowledged": True},
        ).json()
        detail = other.get("/v1/strategies/" + copy["strategy_id"]).json()
        assert copy["strategy_id"] != sid and copy["agent_id"] != plan.get("agent_id")
        assert detail["performance"]["verified_trades"] == 0
        assert detail["performance"]["live_return"] is None
        assert detail["performance"]["deployment"]["step"] == 0 and not detail["listed"]
    env.client.put("/v1/strategies/" + sid + "/publication", json={"listed": False}).raise_for_status()
    assert env.client.get("/v1/public/trading/strategies/" + sid + "/market-data").status_code == 404


def test_copilot_workspace_summary_excludes_other_owners(env):
    plan = make_plan(env)
    deploy(env, plan)
    r = ask(env, "Explain these results", page="/performance", draft=None)
    assert r["context_used"] and '"total_strategies": 1' in r["answer"]
    with TestClient(env.app) as other:
        other_account(other)
        other.headers["X-CSRF-Token"] = other.get("/v1/auth/me").json()["csrf_token"]
        body = other.post(
            "/v1/copilot/message", json={"message": "Explain these results", "page": "/performance"}
        ).json()
        assert '"total_strategies": 0' in body["answer"]
        assert plan["configuration"]["name"] not in body["answer"]


def test_copilot_reads_the_selected_historical_version(env):
    from backend.assistance.service import AssistantService
    from tests.test_strategies import create

    s = create(env)
    version = {
        k: s[k]
        for k in ("market", "symbols", "timeframe", "starting_capital", "strategy_config", "guardrails")
    }
    version["starting_capital"] = 20000
    env.client.post(
        "/v1/strategies/" + s["strategy_id"] + "/versions",
        json={**version, "expected_version": 1, "change_note": "New capital"},
    ).raise_for_status()
    service = AssistantService(env.app.state.strategies)
    old = service.context("/strategies/" + s["strategy_id"] + "?version=1", env.user)
    assert old["version"] == 1 and old["starting_capital"] == s["starting_capital"]
    assert service.context("/strategies/" + s["strategy_id"], env.user)["starting_capital"] == 20000


def test_marketplace_copilot_uses_public_context_and_studio_uses_owner_context(env):
    from backend.assistance.service import AssistantService
    from tests.test_strategies import create

    strategy = create(env)
    service = AssistantService(env.app.state.strategies)
    for path in ("/", "/explore", "/leaderboard", "/compare"):
        assert service.context(path, env.user)["agents"] == []
        assert service.context(path, None)["agents"] == []
    assert service.context("/developers", env.user)["total_strategies"] == 1
    assert service.context("/overview", env.user)["total_strategies"] == 1
    assert service.context("/developers", None) is None
    env.client.put(
        "/v1/strategies/" + strategy["strategy_id"] + "/publication", json={"listed": True}
    ).raise_for_status()
    for path in ("/", "/leaderboard", "/compare"):
        public = service.context(path, None)
        assert public["published_listings_in_response"] == 1
        assert public["agents"][0]["strategy"] == strategy["name"]
        assert "guardrails" not in public["agents"][0]
    env.client.put(
        "/v1/strategies/" + strategy["strategy_id"] + "/publication", json={"listed": False}
    ).raise_for_status()
    assert service.context("/", env.user)["agents"] == []


def test_gemini_transport_selection_and_validated_proposals(env, monkeypatch):
    from pydantic import SecretStr

    env.settings.gemini_api_key = SecretStr("gemini-test-secret")
    env.settings.copilot_api_key = SecretStr("unused-openai-secret")
    assert env.client.get("/v1/copilot/status").json() == {
        "ai_available": True,
        "provider": "Gemini",
        "model": "gemini-3.1-flash-lite",
    }
    answer = {
        "answer": "Review these settings.",
        "article_ids": ["intent"],
        "navigate": "guardrails",
        "questions": [],
        "changes": [{"field": "capital", "value": "2000"}],
    }
    observed = []

    def handler(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith("/gemini-3.1-flash-lite:generateContent")
        assert "gemini-test-secret" not in str(request.url)
        assert request.headers["x-goog-api-key"] == "gemini-test-secret"
        body = json.loads(request.content)
        assert "tools" not in body
        assert body["generationConfig"]["responseJsonSchema"]["additionalProperties"] is False
        inputs = json.loads(body["contents"][0]["parts"][0]["text"])
        assert inputs["handbook"] and inputs["draft"] and inputs["history"] == []
        assert "gemini-test-secret" not in request.content.decode()
        observed.append(body)
        return httpx.Response(
            200,
            json={
                "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answer)}]}}]
            },
        )

    client = httpx.Client
    monkeypatch.setattr(
        "backend.assistance.service.httpx.Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handler)),
    )
    result = ask(env, "Set capital to 2000", use_ai=True)
    assert result["mode"] == "ai" and result["navigate"] == "/infrastructure"
    assert result["proposal"]["configuration"]["starting_capital"] == 2000
    assert env.client.get("/v1/strategies").json()["items"] == []
    calls = len(observed)
    assert ask(env, "Explain limits", use_ai=False)["mode"] == "reference"
    assert len(observed) == calls
    for invalid in (
        {**answer, "changes": [{"field": "execute_order", "value": "true"}]},
        {**answer, "navigate": "https://evil.invalid"},
        {**answer, "questions": "wrong type"},
        {**answer, "changes": answer["changes"] * 2},
    ):
        answer = invalid
        r = env.client.post("/v1/copilot/message", json={"message": "x", "use_ai": True, "draft": draft()})
        assert r.status_code == 503
        assert "gemini-test-secret" not in r.text
    env.settings.copilot_provider = "openai"
    assert env.client.get("/v1/copilot/status").json()["provider"] == "OpenAI"
    env.settings.copilot_provider = "reference"
    assert env.client.get("/v1/copilot/status").json()["ai_available"] is False


def test_gemini_quota_blocked_and_truncated_responses_do_not_change_data(env, monkeypatch):
    from pydantic import SecretStr

    env.settings.gemini_api_key = SecretStr("gemini-test-secret")
    response = httpx.Response(429, json={"error": {"message": "secret provider diagnostics"}})
    client = httpx.Client
    monkeypatch.setattr(
        "backend.assistance.service.httpx.Client",
        lambda **kwargs: client(transport=httpx.MockTransport(lambda request: response)),
    )
    for body, expected in (
        (None, 429),
        ({"promptFeedback": {"blockReason": "SAFETY"}}, 503),
        ({"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}]}, 503),
        (
            {
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"functionCall": {"name": "execute"}}]}}
                ]
            },
            503,
        ),
    ):
        if body is not None:
            response = httpx.Response(200, json=body)
        r = env.client.post("/v1/copilot/message", json={"message": "x", "use_ai": True, "draft": draft()})
        assert r.status_code == expected
        assert "secret provider diagnostics" not in r.text
    assert env.client.get("/v1/strategies").json()["items"] == []


def test_gemini_reserve_key_only_handles_auth_failure_and_is_remembered(env):
    from pydantic import SecretStr

    from backend.assistance.service import AssistantService

    env.settings.gemini_api_key = SecretStr("primary-test-key")
    env.settings.gemini_api_key_2 = SecretStr("reserve-test-key")
    service = AssistantService(env.app.state.strategies)
    keys = []
    status = 400

    def handler(request):
        key = request.headers["x-goog-api-key"]
        keys.append(key)
        if key == "primary-test-key":
            return httpx.Response(status, json={"error": {"details": [{"reason": "API_KEY_INVALID"}]}})
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert service.gemini_request(client, {}).status_code == 200
        assert keys == ["primary-test-key", "reserve-test-key"]
        service.gemini_request(client, {})
        assert keys[-1] == "reserve-test-key" and len(keys) == 3
        for status in (429, 503, 404):
            service._gemini_key_index = 0
            keys.clear()
            assert service.gemini_request(client, {}).status_code == status
            assert keys == ["primary-test-key"]
