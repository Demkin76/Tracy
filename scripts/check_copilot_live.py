"""Opt-in Gemini acceptance against the running local app. Never prints credentials."""

import json
import os
from pathlib import Path

import httpx


def main():
    credentials = json.loads(Path("data/tracy-owner.json").read_text())
    base = os.environ.get("TRACY_URL", "http://127.0.0.1:8000")
    results = []
    with httpx.Client(base_url=base, timeout=60) as client:
        login = client.post("/v1/auth/login", json={k: credentials[k] for k in ("email", "password")})
        login.raise_for_status()
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        status = client.get("/v1/copilot/status").json()
        assert status["provider"] == "Gemini" and status["ai_available"], status
        print("Provider:", status["provider"], "Model:", status["model"], flush=True)
        before = client.get("/v1/strategies").json()["items"]
        from backend.assistance.service import Draft

        requests = [
            {
                "message": "Объясни коротко, что такое Replay next 24 candles и отправляются ли реальные ордера?",
                "page": "/help/replay",
            },
            {"message": "Открой leaderboard, где можно сравнить рейтинг агентов", "page": "/help/start"},
            {
                "message": "Хочу ETH/USDC, momentum, капитал 2000 USDC, максимальная позиция 200 USDC, сделка 100 USDC, дневной убыток 3%, подтверждение выше 80 USDC.",
                "page": "/agents/new",
                "purpose": "extract",
                "draft": Draft(name="Gemini acceptance draft", goal="Test a paper strategy").model_dump(),
            },
        ]
        for i, body in enumerate(requests):
            response = client.post("/v1/copilot/message", json={**body, "use_ai": True})
            if response.status_code != 200:
                print(
                    "Acceptance stopped; HTTP",
                    response.status_code,
                    response.json().get("detail"),
                    flush=True,
                )
                return 1
            result = response.json()
            assert result["mode"] == "ai"
            if i == 0:
                assert any("а" <= c.lower() <= "я" for c in result["answer"])
                assert result["proposal"] is None
            elif i == 1:
                assert result["navigate"] == "/leaderboard", result
            else:
                config = result["proposal"]["configuration"]
                assert config["market"] == "ETH/USDC" and config["starting_capital"] == 2000
                assert config["strategy_config"]["runner"] == "momentum"
                assert config["guardrails"]["max_position_size"] == 200
                assert config["guardrails"]["max_trade_size"] == 100
                assert config["guardrails"]["max_daily_loss"] == 3
                assert config["guardrails"]["human_approval_above"] == 80
            results.append(result)
            print("Passed scenario", i + 1, flush=True)
        after = client.get("/v1/strategies").json()["items"]
        assert [x["strategy_id"] for x in before] == [x["strategy_id"] for x in after]
        Path("data/gemini-acceptance.json").write_text(
            json.dumps({"status": status, "passed": True, "results": results}, ensure_ascii=False, indent=2)
        )
        print(
            "Passed: live Russian help, allowlisted navigation, validated draft extraction; no strategy created",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
