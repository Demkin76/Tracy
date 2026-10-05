"""Prepare v3 synthetic trading scenarios through authenticated APIs. No external trades."""

import json
from pathlib import Path

import httpx

from sdk.poa.signing import generate_keypair

ROOT = Path(__file__).resolve().parents[1]


def main():
    credentials = json.loads((ROOT / "data/tracy-owner.json").read_text(encoding="utf-8"))
    report = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=90) as client:
        response = client.post("/v1/auth/login", json={k: credentials[k] for k in ("email", "password")})
        response.raise_for_status()
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        for aid, name, allocation, lookback in [
            ("tracy_v3_momentum", "SOL Momentum", 30, 3),
            ("tracy_v3_sentinel", "SOL Sentinel", 20, 5),
        ]:
            key_file = ROOT / ("data/" + aid + ".json")
            if key_file.exists():
                keys = json.loads(key_file.read_text(encoding="utf-8"))
            else:
                keys = {"agent_id": aid, **generate_keypair()}
                key_file.write_text(json.dumps(keys, indent=2), encoding="utf-8")
            exists = client.get("/v1/agents/" + aid)
            if exists.status_code == 404:
                r = client.post(
                    "/v2/agents",
                    json={
                        "agent_id": aid,
                        "name": name + " agent",
                        "public_key": keys["public_key"],
                        "description": "Hosted synthetic paper-trading demonstration. No real funds.",
                    },
                )
                r.raise_for_status()
            else:
                exists.raise_for_status()
                if exists.json()["public_key"] != keys["public_key"]:
                    raise RuntimeError("Demo identity key does not match the existing agent")
            existing = client.get("/v1/strategies").json()["items"]
            s = next((s for s in existing if s["agent_id"] == aid and s["name"] == name), None)
            if s is None:
                r = client.post(
                    "/v1/strategies",
                    json={
                        "agent_id": aid,
                        "name": name,
                        "description": "A configured momentum strategy evaluated on reproducible synthetic periods. Paper results only.",
                        "strategy_config": {
                            "runner": "momentum",
                            "allocation_pct": allocation,
                            "lookback": lookback,
                        },
                        "guardrails": {
                            "max_trade_size": 5000,
                            "max_position_size": 7000,
                            "max_daily_loss": 8,
                            "max_drawdown": 25,
                            "human_approval_above": 5000,
                        },
                    },
                )
                r.raise_for_status()
                s = r.json()
            sid = s["strategy_id"]
            if not client.get("/v1/strategies/" + sid + "/tests").json()["items"]:
                r = client.post("/v1/strategies/" + sid + "/tests", json={"dataset": "trending"})
                r.raise_for_status()
            s = client.get("/v1/strategies/" + sid).json()
            if not s["performance"]["deployment"]:
                r = client.post("/v1/strategies/" + sid + "/deploy", json={"expected_version": s["version"]})
                r.raise_for_status()
                s = r.json()
            step = s["performance"]["deployment"]["step"]
            while step < 72 and s["status"] in ("LIVE", "DEGRADED"):
                r = client.post(
                    "/v1/strategies/" + sid + "/advance",
                    json={"expected_step": step, "steps": min(24, 72 - step)},
                )
                r.raise_for_status()
                new_step = r.json()["step"]
                if new_step == step:
                    break
                step = new_step
                s = client.get("/v1/strategies/" + sid).json()
            r = client.put("/v1/strategies/" + sid + "/publication", json={"listed": True})
            r.raise_for_status()
            r = client.post("/v1/strategies/" + sid + "/probe")
            r.raise_for_status()
            report.append(
                {
                    "strategy_id": sid,
                    "agent_id": aid,
                    "name": name,
                    "version": s["version"],
                    "step": step,
                    "backtest_return": s["performance"]["backtest_return"],
                    "live_return": s["performance"]["live_return"],
                    "health": s["health"]["status"],
                    "score": s["health"]["score"],
                    "rejected_intent": r.json()["intent_id"],
                }
            )
    path = ROOT / "data/trading-demo.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
