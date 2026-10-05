import time
from uuid import uuid4

from backend.degradation.rules import assess
from backend.platform.service import record_event


class DegradationService:
    def __init__(self, strategies):
        self.strategies = strategies

    def alert(self, conn, strategy, kind, severity, message):
        existing = conn.execute(
            "SELECT 1 FROM degradation_alerts WHERE strategy_id=? AND version=? AND kind=? AND severity=? AND acknowledged=0 LIMIT 1",
            (strategy["strategy_id"], strategy["version"], kind, severity),
        ).fetchone()
        if existing:
            return
        before = conn.total_changes
        conn.execute(
            """INSERT OR IGNORE INTO degradation_alerts VALUES(?,?,?,?,?,?,?,0)""",
            (
                "alert_" + uuid4().hex,
                strategy["strategy_id"],
                strategy["version"],
                kind,
                severity,
                message,
                int(time.time()),
            ),
        )
        if conn.total_changes > before:
            record_event(conn, strategy["owner_id"], kind, strategy["strategy_id"])

    def evaluate(self, conn, strategy, snapshot, record=False):
        live = snapshot["live"]
        baseline = snapshot["backtest"]
        health = assess(
            live,
            baseline,
            strategy["guardrails"],
            snapshot["execution_fidelity"],
            snapshot["performance_gap"],
        )
        if record:
            for reason in health["reasons"]:
                self.alert(conn, strategy, reason["kind"], reason["severity"], reason["message"])
            if strategy["status"] in ("LIVE", "DEGRADED"):
                status = (
                    "PAUSED"
                    if health["status"] == "CRITICAL"
                    else "DEGRADED"
                    if health["status"] == "DEGRADED"
                    else "LIVE"
                )
                conn.execute(
                    "UPDATE strategies SET status=?,updated_at=? WHERE strategy_id=?",
                    (status, int(time.time()), strategy["strategy_id"]),
                )
                if status == "PAUSED":
                    conn.execute(
                        "UPDATE trading_deployments SET status='PAUSED' WHERE strategy_id=? AND strategy_version=?",
                        (strategy["strategy_id"], strategy["version"]),
                    )
                    self.alert(
                        conn,
                        strategy,
                        "strategy_paused",
                        "CRITICAL",
                        "Strategy automatically paused after a critical risk or evidence check.",
                    )
        return health
