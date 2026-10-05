"""Long-only spot portfolio accounting; fees included in cost basis, no leverage."""


def calculate(fills, capital, marks=None):
    cash, quantity, cost, fees, slippage = float(capital), 0.0, 0.0, 0.0, 0.0
    realized, closed, curve = 0.0, [], [{"timestamp": None, "equity": float(capital)}]
    peak, max_dd, last_price = float(capital), 0.0, 0.0
    events = [(f["timestamp"], 0, i, f) for i, f in enumerate(fills)]
    events += [(m["timestamp"], 1, i, m) for i, m in enumerate(marks or [])]
    outcomes = {}
    for timestamp, kind, _, event in sorted(events, key=lambda e: e[:3]):
        if kind == 0:
            q, p, fee = event["quantity"], event["executed_price"], event["fee"]
            if q <= 0 or p <= 0 or fee < 0:
                raise ValueError("Invalid fill")
            last_price = event["market_context"]["price"]
            fees += fee
            slippage += abs(p - event["requested_price"]) * q
            if event["side"] == "BUY":
                debit = q * p + fee
                if debit > cash + 0.000001:
                    raise ValueError("Insufficient cash in fill ledger")
                cash -= debit
                quantity += q
                cost += debit
            else:
                if q > quantity + 0.000001:
                    raise ValueError("Sell exceeds inventory")
                allocated = cost * q / quantity if quantity else 0
                pnl = q * p - fee - allocated
                cash += q * p - fee
                quantity -= q
                cost -= allocated
                realized += pnl
                closed.append(pnl)
                if quantity < 0.00000001:
                    quantity, cost = 0.0, 0.0
                outcomes[event.get("trade_id", str(len(outcomes)))] = round(pnl, 8)
        else:
            last_price = event["price"]
        equity = cash + quantity * last_price
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)
        curve.append({"timestamp": timestamp, "equity": round(equity, 8)})
    equity = cash + quantity * last_price
    wins = [p for p in closed if p > 0]
    losses = [p for p in closed if p < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    recent = closed[-30:]
    recent_wins = sum(p > 0 for p in recent)
    recent_curve = curve[-31:]
    rolling = (
        (recent_curve[-1]["equity"] / recent_curve[0]["equity"] - 1) * 100
        if len(recent_curve) > 1 and recent_curve[0]["equity"]
        else None
    )

    def r(n):
        return round(n, 6)

    return {
        "pnl": r(equity - capital),
        "return_pct": r((equity / capital - 1) * 100),
        "realized_pnl": r(realized),
        "unrealized_pnl": r(quantity * last_price - cost),
        "max_drawdown": r(max_dd),
        "current_drawdown": r((peak - equity) / peak * 100),
        "win_rate": r(100 * len(wins) / len(closed)) if closed else None,
        "average_win": r(gross_win / len(wins)) if wins else None,
        "average_loss": r(sum(losses) / len(losses)) if losses else None,
        "profit_factor": r(gross_win / gross_loss) if gross_loss else None,
        "profit_factor_note": "No losing exits"
        if wins and not losses
        else "No closed trades"
        if not closed
        else None,
        "trade_count": len(fills),
        "closed_trade_count": len(closed),
        "fees": r(fees),
        "slippage": r(slippage),
        "cash": r(cash),
        "position_quantity": round(quantity, 8),
        "position_value": r(quantity * last_price),
        "equity": r(equity),
        "equity_curve": curve,
        "realized_by_trade": outcomes,
        "recent_win_rate": r(100 * recent_wins / len(recent)) if recent else None,
        "recent_closed_count": len(recent),
        "rolling_return": r(rolling) if rolling is not None else None,
        "average_slippage_bps": r(
            sum(abs(f["executed_price"] / f["requested_price"] - 1) * 10000 for f in fills) / len(fills)
        )
        if fills
        else None,
    }
