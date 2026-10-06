"""Bounded online learning, chronological observations and identical execution rules.

Beta counts describe observed profitable/unprofitable exits, NOT a calibrated
forecast. UCB explores only the explicit approved entry-filter arms in training.
Validation is frozen and cannot update either policy or posterior counts.
"""

import math
from copy import deepcopy

from backend.performance.metrics import calculate

ENGINE = "tracy-adaptive/1"


def arms(program):
    if program["kind"] in ("sma_cross", "ema_cross"):
        return [0.0, 5.0, 10.0]
    t = program["threshold_bps"]
    return [t, t * 0.5, t * 1.5]


def initial_state(blueprint):
    return {
        "schema": "tracy.agent-apr/1",
        "engine": ENGINE,
        "arms": [
            {"value": v, "alpha": 1, "beta": 1, "net_pnl": 0.0, "closed_trades": 0}
            for v in arms(blueprint["program"])
        ],
        "active_arm": 0,
        "observed_until": 0,
        "last_run_id": None,
        "note": "Beta(1,1) prior; net-positive exits increment alpha, other exits increment beta. Not a probability of future profit.",
    }


def choose(state):
    total = sum(a["closed_trades"] for a in state["arms"])
    return max(
        range(len(state["arms"])),
        key=lambda i: (
            state["arms"][i]["alpha"] / (state["arms"][i]["alpha"] + state["arms"][i]["beta"])
            + math.sqrt(2 * math.log(total + 2) / (state["arms"][i]["closed_trades"] + 1)),
            -i,
        ),
    )


def learn(state, arm, pnl):
    a = state["arms"][arm]
    a["alpha" if pnl > 0 else "beta"] += 1
    a["closed_trades"] += 1
    a["net_pnl"] = round(a["net_pnl"] + pnl, 8)


def new_account():
    return {"fills": [], "marks": [], "decisions": [], "entry_step": -1, "entry_arm": 0}


def signal(program, history, position, held, threshold):
    if program["kind"] in ("sma_cross", "ema_cross"):
        slow, fast = program["slow"], program["fast"]
        if len(history) < slow + 1:
            return None
        prices = [b["price"] for b in history]
        f, s = sum(prices[-fast:]) / fast, sum(prices[-slow:]) / slow
        pf, ps = sum(prices[-fast - 1 : -1]) / fast, sum(prices[-slow - 1 : -1]) / slow
        if program["kind"] == "ema_cross":

            def ema(values, length):
                current = values[0]
                alpha = 2 / (length + 1)
                for price in values[1:]:
                    current = alpha * price + (1 - alpha) * current
                return current

            f, s = ema(prices, fast), ema(prices, slow)
            pf, ps = ema(prices[:-1], fast), ema(prices[:-1], slow)
        if position and pf >= ps and f < s:
            return "SELL"
        if not position and pf <= ps and f > s and (f / s - 1) * 10000 >= threshold:
            return "BUY"
        return None
    if len(history) < program["lookback"]:
        return None
    move = history[-1]["price"] / history[-program["lookback"]]["price"] - 1
    momentum = program["kind"] == "momentum"
    if position:
        if held >= program["exit_after_bars"] or (
            move < -threshold / 10000 if momentum else move > threshold / 10000
        ):
            return "SELL"
    elif move > threshold / 10000 if momentum else move < -threshold / 10000:
        return "BUY"
    return None


def step(
    bp,
    account,
    state,
    history,
    bar,
    index,
    arm,
    training=False,
    force_exit=False,
    bid=None,
    ask=None,
    quote_sizes=None,
    explore=False,
):
    """Decision uses only history. bar price is an execution quote, not a signal.

    Backtests pass the next bar open; forward passes the current public bid/ask.
    Risk exits bypass entry notional caps and approval thresholds, but never sell
    more inventory or open a short. Authorization is explicit in strategy APR.
    """
    before = calculate(account["fills"], bp["capital"], account["marks"])
    g = bp["guardrails"]
    day = bar["timestamp"] // 86400 * 86400
    prior = [
        p["equity"] for p in before["equity_curve"] if p["timestamp"] is not None and p["timestamp"] < day
    ]
    day_open = prior[-1] if prior else bp["capital"]
    loss = max(0, (day_open - before["equity"]) / day_open * 100)
    risk = loss >= g["max_daily_loss"] or before["current_drawdown"] >= g["max_drawdown"]
    chosen = account["entry_arm"] if before["position_quantity"] else arm
    value = state["arms"][chosen]["value"]
    side = (
        "SELL"
        if before["position_quantity"] and (risk or force_exit)
        else signal(bp["program"], history, before["position_quantity"], index - account["entry_step"], value)
    )
    if force_exit and side == "BUY":
        side = None
    reason = "risk_exit" if risk and side == "SELL" else "end_of_run" if force_exit else "strategy_signal"
    if (
        side == "BUY"
        and state.get("schema") == "tracy.agent-apr/2"
        and state["apr"][chosen]["probability"] < 0.5
        and not explore
    ):
        side, reason = None, "attributed_probability_below_entry_floor"
    if side == "BUY" and risk:
        side, reason = None, "loss_limit_blocks_entry"
    if side:
        reference = (ask if side == "BUY" else bid) or bar["price"]
        price = reference * (1 + bp["slippage_bps"] / 10000 * (1 if side == "BUY" else -1))
        q = (
            round(before["cash"] * bp["allocation_pct"] / 100 / (price * (1 + bp["fee_bps"] / 10000)), 8)
            if side == "BUY"
            else before["position_quantity"]
        )
        if side == "BUY" and (
            q * price > min(g["max_trade_size"], g["max_position_size"], g["human_approval_above"]) or q <= 0
        ):
            reason, side = "entry_limit", None
        if side and quote_sizes and q > quote_sizes[side]:
            from fastapi import HTTPException

            raise HTTPException(503, "Top-of-book size is insufficient; no paper fill was invented")
        if side:
            fill = {
                "trade_id": "fill_" + str(len(account["fills"])),
                "side": side,
                "quantity": q,
                "executed_price": price,
                "requested_price": reference,
                "fee": q * price * bp["fee_bps"] / 10000,
                "timestamp": bar["timestamp"],
                "market_context": {**bar, "price": reference},
                "arm": chosen,
                "reason": reason,
                "mode": "paper",
                "engine": ENGINE,
            }
            account["fills"].append(fill)
            if side == "BUY":
                account["entry_step"], account["entry_arm"] = index, chosen
            elif training:
                after = calculate(account["fills"], bp["capital"], account["marks"] + [bar])
                pnl = after["realized_by_trade"][fill["trade_id"]]
                if state.get("schema") == "tracy.agent-apr/2":
                    state["arms"][chosen]["closed_trades"] += 1
                    state["arms"][chosen]["net_pnl"] = round(state["arms"][chosen]["net_pnl"] + pnl, 8)
                else:
                    learn(state, chosen, pnl)  # Legacy v1 evidence keeps its original semantics.
    account["marks"].append(bar)
    account["decisions"].append(
        {
            "timestamp": bar["timestamp"],
            "signal_as_of": history[-1]["close_timestamp"] if history else None,
            "arm": chosen,
            "threshold_bps": value,
            "side": side,
            "reason": reason,
            "daily_loss_pct": loss,
            "drawdown_pct": before["current_drawdown"],
        }
    )


def simulate(bp, bars, state, arm=0, training=False, warmup=None):
    state, account = deepcopy(state), new_account()
    history = list(warmup or [])
    pending, attributed = [], []
    for i, bar in enumerate(bars):
        chosen = (
            choose(state)
            if training
            and not calculate(account["fills"], bp["capital"], account["marks"])["position_quantity"]
            else arm
        )
        at_open = {**bar, "price": bar["open"]}
        count_before = len(account["fills"])
        step(bp, account, state, history, at_open, i, chosen, training, explore=training)
        if (
            training
            and state.get("schema") == "tracy.agent-apr/2"
            and len(account["fills"]) > count_before
            and account["fills"][-1]["side"] == "BUY"
        ):
            from backend.adaptive.learning import decision_contract

            pending.append(
                decision_contract(
                    bp,
                    state,
                    0,
                    account["decisions"][-1],
                    account["fills"][-1],
                    history,
                    "historical_" + str(i),
                    "training",
                    "training",
                )
            )
        account["marks"].append({**bar, "timestamp": bar["close_timestamp"] - 1})
        history.append(bar)
        if training and pending:
            from backend.adaptive.learning import evaluate

            for d in list(pending):
                if d["due_at"] > bar["close_timestamp"]:
                    continue
                observed = [
                    b
                    for b in history
                    if b["timestamp"] >= d["evaluation_start"] and b["close_timestamp"] <= d["due_at"]
                ]
                outcome = evaluate(
                    d,
                    {
                        "period_start": d["evaluation_start"],
                        "period_end": d["due_at"],
                        "bars": observed,
                        "mode": "historical_training",
                    },
                )
                outcome.pop("evaluated_at", None)  # Deterministic replay report.
                attributed.append(outcome)
                rule, arm_state, signal = (
                    state["apr"][d["arm"]],
                    state["arms"][d["arm"]],
                    outcome["attribution"],
                )
                key = (
                    "ignored"
                    if not signal["eligible_for_learning"]
                    else "positive"
                    if signal["decision_signal"] > 0
                    else "negative"
                )
                rule[key] += 1
                if signal["eligible_for_learning"]:
                    arm_state["alpha" if signal["decision_signal"] > 0 else "beta"] += 1
                if rule["positive"] + rule["negative"] >= bp.get("learning", {}).get("minimum_samples", 20):
                    rule["probability"] = round(
                        (2 + rule["positive"]) / (4 + rule["positive"] + rule["negative"]), 6
                    )
                    rule["reason"] = "Historical horizon attribution, not net trade PnL"
                pending.remove(d)
    # Deterministic end-of-window liquidation. It is disclosed, not a signal.
    final = {**bars[-1], "timestamp": bars[-1]["close_timestamp"] - 1}
    step(bp, account, state, history, final, len(bars), arm, training, force_exit=True)
    metrics = calculate(account["fills"], bp["capital"], account["marks"])
    return {
        "metrics": metrics,
        "fills": account["fills"],
        "decisions": account["decisions"],
        "state": state,
        "attributed_outcomes": attributed,
    }


def experiment(bp, snapshot, prior, training_bars):
    bars = snapshot["bars"]
    train, validation = bars[:training_bars], bars[training_bars:]
    learned = simulate(bp, train, prior, prior["active_arm"], training=True)
    state = learned["state"]
    # Candidate selection cannot inspect the following validation interval.
    candidate = max(
        range(len(state["arms"])),
        key=lambda i: (
            (
                state["apr"][i]["probability"]
                if state.get("schema") == "tracy.agent-apr/2"
                else state["arms"][i]["alpha"] / (state["arms"][i]["alpha"] + state["arms"][i]["beta"])
            ),
            -i,
        ),
    )
    baseline_state = deepcopy(prior)
    for rule in baseline_state.get("apr", []):
        rule["probability"] = 0.5
    baseline = simulate(bp, validation, baseline_state, 0, warmup=train)
    incumbent = simulate(bp, validation, prior, prior["active_arm"], warmup=train)
    adaptive = simulate(bp, validation, state, candidate, warmup=train)
    a, b, c = adaptive["metrics"], baseline["metrics"], incumbent["metrics"]
    checks = {
        "candidate_has_training_sample": state["arms"][candidate]["closed_trades"] >= 3,
        "validation_sample": min(a["closed_trade_count"], b["closed_trade_count"], c["closed_trade_count"])
        >= 5,
        "net_return_beats_baseline_and_incumbent": a["return_pct"]
        > max(b["return_pct"], c["return_pct"]) + 0.05,
        "drawdown_not_worse": a["max_drawdown"] <= min(b["max_drawdown"], c["max_drawdown"]),
        "inside_risk_limit": a["max_drawdown"] < bp["guardrails"]["max_drawdown"],
    }
    passed = all(checks.values())
    state["observed_until"] = snapshot["period_end"]
    # Activation requires an explicit review of this signed report.
    return {
        "engine": ENGINE,
        "mode": "historical_paper_learning",
        "training": learned,
        "baseline": baseline,
        "incumbent": incumbent,
        "candidate": adaptive,
        "candidate_arm": candidate,
        "incumbent_arm": prior["active_arm"],
        "gate": {"passed": passed, "checks": checks},
        "next_state": state,
        "training_end": train[-1]["close_timestamp"],
        "validation_start": validation[0]["timestamp"],
        "validation_end": snapshot["period_end"],
        "note": "APR v2 learns from matured horizon attribution; v1 retains legacy closed-exit counts. Validation freezes the candidate. Gate success is evidence for one interval, not proof of future profit. Mainnet execution is unavailable.",
    }
