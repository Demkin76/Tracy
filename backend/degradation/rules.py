def assess(live, baseline, guardrails, fidelity, gap):
    reasons = []
    severity = 0
    n = live["closed_trade_count"]
    if live["max_drawdown"] >= guardrails["max_drawdown"]:
        reasons.append(
            {
                "kind": "drawdown_threshold_exceeded",
                "severity": "CRITICAL",
                "message": f"Drawdown {live['max_drawdown']:.2f}% reached the {guardrails['max_drawdown']:.2f}% limit.",
            }
        )
        severity = 3
    if n >= 5 and gap is not None and gap < -5:
        level = 2 if gap < -10 else 1
        reasons.append(
            {
                "kind": "backtest_live_gap_increased",
                "severity": "DEGRADED" if level == 2 else "WATCH",
                "message": f"Paper live return trails the selected backtest by {-gap:.2f} percentage points.",
            }
        )
        severity = max(severity, level)
    if n >= 5 and baseline and baseline.get("win_rate") is not None and live["recent_win_rate"] is not None:
        drop = baseline["win_rate"] - live["recent_win_rate"]
        if drop > 15:
            level = 2 if drop > 25 else 1
            reasons.append(
                {
                    "kind": "win_rate_dropped",
                    "severity": "DEGRADED" if level == 2 else "WATCH",
                    "message": f"Win rate fell {drop:.1f}pp versus backtest over the last {live['recent_closed_count']} closed trades (up to 30).",
                }
            )
            severity = max(severity, level)
    if n >= 5 and live["rolling_return"] is not None and live["rolling_return"] < -2:
        reasons.append(
            {
                "kind": "performance_degraded",
                "severity": "WATCH",
                "message": f"Return over the latest 30 ledger observations is {live['rolling_return']:.2f}%.",
            }
        )
        severity = max(severity, 1)
    if live["trade_count"] and fidelity < 100:
        reasons.append(
            {
                "kind": "execution_fidelity",
                "severity": "CRITICAL",
                "message": "One or more fills have no valid matching proof.",
            }
        )
        severity = 3
    if (
        baseline
        and live["average_slippage_bps"] is not None
        and live["average_slippage_bps"] > max(20, (baseline.get("average_slippage_bps") or 0) * 2)
    ):
        reasons.append(
            {
                "kind": "slippage_increased",
                "severity": "WATCH",
                "message": "Observed slippage exceeds the backtest reference.",
            }
        )
        severity = max(severity, 1)

    def clamp(x):
        return max(0, min(100, x))

    components = {
        "live_performance": {
            "weight": 0.30,
            "score": clamp(50 + live["return_pct"] * 5),
            "formula": "clamp(50 + live_return_pct * 5, 0, 100)",
        },
        "drawdown": {
            "weight": 0.25,
            "score": clamp(100 * (1 - live["max_drawdown"] / guardrails["max_drawdown"])),
            "formula": "clamp(100 * (1 - max_drawdown / policy_max_drawdown), 0, 100)",
        },
        "backtest_live_gap": {
            "weight": 0.20,
            "score": clamp(100 + min(0, gap or 0) * 4),
            "formula": "clamp(100 + min(0, gap_pp) * 4, 0, 100)",
        },
        "execution_fidelity": {
            "weight": 0.15,
            "score": fidelity,
            "formula": "100 * verified_fills / all_fills",
        },
        "recent_consistency": {
            "weight": 0.10,
            "score": live["recent_win_rate"] or 0,
            "formula": "winning exits / last min(30, closed exits) * 100",
        },
    }
    sufficient = n >= 5 and baseline is not None
    return {
        "status": ["HEALTHY", "WATCH", "DEGRADED", "CRITICAL"][severity]
        if sufficient or severity
        else "WATCH",
        "score": round(sum(c["score"] * c["weight"] for c in components.values())) if sufficient else None,
        "components": components,
        "reasons": reasons,
        "sample_size": n,
        "minimum_sample": 5,
        "confidence": "Observed paper sample"
        if sufficient
        else "Insufficient sample: need 5 closed trades and a backtest",
        "formula_version": "tracy-health/1",
        "note": "Diagnostic score, not investment advice or a prediction.",
    }
