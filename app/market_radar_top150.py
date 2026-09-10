from __future__ import annotations

"""TOP-150 -> TOP-15 Fast Scalper radar.

Market discovery comes from Binance public WebSocket.  The radar keeps a broad
universe from the all-market mini ticker, then progressively narrows it using
liquidity, short-term activity, momentum and risk.  The trading engine remains
independent: this module only supplies recommendations and live prices.
"""

import json
import math
import threading
import time
from collections import defaultdict, deque
from statistics import median, pstdev
from typing import Any

import websocket

STABLE_BASES = {"USDT", "USDC", "FDUSD", "USDE", "TUSD", "DAI", "USD1", "USDS", "EUR"}
MIN_24H_QUOTE = 50_000.0
TOP150 = 150
STAGE1 = 80
STAGE2 = 40
STAGE3 = 25
FINAL = 15

class MarketRadar:
    def __init__(self, top_n: int = FINAL):
        self.top_n = top_n
        self.lock = threading.RLock()
        self.tickers: dict[str, dict[str, Any]] = {}
        self.bars = defaultdict(lambda: deque(maxlen=20))
        self.pulses = defaultdict(lambda: deque(maxlen=90))
        self._ws = None
        self._stop = threading.Event()
        self._thread = None
        self._ready = threading.Event()
        self.connected = False
        self.last_error: str | None = None
        self.last_update = 0.0
        self.message_count = 0
        self.stage_counts = {"universe": 0, "top150": 0, "stage1": 0, "stage2": 0, "stage3": 0, "top15": 0}
        self.last_snapshot = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="fast-scalper-market-radar")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.connected = False
        ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "connected": self.connected,
                "ready": self._ready.is_set(),
                "ticker_count": len(self.tickers),
                "last_update": self.last_update,
                "seconds_since_update": round(time.time() - self.last_update, 1) if self.last_update else None,
                "message_count": self.message_count,
                "last_error": self.last_error,
                "data_source": "Binance public WebSocket",
                "rest_polling": False,
                "stage_counts": dict(self.stage_counts),
            }

    def _build_url(self, symbols: list[str] | None = None) -> str:
        # !miniTicker@arr supplies the complete discovery universe. Once enough
        # data is present, add short-term kline and trade streams for TOP-150.
        streams = ["!miniTicker@arr"]
        if symbols:
            streams += [f"{s.lower()}@kline_1m" for s in symbols]
            streams += [f"{s.lower()}@aggTrade" for s in symbols]
        return "wss://stream.binance.com:443/stream?streams=" + "/".join(streams)

    def _top_symbols(self) -> list[str]:
        with self.lock:
            rows = []
            for s, d in self.tickers.items():
                if not s.endswith("USDT") or s[:-4] in STABLE_BASES:
                    continue
                try:
                    q = float(d.get("q", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if q >= MIN_24H_QUOTE:
                    rows.append((s, q))
        rows.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in rows[:TOP150]]

    def _run(self) -> None:
        # Phase 1: discover the current broad market through one public stream.
        while not self._stop.is_set():
            try:
                symbols = self._top_symbols()
                url = self._build_url(symbols if len(symbols) >= 50 else None)
                self._ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=15, ping_timeout=10)
            except Exception as exc:
                self.connected = False
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            if not self._stop.is_set():
                time.sleep(1.0)

    def _on_open(self, _ws) -> None:
        self.connected = True
        self.last_error = None
        print("RADAR_WS_CONNECTED", flush=True)

    def _on_close(self, _ws, code=None, msg=None) -> None:
        self.connected = False
        if code:
            self.last_error = f"WebSocket closed: {code} {msg or ''}".strip()

    def _on_error(self, _ws, error) -> None:
        self.connected = False
        self.last_error = str(error)[:300]
        print(f"RADAR_WS_ERROR {self.last_error}", flush=True)

    def _on_message(self, _ws, raw) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            with self.lock:
                self.message_count += 1
            if isinstance(data, list):
                for row in data:
                    if isinstance(row, dict):
                        self._mini(row)
                return
            if not isinstance(data, dict):
                return
            event = data.get("e")
            if event == "24hrMiniTicker":
                self._mini(data)
            elif event == "kline":
                self._kline(data)
            elif event == "aggTrade":
                self._trade(data)
        except Exception as exc:
            self.last_error = f"message: {exc}"[:300]

    def _mini(self, d: dict[str, Any]) -> None:
        s = str(d.get("s", "")).upper()
        if not s:
            return
        with self.lock:
            self.tickers[s] = dict(d)
            self.last_update = time.time()
            if s.endswith("USDT") and s[:-4] not in STABLE_BASES:
                self._ready.set()

    def _kline(self, d: dict[str, Any]) -> None:
        k = d.get("k", {})
        s = str(k.get("s", "")).upper()
        if not s:
            return
        try:
            row = {
                "ts": float(k.get("t", 0)) / 1000,
                "open": float(k.get("o", 0) or 0),
                "high": float(k.get("h", 0) or 0),
                "low": float(k.get("l", 0) or 0),
                "close": float(k.get("c", 0) or 0),
                "quote_volume": float(k.get("q", 0) or 0),
            }
        except (TypeError, ValueError):
            return
        with self.lock:
            bars = self.bars[s]
            if bars and bars[-1]["ts"] == row["ts"]:
                bars[-1] = row
            else:
                bars.append(row)

    def _trade(self, d: dict[str, Any]) -> None:
        s = str(d.get("s", "")).upper()
        try:
            p = float(d.get("p", 0) or 0)
            q = float(d.get("q", 0) or 0)
        except (TypeError, ValueError):
            return
        if not s or p <= 0 or q <= 0:
            return
        sec = int(time.time())
        quote = p * q
        with self.lock:
            h = self.pulses[s]
            if h and h[-1]["sec"] == sec:
                b = h[-1]
            else:
                b = {"sec": sec, "price": p, "quote": 0.0, "buy_quote": 0.0, "trades": 0}
                h.append(b)
            b["price"] = p
            b["quote"] += quote
            b["buy_quote"] += quote if not bool(d.get("m", False)) else 0.0
            b["trades"] += 1

    def _rolling_change(self, bars: list[dict[str, float]], n: int) -> float:
        if len(bars) <= n or bars[-1]["close"] <= 0 or bars[-1-n]["open"] <= 0:
            return 0.0
        return (bars[-1]["close"] / bars[-1-n]["open"] - 1.0) * 100.0

    def _metrics(self, symbol: str, price: float) -> dict[str, float]:
        with self.lock:
            bars = list(self.bars.get(symbol, ()))
            pulse = list(self.pulses.get(symbol, ()))
        m1 = self._rolling_change(bars, 1)
        m2 = self._rolling_change(bars, 2)
        m4 = self._rolling_change(bars, 4)
        ranges = []
        vols = []
        for b in bars[-8:]:
            if b["close"] > 0:
                ranges.append((b["high"] - b["low"]) / b["close"] * 100.0)
            vols.append(max(0.0, b["quote_volume"]))
        risk = pstdev(ranges) if len(ranges) >= 3 else (ranges[-1] if ranges else 0.0)
        vol_base = median(vols[:-1]) if len(vols) >= 3 else 0.0
        vol_ratio = vols[-1] / vol_base if vol_base > 0 else 1.0
        p30 = 0.0
        pvol = 0.0
        buy_ratio = 0.5
        if pulse:
            latest = pulse[-1]
            if len(pulse) >= 2 and pulse[-2]["price"] > 0:
                p30 = (latest["price"] / pulse[max(0, len(pulse)-31)]["price"] - 1.0) * 100.0
            recent = pulse[-30:]
            pvol = sum(x["quote"] for x in recent) / max(1, len(recent))
            buy_ratio = latest["buy_quote"] / latest["quote"] if latest["quote"] > 0 else 0.5
        return {"change_1m_pct": m1, "change_2m_pct": m2, "change_4m_pct": m4,
                "risk_pct": risk, "volume_ratio": vol_ratio, "change_30s_pct": p30,
                "pulse_volume": pvol, "buy_ratio": buy_ratio}

    def _pulse_score(self, m: dict[str, float]) -> float:
        short = max(0.0, m["change_30s_pct"])
        m1 = max(0.0, m["change_1m_pct"])
        activity = min(1.0, max(0.0, m["volume_ratio"] - 1.0) / 3.0)
        orderflow = min(1.0, max(0.0, (m["buy_ratio"] - 0.50) / 0.30))
        return min(1.0, 0.35 * min(1.0, short / 0.20) + 0.30 * min(1.0, m1 / 0.40) + 0.20 * activity + 0.15 * orderflow)

    def _score(self, t: dict[str, Any], m: dict[str, float]) -> float:
        q = max(1.0, float(t.get("q", 0) or 0))
        liquidity = min(1.0, max(0.0, math.log10(q) / 9.0))
        momentum = min(1.0, max(0.0, (0.45*m["change_1m_pct"] + 0.35*m["change_2m_pct"] + 0.20*m["change_4m_pct"]) / 1.2))
        activity = min(1.0, max(0.0, m["volume_ratio"] - 1.0) / 3.0)
        pulse = self._pulse_score(m)
        # Risk-adjustment penalizes noisy/oversized one-minute ranges, while
        # preserving fast but orderly movement.
        risk_penalty = min(0.45, max(0.0, m["risk_pct"]) / 4.0)
        raw = 0.30*liquidity + 0.28*momentum + 0.22*activity + 0.20*pulse
        return max(0.0, min(100.0, 100.0 * raw * (1.0 - risk_penalty)))

    def snapshot(self, limit: int = FINAL) -> list[dict[str, Any]]:
        self.start()
        if not self._ready.wait(timeout=8.0):
            return []
        with self.lock:
            items = [(s, d) for s, d in self.tickers.items()
                     if s.endswith("USDT") and s[:-4] not in STABLE_BASES]
        items.sort(key=lambda x: float(x[1].get("q", 0) or 0), reverse=True)
        top150 = items[:TOP150]
        self.stage_counts["universe"] = len(items)
        self.stage_counts["top150"] = len(top150)
        rows = []
        for s, d in top150:
            try:
                price = float(d.get("c", 0) or 0)
                q = float(d.get("q", 0) or 0)
            except (TypeError, ValueError):
                continue
            if price <= 0 or q < MIN_24H_QUOTE:
                continue
            m = self._metrics(s, price)
            score = self._score(d, m)
            # Minimum quality gates: enough liquidity, some live activity, and
            # no extreme short-term noise. Gates are intentionally progressive.
            if q < 1_000_000:
                continue
            if m["risk_pct"] > 2.5 and m["change_1m_pct"] < 0.5:
                continue
            rows.append((s, d, m, score))
        rows.sort(key=lambda x: (x[3], float(x[1].get("q", 0) or 0)), reverse=True)
        s1 = rows[:STAGE1]
        self.stage_counts["stage1"] = len(s1)
        s1 = [x for x in s1 if x[2]["volume_ratio"] >= 0.8 or x[2]["change_1m_pct"] > 0.08]
        s2 = s1[:STAGE2]
        self.stage_counts["stage2"] = len(s2)
        s2 = [x for x in s2 if x[2]["change_2m_pct"] > -0.35 and x[2]["change_4m_pct"] > -0.80]
        s3 = s2[:STAGE3]
        self.stage_counts["stage3"] = len(s3)
        s3.sort(key=lambda x: x[3], reverse=True)
        final = s3[:FINAL]
        self.stage_counts["top15"] = len(final)
        out = []
        for s, d, m, score in final:
            p = float(d.get("c", 0) or 0)
            signal = "BUY" if m["change_1m_pct"] > 0 and m["change_2m_pct"] > 0 else ("WATCH" if m["change_1m_pct"] > 0 else "WAIT")
            target = min(0.012, max(0.0035, abs(m["change_2m_pct"]) / 100.0 * 0.8))
            out.append({
                "symbol": s[:-4] + "/USDT", "price": p,
                "change_24h_pct": round((p / float(d.get("o", p) or p) - 1.0) * 100.0, 3),
                "quote_volume_24h": float(d.get("q", 0) or 0), "score": round(score, 2),
                "signal": signal, "estimated_entry": p, "estimated_exit": p * (1.0 + target),
                "estimated_stop": p * (1.0 - 0.004),
                "change_3m_pct": round((m["change_2m_pct"] + m["change_1m_pct"]) / 2.0, 4),
                "volume_ratio": round(m["volume_ratio"], 2), "pump_events": 0,
                "pump_score": round(self._pulse_score(m), 3), "hold_seconds": 180,
            })
        self.last_snapshot = time.time()
        return out[:max(1, int(limit))]

    def price(self, symbol: str) -> float:
        s = symbol.upper().replace("/", "")
        with self.lock:
            d = self.tickers.get(s)
            try:
                return float(d.get("c", 0) or 0) if d else 0.0
            except (TypeError, ValueError):
                return 0.0

RADAR = MarketRadar(FINAL)
