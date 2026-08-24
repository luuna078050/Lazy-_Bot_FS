from __future__ import annotations

from collections import defaultdict, deque
from statistics import median


def install():
    from .market_radar import RADAR

    if getattr(RADAR, "_fs_tf_patch", False):
        return

    RADAR.tf_bars = defaultdict(lambda: deque(maxlen=120))
    original_kline = RADAR._kline
    original_build_url = RADAR._build_url

    def build_url():
        url = original_build_url()
        # The original URL already contains the 3m streams. Add 1m and 5m
        # kline streams to the same single WebSocket connection.
        marker = "@kline_3m"
        symbols = RADAR._top_symbols()
        base = "wss://stream.binance.com:443/stream?streams=!miniTicker@arr"
        streams = [f"{s.lower()}@kline_1m" for s in symbols]
        streams += [f"{s.lower()}@kline_3m" for s in symbols]
        streams += [f"{s.lower()}@kline_5m" for s in symbols]
        streams += [f"{s.lower()}@aggTrade" for s in symbols]
        return base + "/" + "/".join(streams)

    def kline(data):
        k = data.get("k", {})
        symbol = str(k.get("s", "")).upper()
        interval = str(k.get("i", "")).lower()
        if not symbol or interval not in {"1m", "3m", "5m"}:
            return original_kline(data)
        row = {
            "ts": float(k.get("t", 0)) / 1000,
            "open": float(k.get("o", 0) or 0),
            "high": float(k.get("h", 0) or 0),
            "low": float(k.get("l", 0) or 0),
            "close": float(k.get("c", 0) or 0),
            "quote_volume": float(k.get("q", 0) or 0),
            "closed": bool(k.get("x")),
        }
        key = (symbol, interval)
        with RADAR.lock:
            bars = RADAR.tf_bars[key]
            if bars and bars[-1]["ts"] == row["ts"]:
                bars[-1] = row
            else:
                bars.append(row)
        if interval == "3m":
            # Keep the legacy 3m store populated for the existing radar score.
            original_kline(data)

    def timeframe_metrics(symbol: str, timeframe: str = "3m"):
        key = symbol.replace("/", "").upper()
        tf = str(timeframe or "3m").lower()
        if tf not in {"1m", "3m", "5m"}:
            tf = "3m"
        with RADAR.lock:
            bars = list(RADAR.tf_bars.get((key, tf), ()))
            if not bars and tf == "3m":
                bars = list(RADAR.bars.get(key, ()))
        if not bars:
            return {"change_pct": 0.0, "volume_ratio": 1.0}
        current = bars[-1]
        op = float(current.get("open") or 0)
        close = float(current.get("close") or 0)
        change = (close / op - 1.0) * 100.0 if op > 0 else 0.0
        previous = [float(x.get("quote_volume") or 0) for x in bars[-6:-1] if float(x.get("quote_volume") or 0) > 0]
        base_vol = median(previous) if previous else 0.0
        volume = float(current.get("quote_volume") or 0)
        ratio = volume / base_vol if base_vol > 0 else 1.0
        return {"change_pct": round(change, 5), "volume_ratio": round(ratio, 3)}

    RADAR._build_url = build_url
    RADAR._kline = kline
    RADAR.timeframe_metrics = timeframe_metrics
    RADAR._fs_tf_patch = True
