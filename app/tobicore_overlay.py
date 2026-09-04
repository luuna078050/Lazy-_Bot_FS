from __future__ import annotations
import os
import httpx


def _tc(payload: dict):
    base = os.getenv("TOBICORE_URL", "").rstrip("/")
    if not base:
        return None
    try:
        r = httpx.post(base + "/api/signal", json=payload, timeout=2.5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def install(m):
    original_ranking = m.ranking
    original_openp = m.openp

    async def ranking():
        rows = await original_ranking()
        for row in rows:
            try:
                tc = _tc({
                    "symbol": row["symbol"],
                    "price": float(row["price"]),
                    "momentum": float(row.get("momentum", (row.get("score", 50.0) - 50.0) / 10.0)),
                    "trend": float((row.get("score", 50.0) - 50.0) / 20.0),
                    "volume_ratio": 1.0,
                    "spread_bps": 0.0,
                })
                if tc:
                    signals = tc.get("signals", [])
                    buy = [x for x in signals if x.get("direction") == "BUY"]
                    sell = [x for x in signals if x.get("direction") == "SELL"]
                    avg = sum(float(x.get("score", 50.0)) for x in signals) / max(1, len(signals))
                    row["tobicore_score"] = round(avg, 2)
                    row["tobicore_buy"] = len(buy)
                    row["tobicore_sell"] = len(sell)
                    row["tobicore_signal"] = "BUY" if len(buy) > len(sell) and avg >= 55 else ("SELL" if len(sell) > len(buy) and avg <= 45 else "WAIT")
                    row["score_local"] = row["score"]
                    row["score"] = round(float(row["score"]) * 0.65 + avg * 0.35, 2)
            except Exception:
                row["tobicore_signal"] = "UNAVAILABLE"
        rows.sort(key=lambda x: (x["score"], x.get("volume", 0)), reverse=True)
        return rows

    async def openp(i, s):
        row = next((x for x in m.S.get("ranking", []) if x.get("symbol") == s), None)
        if row and row.get("tobicore_signal") not in ("BUY",):
            return
        return await original_openp(i, s)

    m.ranking = ranking
    m.openp = openp
