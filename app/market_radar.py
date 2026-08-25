"""Binance WebSocket market radar for Fast Skalper.

Ranking is calculated locally from Binance public WebSocket market data.
The ranking is intentionally a *hot-market opportunity score*, not a claim
that Binance publishes the same score. Binance's live market activity is used
as the input layer; Fast Skalper adds its own quality/risk matrix on top.
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
        self.pulses = defaultdict(lambda: deque(maxlen=60))
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
        self._thread = threading.Thread(target=self._run, daemon=True, name="fast-scalper-market-radar")
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
                if s.endswith("USDT") and s[:-4] not in STABLE_BASES
                and float(d.get("q", 0) or 0) >= 10_000
            ]
        rows.sort(key=lambda x: float(x[1].get("q", 0) or 0), reverse=True)
        return [s for s, _ in rows[: self.top_n]] or FALLBACK[: self.top_n]

    def _build_url(self) -> str:
        symbols = self._top_symbols()
        streams = ["!miniTicker@arr"]
        streams += [f"{s.lower()}@kline_3m" for s in symbols]
        streams += [f"{s.lower()}@aggTrade" for s in symbols]
        return "wss://stream.binance.com:443/stream?streams=" + "/".join(streams)

    def _run(self) -> None:
        while not self._stop.is_set():
            url = self._build_url()
            self.connection_url = url
            try:
                self._ws = websocket.WebSocketApp(
                    url, on_open=self._on_open, on_message=self._on_message,
                    on_error=self._on_error, on_close=self._on_close,
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
            if not self._ready.is_set() and s.endswith("USDT") and s[:-4] not in STABLE_BASES:
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
        sec = int(time.time())
        buy = not bool(d.get("m", False))
        quote = p * q
        with self.lock:
            h = self.pulses[s]
            if h and h[-1]["sec"] == sec:
                bucket = h[-1]
            else:
                bucket = {"sec": sec, "price": p, "quote": 0.0, "buy_quote": 0.0, "trades": 0}
                h.append(bucket)
            bucket["price"] = p
            bucket["quote"] += quote
            bucket["buy_quote"] += quote if buy else 0.0
            bucket["trades"] += 1

    @staticmethod
    def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return min(hi, max(lo, float(v)))

    def _pulse(self, symbol: str) -> dict[str, Any]:
        with self.lock:
            h = list(self.pulses.get(symbol, ()))
        if not h:
            return {"pump_events": 0, "pump_score": 0.0, "signal": "WAIT",
                    "pulse_change_3s_pct": 0.0, "pulse_volume_ratio": 1.0,
                    "buy_ratio": 0.5, "hold_seconds": 180}
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
        score = min(1.0, 0.40 * self._clamp(max(0.0, c3) / 0.30)
                    + 0.35 * self._clamp(max(0.0, vr - 1.0) / 4.0)
                    + 0.25 * self._clamp((br - 0.5) / 0.35))
        if c3 >= 0.12 and vr >= 1.8 and br >= 0.56 and score >= 0.50:
            signal = "PUMP_NOW"
        elif events >= 2:
            signal = "PUMP_HISTORY"
        else:
            signal = "NORMAL"
        return {"pump_events": events, "pump_score": round(score, 3), "signal": signal,
                "pulse_change_3s_pct": round(c3, 4), "pulse_volume_ratio": round(vr, 2),
                "buy_ratio": round(br, 4), "hold_seconds": 20 if signal == "PUMP_NOW" else 180}

    def _timeframe_metrics(self, symbol: str, price: float) -> dict[str, float]:
        with self.lock:
            bars = list(self.bars.get(symbol, ()))
        if not bars or price <= 0:
            return {"change_1m_pct": 0.0, "change_3m_pct": 0.0, "change_5m_pct": 0.0,
                    "volume_ratio": 1.0, "volume_surge": 0.0, "stability": 0.0}
        # The stream is 3m candles; use current candle plus recent 3m candles
        # to derive comparable 1m/3m/5m proxies without REST polling.
        closes = [float(x["close"] or 0) for x in bars if float(x["close"] or 0) > 0]
        current = bars[-1]
        base3 = float(current["open"] or price)
        change3 = (price / base3 - 1.0) * 100.0 if base3 > 0 else 0.0
        change5 = ((price / closes[-2]) - 1.0) * 100.0 if len(closes) >= 2 and closes[-2] > 0 else change3
        change1 = change3 / 3.0
        prev_vol = [float(x["quote_volume"] or 0) for x in bars[-6:-1] if float(x["quote_volume"] or 0) > 0]
        baseline = median(prev_vol) if prev_vol else 0.0
        current_volume = float(current["quote_volume"] or 0)
        vr = current_volume / baseline if baseline > 0 else 1.0
        volume_surge = self._clamp((vr - 1.0) / 3.0)
        recent_changes = []
        for i in range(max(1, len(closes) - 5), len(closes)):
            if closes[i - 1] > 0:
                recent_changes.append(closes[i] / closes[i - 1] - 1.0)
        if len(recent_changes) >= 2:
            avg = sum(recent_changes) / len(recent_changes)
            variance = sum((x - avg) ** 2 for x in recent_changes) / len(recent_changes)
            stability = self._clamp(1.0 - math.sqrt(variance) / 0.01)
        else:
            stability = 0.0
        return {"change_1m_pct": round(change1, 4), "change_3m_pct": round(change3, 4),
                "change_5m_pct": round(change5, 4), "volume_ratio": round(vr, 2),
                "volume_surge": round(volume_surge, 4), "stability": round(stability, 4)}

    def _hot_market_score(self, pct24: float, tf: dict[str, float], pulse: dict[str, Any], liquidity: float) -> float:
        # Proxy for Binance's hot/trending idea using the live Binance stream.
        # It is deliberately labelled as a proxy, not as Binance's proprietary rank.
        trend24 = self._clamp(max(0.0, pct24) / 12.0)
        short = self._clamp(max(0.0, tf["change_3m_pct"]) / 1.0)
        flow = self._clamp((pulse["buy_ratio"] - 0.50) / 0.18)
        surge = tf["volume_surge"]
        pulse_now = 1.0 if pulse["signal"] == "PUMP_NOW" else (0.55 if pulse["signal"] == "PUMP_HISTORY" else 0.0)
        return self._clamp(0.25 * trend24 + 0.25 * short + 0.20 * flow + 0.20 * surge + 0.10 * pulse_now)

    def _opportunity_score(self, hot: float, tf: dict[str, float], pulse: dict[str, Any], liquidity: float,
                           pct24: float) -> tuple[float, dict[str, float]]:
        # Final matrix: Hot/Trending 15, 1-3m momentum 15, acceleration 10,
        # buy/sell flow 15, volume surge 15, liquidity 8, stability 7,
        # risk/reward quality 10, 24h trend 5.
        momentum = self._clamp(max(0.0, tf["change_3m_pct"]) / 1.0)
        acceleration = self._clamp((tf["change_3m_pct"] - tf["change_5m_pct"] * 0.6) / 0.8)
        flow = self._clamp((pulse["buy_ratio"] - 0.50) / 0.18)
        surge = tf["volume_surge"]
        stability = tf["stability"]
        trend = self._clamp(max(0.0, pct24) / 12.0)
        # Reward movement with confirmation; penalize weak stability and overly stretched moves.
        extension_penalty = self._clamp(max(0.0, abs(tf["change_3m_pct"]) - 1.2) / 1.5)
        rr_quality = self._clamp(0.65 * (1.0 - extension_penalty) + 0.35 * stability)
        components = {
            "hot": hot, "momentum": momentum, "acceleration": acceleration,
            "flow": flow, "volume_surge": surge, "liquidity": liquidity,
            "stability": stability, "risk_reward": rr_quality, "trend_24h": trend,
        }
        score = 100.0 * (
            0.15 * hot + 0.15 * momentum + 0.10 * acceleration + 0.15 * flow
            + 0.15 * surge + 0.08 * liquidity + 0.07 * stability
            + 0.10 * rr_quality + 0.05 * trend
        )
        return round(self._clamp(score, 0, 100), 2), components

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
            open24 = float(d.get("o", price) or price)
            pct24 = (price / open24 - 1.0) * 100.0 if open24 > 0 else 0.0
            volume24 = float(d.get("q", 0) or 0)
            liquidity = self._clamp(math.log10(max(volume24, 1.0)) / 8.0)
            tf = self._timeframe_metrics(s, price)
            pulse = self._pulse(s)
            hot = self._hot_market_score(pct24, tf, pulse, liquidity)
            score, components = self._opportunity_score(hot, tf, pulse, liquidity, pct24)
            entry = price
            # Conservative estimate for a 3m scalp; never present this as guaranteed profit.
            target_pct = min(0.012, max(0.0025, abs(tf["change_3m_pct"]) / 100.0 * (1.10 if pulse["signal"] == "PUMP_NOW" else 0.75)))
            stop_pct = 0.006 if pulse["signal"] == "PUMP_NOW" else 0.004
            rows.append({
                "symbol": s[:-4] + "/USDT", "price": price,
                "change_24h_pct": round(pct24, 3), "quote_volume_24h": volume24,
                "score": score, "hot_market_score": round(hot * 100, 2),
                "ranking_components": components,
                "estimated_entry": entry,
                "estimated_exit": entry * (1.0 + target_pct),
                "estimated_stop": entry * (1.0 - stop_pct),
                "estimated_target_pct": round(target_pct * 100, 4),
                **tf, **pulse,
            })
        rows.sort(key=lambda x: (x["score"], x["hot_market_score"], x["quote_volume_24h"]), reverse=True)
        return rows[: max(5, min(limit, self.top_n))]


RADAR = MarketRadar(20)
RADAR.start()


def _boot_radar_check() -> None:
    def _check() -> None:
        try:
            rows = RADAR.snapshot(20)
            top = rows[0]["symbol"] if rows else "NONE"
            print(f"RADAR_RANKING_READY count={len(rows)} top={top}", flush=True)
        except Exception as exc:
            print(f"RADAR_RANKING_ERROR {str(exc)[:300]}", flush=True)
    threading.Thread(target=_check, daemon=True, name="radar-boot-check").start()


_boot_radar_check()
