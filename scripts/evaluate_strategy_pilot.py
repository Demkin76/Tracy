"""Exercise the real onboarding/replay API in a disposable local database.

Downloads public Binance candles, never sends exchange orders or uses production
credentials. No test fixtures or synthetic prices. An optional saved snapshot
allows an offline rerun against exactly the same exchange observations.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.crypto.hashing import digest
from backend.main import create_app
from backend.market_data.provider import provenance
from backend.strategies.plans import AgentPlan
from backend.trading.adapters import run_backtest
from sdk.poa.signing import generate_keypair


def compact(metrics):
    return {k: v for k, v in metrics.items() if k not in ("equity_curve", "realized_by_trade")}


def call(client, method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Previously saved market-data.json; no network fetch")
    parser.add_argument("--output", type=Path, required=True, help="A new output directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    candidates = json.loads((ROOT / "experiments/strategy-pilot/candidates.json").read_text())
    candidates = [AgentPlan.model_validate(c).model_dump() for c in candidates]
    (args.output / "candidates.json").write_text(json.dumps(candidates, indent=2))
    with TemporaryDirectory(prefix="tracy-strategy-pilot-") as temporary:
        folder = Path(temporary)
        settings = Settings(
            _env_file=None,
            environment="development", cookie_secure=False,
            allowed_hosts=["testserver"], signup_enabled=True, devnet_enabled=False,
            signing_seed=generate_keypair()["private_seed"],
            execution_wallet_seed=generate_keypair()["private_seed"],
            database_path=folder / "pilot.sqlite3", reconciler_enabled=False,
            copilot_provider="reference", control_credentials_path=folder / "credentials.json",
            control_resources_path=folder / "resources.json",
        )
        app = create_app(settings)
        with TestClient(app) as client:
            user = call(client, "POST", "/v1/auth/signup", json={
                "email": "pilot@example.test", "password": secrets.token_urlsafe(32), "name": "Local pilot",
            })
            client.headers["X-CSRF-Token"] = user["csrf_token"]
            market = app.state.strategies.market_data
            if args.snapshot:
                snapshot = json.loads(args.snapshot.read_text())
                snapshot_id = snapshot.pop("snapshot_id")
                assert digest(snapshot) == snapshot_id, "Snapshot integrity mismatch"
                assert snapshot["provider"] == "Binance Spot" and snapshot["synthetic"] is False
                assert snapshot["market"] == "BTC/USDC" and snapshot["timeframe"] == "1h"
                assert len(snapshot["bars"]) == 384
                snapshot = market.save(snapshot, "pilot-import:" + snapshot_id)
            else:
                snapshot = market.window("BTC/USDC", "1h", 384)
            (args.output / "market-data.json").write_text(json.dumps(snapshot, indent=2))

            # Pin all three plans to the same real snapshot, even across the hour
            # boundary. The application has no user-facing as-of selector yet.
            def pinned_window(symbol, timeframe, count=96, start=None):
                assert (symbol, timeframe, count, start) == ("BTC/USDC", "1h", 384, None)
                return deepcopy(snapshot)

            market.window = pinned_window
            report = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "mode": "historical_replay_not_forward_paper",
                "market_data": provenance(snapshot), "candidates_hash": digest(candidates),
                "assumptions": "Signals from previous closes; fills at current close with 10 bps fee and 10 bps slippage per side. No order-book simulation. No parameter optimization.",
                "cash_control_pnl_usdc": 0,
                "results": [],
            }
            for candidate in candidates:
                plan = call(client, "POST", "/v1/agent-plans", json=candidate)
                assert plan["report"]["ready"] and plan["report"]["passed"] == 12
                deployed = call(client, "POST", "/v1/agent-plans/" + plan["plan_id"] + "/deploy",
                                json={"reviewed_hash": plan["review_hash"], "acknowledged": True})
                sid = deployed["strategy_id"]
                path = "/v1/strategies/" + sid
                result = {"name": candidate["name"], "guardrails": plan["report"]["checks"],
                          "backtests": [{"market_data": s["market_data"], "metrics": compact(s["metrics"])}
                                        for s in plan["report"]["simulations"]],
                          "replay_market_data": plan["report"]["replay_market_data"], "checkpoints": []}
                step = 0
                for target in (24, 48, 72, 96):
                    advanced = call(client, "POST", path + "/advance", json={"expected_step": step, "steps": target - step})
                    step = advanced["step"]
                    detail = call(client, "GET", path)
                    metrics = compact(detail["performance"]["live"])
                    # Also expose a conservative estimated closing-cost mark so
                    # open positions don't get a free exit in the 24-bar ranking.
                    config = candidate["strategy_config"]
                    close_cost = metrics["position_value"] * (1 - (1 - config["slippage_bps"] / 10000) * (1 - config["fee_bps"] / 10000))
                    result["checkpoints"].append({"step": step, "status": detail["status"],
                        "metrics": metrics, "pnl_after_estimated_exit_cost": round(metrics["pnl"] - close_cost, 6),
                        "verified_fills": detail["performance"]["verified_trades"],
                        "health": detail["health"]})
                    if step != target or detail["status"] == "PAUSED":
                        result["stopped_early"] = True
                        break
                trades = call(client, "GET", path + "/trades", params={"limit": 200})["items"]
                proofs = [call(client, "GET", "/v1/trades/" + t["trade_id"] + "/proof")["checks"] for t in trades]
                assert all(p["valid"] and not p["on_chain"] for p in proofs)
                result["proof_checks"] = proofs
                result["intents"] = call(client, "GET", path + "/intents")
                result["trades"] = trades
                stressed = deepcopy(candidate)
                stressed.update(agent_id="pilot", strategy_id="pilot", version=1)
                stressed["strategy_config"].update(fee_bps=20, slippage_bps=20)
                result["doubled_cost_baseline_without_guardrails"] = compact(
                    run_backtest(stressed, snapshot["bars"][288:])["metrics"])
                report["results"].append(result)
                first, last = result["checkpoints"][0], result["checkpoints"][-1]
                print(candidate["name"], "checks=12/12", "24-bar PnL=", first["metrics"]["pnl"],
                      "final step=", last["step"], "PnL=", last["metrics"]["pnl"], "verified fills=", len(proofs))
            (args.output / "report.json").write_text(json.dumps(report, indent=2))
            print("Report:", args.output.resolve() / "report.json")


if __name__ == "__main__":
    main()
