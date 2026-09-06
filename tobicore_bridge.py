from __future__ import annotations
import os
import httpx

TOBICORE_URL = os.getenv("TOBICORE_URL", "").rstrip("/")

async def signal(symbol: str, price: float, momentum: float, trend: float, volume_ratio: float = 1.0, spread_bps: float = 0.0):
    if not TOBICORE_URL:
        return None
    payload = {"symbol": symbol, "price": price, "momentum": momentum, "trend": trend, "volume_ratio": volume_ratio, "spread_bps": spread_bps}
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.post(f"{TOBICORE_URL}/api/signal", json=payload)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None

def best_signal(data: dict | None):
    if not data:
        return None
    signals = data.get("signals", [])
    active = [x for x in signals if x.get("direction") in ("BUY", "SELL")]
    if not active:
        return None
    return max(active, key=lambda x: float(x.get("confidence", 0)))
