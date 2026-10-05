import json

from fastapi import HTTPException

from backend.market_data.service import regime
from backend.performance.metrics import calculate


class PerformanceService:
    def __init__(self, strategies):
        self.strategies = strategies

    def snapshot(self, conn, strategy):
        sid, version = strategy["strategy_id"], strategy["version"]
        deployment = conn.execute(
            "SELECT * FROM trading_deployments WHERE strategy_id=? AND strategy_version=?", (sid, version)
        ).fetchone()
        test = (
            conn.execute(
                "SELECT * FROM strategy_tests WHERE test_id=?", (deployment["baseline_test_id"],)
            ).fetchone()
            if deployment
            else conn.execute(
                "SELECT * FROM strategy_tests WHERE strategy_id=? AND strategy_version=? ORDER BY started_at DESC,rowid DESC LIMIT 1",
                (sid, version),
            ).fetchone()
        )
        reference = json.loads(test["body"]) if test else None
        trades, marks = [], []
        all_count = 0
        if deployment:
            rows = conn.execute(
                "SELECT f.body,r.body AS receipt FROM paper_fills f LEFT JOIN trading_receipts r ON r.trade_id=f.trade_id WHERE f.deployment_id=? ORDER BY f.rowid",
                (deployment["deployment_id"],),
            ).fetchall()
            all_count = len(rows)
            for row in rows:
                fill = json.loads(row["body"])
                if (
                    row["receipt"]
                    and self.strategies.trading.crypto_valid(json.loads(row["receipt"]))
                    and json.loads(row["receipt"])["trade"] == fill
                ):
                    trades.append(fill)
            marks = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT body FROM trading_marks WHERE deployment_id=? ORDER BY step",
                    (deployment["deployment_id"],),
                )
            ]
        if len(trades) != all_count:
            raise HTTPException(
                409, "Trading evidence is incomplete or invalid; performance metrics are withheld"
            )
        live = calculate(trades, strategy["starting_capital"], marks)
        baseline = reference["metrics"] if reference else None
        has_live = bool(trades)
        gap = round(live["return_pct"] - baseline["return_pct"], 6) if baseline and has_live else None
        market_regime = regime(
            reference["market_context"] if reference else None, marks[-1] if marks else None
        )
        return {
            "strategy_id": sid,
            "strategy_version": version,
            "mode": "paper",
            "backtest": baseline,
            "live": live,
            "backtest_return": baseline["return_pct"] if baseline else None,
            "live_return": live["return_pct"] if has_live else None,
            "performance_gap": gap,
            "gap_unit": "percentage_points",
            "baseline_test_id": test["test_id"] if test else None,
            "verified_trades": len(trades),
            "execution_fidelity": 100 * len(trades) / all_count if all_count else 100,
            "track_record_start": trades[0]["timestamp"] if trades else None,
            "track_record_end": trades[-1]["timestamp"] if trades else None,
            "regime": market_regime,
            "comparison_note": "Different synthetic periods, cumulative unannualized returns. Not an apples-to-apples forecast.",
            "deployment": {
                k: deployment[k]
                for k in (
                    "deployment_id",
                    "strategy_version",
                    "status",
                    "step",
                    "created_at",
                    "baseline_test_id",
                    "runner_public_key",
                )
            }
            if deployment
            else None,
        }
