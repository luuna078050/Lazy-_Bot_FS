"""Deterministic v0 decision layer; learning is driven by stored feedback in later releases."""

def decide(payload: dict) -> dict:
    features = payload.get("features") or {}
    trend = float(features.get("trend", 0) or 0)
    momentum = float(features.get("momentum", 0) or 0)
    volatility = float(features.get("volatility", 0) or 0)
    liquidity = float(features.get("liquidity", 0) or 0)

    score = 50.0 + trend * 20.0 + momentum * 20.0 + liquidity * 10.0 - volatility * 10.0
    score = max(0.0, min(100.0, score))
    if score >= 65:
        direction = "BUY"
    elif score <= 35:
        direction = "SELL"
    else:
        direction = "HOLD"
    confidence = abs(score - 50.0) / 50.0
    return {
        "symbol": payload["symbol"],
        "direction": direction,
        "score": round(score, 4),
        "confidence": round(confidence, 4),
        "source": payload.get("source", "unknown"),
        "engine_version": "0.1.0",
    }
