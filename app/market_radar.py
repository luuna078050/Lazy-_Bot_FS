"""Binance WebSocket market radar for LazyBot FS Fast Scalper.

The dashboard must never hammer Binance REST. Market discovery/ranking is fed
from one public WebSocket connection. REST is not used by the recommendation
endpoint. The first recommendation request waits briefly for live data so the
UI receives real pairs instead of an empty list.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import defaultdict, deque
from statistics import median
from typing import Any

import websocket

STABLE_BASES = {"USDT", "USDC", "FDUSD", "USDE", "TUSD", "DAI", "USD1", "USDS", "EUR"}
FALLBACK = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT",
    "SUIUSDT", "TONUSDT", "LTCUSDT", "DOTUSDT", "BCHUSDT",
    "NEARUSDT", "APTUSDT", "ATOMUSDT", "UNIUSDT", "FILUSDT",
]


class MarketRadar:
    def __init__(self, top_n: int = 20):
        self.top_n = max(5, min(int(top_n), 20))
        self.lock = threading.RLock()
        self.tickers: dict[str, dict[str, Any]] = {}
        self.bars = defaultdict(lambda: deque(maxlen=60))
        self.pulses = defaultdict(lambda: deque(maxlen=20))
        self._ws = None
        self._stop = threading.Event()
        self._thread = None
        self._ready = threading.Event()
        self.last_error: str | None = None
        self.last_update = 0.0
        self.connected = False
        self.connection_url = ""
        self.message_count = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="fast-scalper-market-radar",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.connected = False
        if self._ws:
            try:
                self._ws.close()
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
                "connection_url": self.connection_url,
            }

    def _top_symbols(self) -> list[str]:
        with self.lock:
            rows = [
                (s, d) for s, d in self.tickers.items()
                if s.endswith("USDT")
                and s[:-4] not in STABLE_BASES
                and float(d.get("q", 0) or 0) >= 10_000
            ]
        rows.sort(key=lambda x: float(x[1].get("q", 0) or 0), reverse=True)
        return [s for s, _ in rows[: self.top_n]] or FALLBACK[: self.top_n]

    def _build_url(self) -> str:
        symbols = self._top_symbols()
        streams = ["!miniTicker@arr"]
        streams += [f"{s.lower()}@kline_3m" for s in symbols]
        streams += [f"{s.lower()}@aggTrade" for s in symbols]
        # Port 443 is intentionally used for Render/cloud compatibility.
        return "wss://stream.binance.com:443/stream?streams=" + "/".join(streams)

    def _run(self) -> None:
        while not self._stop.is_set():
            url = self._build_url()
            self.connection_url = url
            try:
                self._ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=15, ping_timeout=10)
            except Exception as exc:
                self.last_error = str(exc)[:300]
                self.connected = False
            if not self._stop.is_set():
                time.sleep(1.0)

    def _on_open(self, _ws) -> None:
        self.connected = True
        self.last_error = None
        print("RADAR_WS_CONNECTED", flush=True)

    def _on_close(self, _ws, close_status_code=None, close_msg=None) -> None:
        self.connected = False
        print(f"RADAR_WS_CLOSED {close_status_code} {close_msg or ''}", flush=True)
        if close_status_code:
            self.last_error = f"WebSocket closed: {close_status_code} {close_msg or ''}".strip()

    def _on_error(self, _ws, error) -> None:
        self.connected = False
        self.last_error = str(error)[:300]
        print(f"RADAR_WS_ERROR {self.last_error}", flush=True)

    def _on_message(self, _ws, raw) -> None:
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            self.message_count += 1
            if isinstance(data, list):
                for row in data:
                    self._mini(row)
                return
            event = data.get("e")
            if event == "24hrMiniTicker":
                self._mini(data)
            elif event == "kline":
                self._kline(data)
            elif event == "aggTrade":
                self._trade(data)
        except Exception as exc:
            self.last_error = str(exc)[:300]

    def _mini(self, d: dict[str, Any]) -> None:
        s = str(d.get("s", "")).upper()
        if not s:
            return
        with self.lock:
            self.tickers[s] = dict(d)
            self.last_update = time.time()
            self._ready.set()

    def _kline(self, d: dict[str, Any]) -> None:
        k = d.get("k", {})
        s = str(k.get("s", "")).upper()
        if not s:
            return
        row = {
            "ts": float(k.get("t", 0)) / 1000,
            "open": float(k.get("o", 0) or 0),
            "high": float(k.get("h", 0) or 0),
            "low": float(k.get("l", 0) or 0),
            "close": float(k.get("c", 0) or 0),
            "quote_volume": float(k.get("q", 0) or 0),
            "closed": bool(k.get("x")),
        }
        with self.lock:
            bars = self.bars[s]
            if bars and bars[-1]["ts"] == row["ts"]:
                bars[-1] = row
            else:
                bars.append(row)

    def _trade(self, d: dict[str, Any]) -> None:
        s = str(d.get("s", "")).upper()
        p = float(d.get("p", 0) or 0)
        q = float(d.get("q", 0) or 0)
        if not s or p <= 0:
            return
        now = int(time.time())
        buy = not bool(d.get("m", False))
        quote = p * q
        with self.lock:
            h = self.pulses[s]
            if h and h[-1]["sec"] == now:
                bucket = h[-1]
            else:
                bucket = {"sec": now, "price": p, "quote": 0.0, "buy_quote": 0.0, "trades": 0}
                h.append(bucket)
            bucket["price"] = p
            bucket["quote"] += quote
            bucket["buy_quote"] += quote if buy else 0.0
            bucket["trades"] += 1

    def _pulse(self, symbol: str) -> dict[str, Any]:
        with self.lock:
            h = list(self.pulses.get(symbol, ()))
        if not h:
            return {
                "pump_events": 0,
                "pump_score": 0.0,
                "signal": "WAIT",
                "pulse_change_3s_pct": 0.0,
                "pulse_volume_ratio": 1.0,
                "hold_seconds": 180,
            }
        prices = [x["price"] for x in h]
        latest = prices[-1]

        def ch(n: int) -> float:
            if len(prices) <= n or prices[-1 - n] <= 0:
                return 0.0
            return (latest / prices[-1 - n] - 1.0) * 100.0

        vols = [x["quote"] for x in h]
        base = median(vols[:-1]) if len(vols) > 2 else 0.0
        vr = vols[-1] / base if base > 0 else 1.0
        br = h[-1]["buy_quote"] / h[-1]["quote"] if h[-1]["quote"] else 0.5
        events = 0
        for i in range(1, len(h)):
            prior = [x["quote"] for x in h[max(0, i - 5):i]]
            prior_med = median(prior) if prior else 0.0
            price_jump = h[i]["price"] / h[i - 1]["price"] - 1.0 if h[i - 1]["price"] > 0 else 0.0
            if prior_med > 0 and h[i]["quote"] > prior_med * 1.8 and price_jump >= 0.001:
                events += 1
        c3 = ch(3)
        score = min(
            1.0,
            0.40 * min(1.0, max(0.0, c3) / 0.30)
            + 0.35 * min(1.0, max(0.0, vr - 1.0) / 4.0)
            + 0.25 * max(0.0, min(1.0, (br - 0.5) / 0.35)),
        )
        if c3 >= 0.12 and vr >= 1.8 and br >= 0.56 and score >= 0.50:
            signal = "PUMP_NOW"
        elif events >= 2:
            signal = "PUMP_HISTORY"
        else:
            signal = "NORMAL"
        return {
            "pump_events": events,
            "pump_score": round(score, 3),
            "signal": signal,
            "pulse_change_3s_pct": round(c3, 4),
            "pulse_volume_ratio": round(vr, 2),
            "hold_seconds": 20 if signal == "PUMP_NOW" else 180,
        }

    def _three_min_metrics(self, symbol: str, price: float) -> dict[str, float]:
        with self.lock:
            bars = list(self.bars.get(symbol, ()))
        if not bars or price <= 0:
            return {"change_3m_pct": 0.0, "volume_ratio": 1.0}
        current = bars[-1]
        open_price = float(current["open"] or 0)
        change = (price / open_price - 1.0) * 100.0 if open_price > 0 else 0.0
        previous_volumes = [
            float(x["quote_volume"] or 0) for x in bars[-6:-1]
            if float(x["quote_volume"] or 0) > 0
        ]
        baseline = median(previous_volumes) if previous_volumes else 0.0
        current_volume = float(current["quote_volume"] or 0)
        volume_ratio = current_volume / baseline if baseline > 0 else 1.0
        return {"change_3m_pct": round(change, 4), "volume_ratio": round(volume_ratio, 2)}

    def snapshot(self, limit: int = 20) -> list[dict[str, Any]]:
        self.start()
        if not self._ready.wait(timeout=8.0):
            return []
        with self.lock:
            items = list(self.tickers.items())
        items = [(s, d) for s, d in items if s.endswith("USDT") and s[:-4] not in STABLE_BASES]
        items.sort(key=lambda x: float(x[1].get("q", 0) or 0), reverse=True)
        rows: list[dict[str, Any]] = []
        for s, d in items[: max(5, min(limit, self.top_n))]:
            price = float(d.get("c", 0) or 0)
            if price <= 0:
                continue
            open_24h = float(d.get("o", price) or price)
            pct_24h = (price / open_24h - 1.0) * 100.0 if open_24h > 0 else 0.0
            volume_24h = float(d.get("q", 0) or 0)
            tf = self._three_min_metrics(s, price)
            pm = self._pulse(s)
            liquidity = min(1.0, max(0.0, math.log10(max(volume_24h, 1.0)) / 8.0))
            momentum = min(1.0, max(0.0, pct_24h) / 20.0)
            short_momentum = min(1.0, max(0.0, tf["change_3m_pct"]) / 1.2)
            score = 100.0 * (0.35 * pm["pump_score"] + 0.25 * momentum + 0.25 * liquidity + 0.15 * short_momentum)
            entry = price
            target_pct = min(0.012, max(0.0035, abs(tf["change_3m_pct"]) / 100.0 * (1.25 if pm["signal"] == "PUMP_NOW" else 0.8)))
            stop_pct = 0.006 if pm["signal"] == "PUMP_NOW" else 0.004
            rows.append({
                "symbol": s[:-4] + "/USDT",
                "price": price,
                "change_24h_pct": round(pct_24h, 3),
                "quote_volume_24h": volume_24h,
                "score": round(score, 2),
                "estimated_entry": entry,
                "estimated_exit": entry * (1.0 + target_pct),
                "estimated_stop": entry * (1.0 - stop_pct),
                **tf,
                **pm,
            })
        rows.sort(key=lambda x: (x["score"], x["quote_volume_24h"]), reverse=True)
        return rows[: max(5, min(limit, self.top_n))]


RADAR = MarketRadar(20)
# Start the market stream as the web service starts; the dashboard never
# depends on a user click to initialize market data.
RADAR.start()
