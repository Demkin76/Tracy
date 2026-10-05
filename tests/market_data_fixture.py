"""Deterministic synthetic candles. Never presented as observed market prices."""

import math
from statistics import pstdev

SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}


def candles(market, timeframe, start, count, dataset="trending"):
    price = {"SOL/USDC": 145.0, "BTC/USDC": 60000.0, "ETH/USDC": 2500.0}[market]
    rows, returns = [], []
    for i in range(count):
        if dataset == "trending":
            change = 0.011 + 0.023 * math.sin(i * 0.65)
        elif dataset == "choppy":
            change = 0.003 + 0.032 * math.sin(i * 0.95)
        else:
            change = (0.008 if i < 32 else -0.006) + (0.018 if i < 32 else 0.039) * math.sin(i * 0.9)
        price *= 1 + change
        returns.append(change)
        rows.append(
            {
                "timestamp": start + i * SECONDS[timeframe],
                "price": round(price, 8),
                "volatility": round(100 * pstdev(returns[-20:]), 4) if i else 0,
                "volume": round(1000000 * (1 + abs(change) * 20), 2),
                "trend": "up" if sum(returns[-8:]) > 0 else "down",
                "source": "synthetic:" + dataset,
                "synthetic": True,
                "bar": i,
            }
        )
    return rows


def regime(reference, current):
    if not reference or not current:
        return {"status": "INSUFFICIENT_DATA", "message": "Market context is not available."}
    ref_vol = sum(r["volatility"] for r in reference) / len(reference)
    ref_trend = max(("up", "down"), key=lambda t: sum(r["trend"] == t for r in reference))
    shifted = current["volatility"] > max(0.5, ref_vol * 1.5) or current["trend"] != ref_trend
    return {
        "status": "SHIFTED" if shifted else "SIMILAR",
        "reference_volatility": round(ref_vol, 4),
        "current_volatility": current["volatility"],
        "reference_trend": ref_trend,
        "current": current,
        "message": "Market conditions differ from the test period."
        if shifted
        else "Conditions are similar to the test period.",
        "note": "Synthetic context comparison, not a prediction or an optimized strategy recommendation.",
    }
