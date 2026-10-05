"""Market regime comparisons for observed exchange candles."""

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
        "note": "Historical market context comparison, not a prediction or an optimized strategy recommendation.",
    }
