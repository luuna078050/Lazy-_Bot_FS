from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from statistics import median, pstdev
from types import MethodType

from .market_radar import RADAR, TOP150, STAGE1, STAGE2, STAGE3, FINAL, MIN_24H_QUOTE, STABLE_BASES

# Fast Scalper analysis set.
# 1s and 30s are DERIVED from aggTrade pulses.
# 1m/3m/5m/15m/30m use native Binance Spot kline streams.
# Do not request 1s/30s Spot kline streams: they are not standard Spot intervals.
TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m")
ANALYSIS_TIMEFRAMES = ("1s", "30s", "1m", "3m", "5m", "15m", "30m")
DETAIL_SYMBOL_LIMIT = 80

RADAR.bars = defaultdict(lambda: defaultdict(lambda: deque(maxlen=120)))


def _build_url(self, symbols=None):
    streams = ["!miniTicker@arr"]
    if symbols:
        for s in symbols:
            for tf in TIMEFRAMES:
                streams.append(f"{s.lower()}@kline_{tf}")
            streams.append(f"{s.lower()}@aggTrade")
    return "wss://stream.binance.com:443/stream?streams=" + "/".join(streams)


def _promote_streams(self):
    deadline = time.time() + 8
    while not self._stop.is_set() and time.time() < deadline:
        symbols = self._top_symbols()[:DETAIL_SYMBOL_LIMIT]
        if len(symbols) >= 50:
            with self.lock:
                self._stream_symbols = tuple(symbols)
            print(f"RADAR_DETAIL_STREAMS_READY {len(symbols)} native=1m,3m,5m,15m,30m derived=1s,30s", flush=True)
            try:
                if self._ws:
                    self._ws.close()
            except Exception:
                pass
            return
        time.sleep(.25)


def _kline(self, d):
    k = d.get("k", {})
    s = str(k.get("s", "")).upper()
    interval = str(k.get("i", ""))
    if not s or interval not in TIMEFRAMES:
        return
    try:
        r = {"ts": float(k.get("t", 0)) / 1000, "open": float(k.get("o", 0) or 0), "high": float(k.get("h", 0) or 0), "low": float(k.get("l", 0) or 0), "close": float(k.get("c", 0) or 0), "quote_volume": float(k.get("q", 0) or 0), "closed": bool(k.get("x", False))}
    except (TypeError, ValueError):
        return
    with self.lock:
        b = self.bars[s][interval]
        if b and b[-1]["ts"] == r["ts"]:
            b[-1] = r
        else:
            b.append(r)


def _change(self, bars, n=1):
    if len(bars) <= n or bars[-1]["close"] <= 0 or bars[-1-n]["open"] <= 0:
        return 0.0
    return (bars[-1]["close"] / bars[-1-n]["open"] - 1) * 100


def _pulse_change(pulse, seconds):
    if len(pulse) < 2:
        return 0.0
    latest = pulse[-1]
    target = latest["sec"] - int(seconds)
    base = None
    for row in reversed(pulse[:-1]):
        if row["sec"] <= target:
            base = row
            break
    if base is None or float(base.get("price") or 0) <= 0:
        return 0.0
    return (float(latest.get("price") or 0) / float(base["price"]) - 1) * 100


def _metrics(self, symbol, price):
    with self.lock:
        bars = {tf: list(self.bars.get(symbol, {}).get(tf, ())) for tf in TIMEFRAMES}
        pulse = list(self.pulses.get(symbol, ()))

    changes = {tf: self._change(bars[tf], 1) for tf in TIMEFRAMES}
    p1 = _pulse_change(pulse, 1)
    p30 = _pulse_change(pulse, 30)
    pvol = 0.0
    br = 0.5
    if pulse:
        recent = pulse[-30:]
        pvol = sum(x["quote"] for x in recent) / max(1, len(recent))
        latest = pulse[-1]
        br = latest["buy_quote"] / latest["quote"] if latest["quote"] > 0 else .5

    recent_1m = bars["1m"][-8:]
    ranges = []
    vols = []
    for b in recent_1m:
        if b["close"] > 0:
            ranges.append((b["high"] - b["low"]) / b["close"] * 100)
        vols.append(max(0, b["quote_volume"]))
    risk = pstdev(ranges) if len(ranges) >= 3 else (ranges[-1] if ranges else 0.0)
    base = median(vols[:-1]) if len(vols) >= 3 else 0.0
    vr = vols[-1] / base if base > 0 else 1.0

    return {
        "change_1s_pct": p1,
        "change_30s_pct": p30,
        "change_1m_pct": changes["1m"],
        "change_3m_pct": changes["3m"],
        "change_5m_pct": changes["5m"],
        "change_15m_pct": changes["15m"],
        "change_30m_pct": changes["30m"],
        "risk_pct": risk,
        "volume_ratio": vr,
        "pulse_volume": pvol,
        "buy_ratio": br,
    }


def _pulse_score(self, m):
    return min(1, max(0,
        .20 * min(1, max(0, m["change_1s_pct"]) / .08)
        + .25 * min(1, max(0, m["change_30s_pct"]) / .20)
        + .25 * min(1, max(0, m["change_1m_pct"]) / .40)
        + .15 * min(1, max(0, m["volume_ratio"] - 1) / 3)
        + .15 * min(1, max(0, (m["buy_ratio"] - .5) / .30))
    ))


def _score(self, t, m):
    q = max(1, float(t.get("q", 0) or 0))
    liq = min(1, max(0, math.log10(q) / 9))
    multi = (
        .20*m["change_1s_pct"] + .25*m["change_30s_pct"]
        + .20*m["change_1m_pct"] + .15*m["change_3m_pct"]
        + .10*m["change_5m_pct"] + .07*m["change_15m_pct"]
        + .03*m["change_30m_pct"]
    )
    mom = min(1, max(0, multi / 1.2))
    act = min(1, max(0, m["volume_ratio"] - 1) / 3)
    pulse = self._pulse_score(m)
    pen = min(.45, max(0, m["risk_pct"]) / 4)
    return max(0, min(100, 100 * (.30*liq + .28*mom + .22*act + .20*pulse) * (1-pen)))


def snapshot(self, limit=FINAL):
    self.start()
    if not self._ready.wait(timeout=8):
        return []
    with self.lock:
        items = [(s,d) for s,d in self.tickers.items() if s.endswith("USDT") and s[:-4] not in STABLE_BASES]
    items.sort(key=lambda x: float(x[1].get("q",0) or 0), reverse=True)
    top150 = items[:TOP150]
    self.stage_counts["universe"] = len(items)
    self.stage_counts["top150"] = len(top150)
    rows = []
    for s,d in top150:
        try:
            p = float(d.get("c",0) or 0)
            q = float(d.get("q",0) or 0)
        except (TypeError,ValueError):
            continue
        if p <= 0 or q < MIN_24H_QUOTE:
            continue
        m = self._metrics(s,p)
        score = self._score(d,m)
        if q < 1_000_000:
            continue
        if m["risk_pct"] > 2.5 and m["change_1m_pct"] < .5:
            continue
        rows.append((s,d,m,score))

    rows.sort(key=lambda x:(x[3],float(x[1].get("q",0) or 0)), reverse=True)
    s1 = rows[:STAGE1]
    self.stage_counts["stage1"] = len(s1)
    s1 = [x for x in s1 if x[2]["volume_ratio"] >= .8 or x[2]["change_30s_pct"] > .08]
    s2 = s1[:STAGE2]
    self.stage_counts["stage2"] = len(s2)
    s2 = [x for x in s2 if x[2]["change_3m_pct"] > -.35 and x[2]["change_5m_pct"] > -.80]
    s3 = s2[:STAGE3]
    self.stage_counts["stage3"] = len(s3)
    s3.sort(key=lambda x:x[3], reverse=True)
    final = s3[:FINAL]
    self.stage_counts["top15"] = len(final)

    out = []
    for s,d,m,score in final:
        p = float(d.get("c",0) or 0)
        sig = "BUY" if m["change_30s_pct"] > 0 and m["change_1m_pct"] > 0 and m["change_3m_pct"] > 0 else ("WATCH" if m["change_1m_pct"] > 0 else "WAIT")
        target = min(.012, max(.0035, abs(m["change_1m_pct"])/100*.8))
        out.append({
            "symbol": s[:-4]+"/USDT",
            "price": p,
            "change_24h_pct": round((p/float(d.get("o",p) or p)-1)*100,3),
            "quote_volume_24h": float(d.get("q",0) or 0),
            "score": round(score,2),
            "signal": sig,
            "estimated_entry": p,
            "estimated_exit": p*(1+target),
            "estimated_stop": p*(1-.004),
            "change_1s_pct": round(m["change_1s_pct"],4),
            "change_30s_pct": round(m["change_30s_pct"],4),
            "change_1m_pct": round(m["change_1m_pct"],4),
            "change_3m_pct": round(m["change_3m_pct"],4),
            "change_5m_pct": round(m["change_5m_pct"],4),
            "change_15m_pct": round(m["change_15m_pct"],4),
            "change_30m_pct": round(m["change_30m_pct"],4),
            "volume_ratio": round(m["volume_ratio"],2),
            "pump_events": 0,
            "pump_score": round(self._pulse_score(m),3),
            "hold_seconds": 90,
            "analysis_timeframes": list(ANALYSIS_TIMEFRAMES),
        })
    self.last_snapshot = time.time()
    return out[:max(1,int(limit))]

RADAR._build_url = MethodType(_build_url, RADAR)
RADAR._promote_streams = MethodType(_promote_streams, RADAR)
RADAR._kline = MethodType(_kline, RADAR)
RADAR._change = MethodType(_change, RADAR)
RADAR._metrics = MethodType(_metrics, RADAR)
RADAR._pulse_score = MethodType(_pulse_score, RADAR)
RADAR._score = MethodType(_score, RADAR)
RADAR.snapshot = MethodType(snapshot, RADAR)
print("RADAR_TIMEFRAMES_ENABLED native=1m,3m,5m,15m,30m derived=1s,30s HOLD=90s", flush=True)
