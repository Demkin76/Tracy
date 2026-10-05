"""Paper execution contract. No on-chain claim and no arbitrary runner code."""

from backend.crypto.hashing import digest
from backend.performance.metrics import calculate


def signal(config, bars, step, position, entry_step):
    if step < config["lookback"]:
        return None
    if position > 0:
        past = bars[step - 1]["price"] / bars[max(0, step - config["lookback"])]["price"] - 1
        if step == len(bars) - 1:
            return "SELL"
        if config["runner"] == "buy_hold":
            return None
        if step - entry_step >= config.get("exit_after_bars", 6):
            return "SELL"
        if config["runner"] == "momentum" and past < -config["threshold_bps"] / 10000:
            return "SELL"
        if config["runner"] == "mean_reversion" and past > config["threshold_bps"] / 10000:
            return "SELL"
        return None
    if step == len(bars) - 1:
        return None
    past = bars[step - 1]["price"] / bars[step - config["lookback"]]["price"] - 1
    if config["runner"] == "buy_hold":
        return "BUY"
    if config["runner"] == "momentum" and past > config["threshold_bps"] / 10000:
        return "BUY"
    if config["runner"] == "mean_reversion" and past < -config["threshold_bps"] / 10000:
        return "BUY"
    return None


class PaperAdapter:
    mode = "paper"

    @staticmethod
    def execute(order, context, config, trade_id, intent_id, strategy, deployment_id):
        slip = config["slippage_bps"] / 10000
        price = context["price"] * (1 + slip if order["side"] == "BUY" else 1 - slip)
        quantity = round(order["quantity"], 8)
        return {
            "trade_id": trade_id,
            "intent_id": intent_id,
            "deployment_id": deployment_id,
            "agent_id": strategy["agent_id"],
            "strategy_id": strategy["strategy_id"],
            "strategy_version": strategy["version"],
            "market": strategy["market"],
            "side": order["side"],
            "requested_price": order["requested_price"],
            "executed_price": round(price, 8),
            "quantity": quantity,
            "fee": round(quantity * price * config["fee_bps"] / 10000, 8),
            "slippage": round(abs(price - order["requested_price"]) * quantity, 8),
            "timestamp": context["timestamp"],
            "market_context": context,
            "mode": "paper",
            "tx_signature": None,
            "evidence_source": "tracy_paper_ledger",
        }

    @staticmethod
    def verify(conn, trade):
        import json

        row = conn.execute("SELECT body FROM paper_fills WHERE trade_id=?", (trade["trade_id"],)).fetchone()
        return bool(row and digest(json.loads(row[0])) == digest(trade))


def run_backtest(version, bars):
    config = version["strategy_config"]
    fills = []
    entry = -1
    capital = version["starting_capital"]
    for step, bar in enumerate(bars):
        portfolio = calculate(fills, capital, [bar])
        side = signal(config, bars, step, portfolio["position_quantity"], entry)
        if not side:
            continue
        if side == "BUY":
            quantity = round(
                portfolio["cash"]
                * config["allocation_pct"]
                / 100
                / (bar["price"] * (1 + config["slippage_bps"] / 10000) * (1 + config["fee_bps"] / 10000)),
                8,
            )
            entry = step
        else:
            quantity = portfolio["position_quantity"]
        if quantity <= 0:
            continue
        order = {"side": side, "quantity": quantity, "requested_price": bar["price"]}
        fill = PaperAdapter.execute(
            order, bar, config, "test_" + str(len(fills)), "test", version, "backtest"
        )
        fills.append(fill)
    return {
        "trades": fills,
        "metrics": calculate(fills, capital, bars),
        "market_context": bars,
        "result": "COMPLETED",
        "mode": "backtest",
        "source": "historical_exchange_backtest",
        "execution_assumptions": "Signals use prior closes; simulated fills use current close plus configured slippage and fees. No intrabar liquidity or order-book model.",
    }
