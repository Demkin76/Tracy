"""Opt-in acceptance check against actual exchange data and the running Tracy API."""

import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from backend.trading.verify import verify_chain


def main():
    credentials = json.loads(Path("data/tracy-owner.json").read_text())
    base = os.environ.get("TRACY_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=base, timeout=90) as client:
        login = client.post("/v1/auth/login", json={k: credentials[k] for k in ("email", "password")})
        login.raise_for_status()
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        config = client.get("/v1/config").json()
        plan = client.post(
            "/v1/agent-plans",
            json={
                "name": "Real-data acceptance " + uuid4().hex[:6],
                "goal": "Verify the full lifecycle using recorded SOL/USDC exchange prices",
                "strategy_config": {"runner": "buy_hold", "allocation_pct": 10},
                "guardrails": {"max_daily_loss": 100, "max_drawdown": 100},
            },
        )
        plan.raise_for_status()
        plan = plan.json()
        assert plan["report"]["ready"]
        assert plan["report"]["market_data"]["provider"] == "Binance Spot"
        assert not plan["report"]["market_data"]["synthetic"]
        assert all(
            not bar["synthetic"] for run in plan["report"]["simulations"] for bar in run["market_context"]
        )
        deployment = client.post(
            "/v1/agent-plans/" + plan["plan_id"] + "/deploy",
            json={"reviewed_hash": plan["review_hash"], "acknowledged": True},
        )
        deployment.raise_for_status()
        sid = deployment.json()["strategy_id"]
        step = 0
        while step < 96:
            response = client.post(
                "/v1/strategies/" + sid + "/advance", json={"expected_step": step, "steps": 24}
            )
            response.raise_for_status()
            new_step = response.json()["step"]
            if new_step == step:
                raise RuntimeError("Acceptance replay did not progress")
            step = new_step
        detail = client.get("/v1/strategies/" + sid).json()
        trades = client.get("/v1/strategies/" + sid + "/trades").json()["items"]
        assert len(trades) >= 2
        proof = client.get("/v1/trades/" + trades[-1]["trade_id"] + "/proof").json()
        assert proof["checks"]["valid"] and proof["checks"]["market_data_matches"]
        assert verify_chain(proof["chain"], config["poa_public_key"])
        report = {
            "passed": True,
            "strategy_id": sid,
            "plan_id": plan["plan_id"],
            "provider": plan["report"]["market_data"],
            "checks": plan["report"]["checks"],
            "backtests": [
                {"period": s["market_data"], "metrics": s["metrics"]} for s in plan["report"]["simulations"]
            ],
            "paper_replay": detail["performance"],
            "verified_fills": len(trades),
            "proof_checks": proof["checks"],
            "note": "Actual exchange candles; paper fills only. No exchange orders were submitted.",
        }
        Path("data/real-market-acceptance.json").write_text(json.dumps(report, indent=2))
        print(
            json.dumps(
                {
                    "passed": True,
                    "verified_fills": len(trades),
                    "strategy_id": sid,
                    "report": "data/real-market-acceptance.json",
                }
            )
        )


if __name__ == "__main__":
    main()
