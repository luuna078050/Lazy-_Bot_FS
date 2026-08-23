"""Sub-second/one-second market pulse for LazyBot FS Rocket Hunter.

The normal 3m/1m analysis remains the strategic layer. This module is the
microstructure trigger layer: Binance public websocket trades are aggregated
into one-second buckets so a 2-3 second acceleration is not invisible between
slow REST scans.

It never bypasses risk controls. A pulse can promote a candidate to
EARLY_ROCKET/IGNITION, but execution still requires the normal capital and
live-trading guards.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Iterable

try:
    import websocket
except ImportError:  # pragma: no cover - dependency guard
    websocket = None


@dataclass
class Pulse:
    symbol: str
    ts: float
    price: float
    price_change_1s: float
    price_change_2s: float
    price_change_3s: float
    quote_volume_1s: float
    volume_ratio: float
    buy_ratio: float
    trade_count: int
    spread_pct: float = 0.0
    score: float = 0.0
    state: str = "WAIT"


class RealtimePulse:
    """Maintain one-second pulse state for a configurable Binance spot universe."""

    def __init__(self, symbols: Iterable[str], window_seconds: int = 12):
        self.symbols = [s.upper().replace("/", "") for s in symbols]
        self.window_seconds = max(6, window_seconds)
        self._lock = threading.Lock()
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window_seconds + 2))
        self._current: Dict[str, dict] = {}
        self._latest: Dict[str, Pulse] = {}
        self._thread = None
        self._stop = threading.Event()
        self._ws = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if websocket is None:
            raise RuntimeError("websocket-client is required for realtime pulse")
        self._thread = threading.Thread(target=self._run, name="lazybot-realtime-pulse", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def snapshot(self, symbol: str | None = None):
        with self._lock:
            if symbol:
                p = self._latest.get(symbol.upper().replace("/", ""))
                return None if p is None else p.__dict__.copy()
            return {k: v.__dict__.copy() for k, v in self._latest.items()}

    def _run(self):
        streams = "/".join(f"{s.lower()}@aggTrade" for s in self.symbols)
        url = "wss://stream.binance.com:9443/stream?streams=" + streams
        while not self._stop.is_set():
            try:
                self._ws = websocket.WebSocketApp(url, on_message=self._on_message)
                self._ws.run_forever(ping_interval=15, ping_timeout=10)
            except Exception:
                pass
            if not self._stop.is_set():
                time.sleep(1.0)

    def _on_message(self, _ws, raw):
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)
            symbol = str(data.get("s", "")).upper()
            if not symbol:
                return
            price = float(data.get("p", 0.0))
            qty = float(data.get("q", 0.0))
            # Binance aggTrade `m=True` means buyer is market maker, so the
            # aggressive taker side is sell. Therefore m=False contributes to buy ratio.
            is_buy = not bool(data.get("m", False))
            now = time.time()
            sec = int(now)
            with self._lock:
                bucket = self._current.get(symbol)
                if bucket is None or bucket["sec"] != sec:
                    if bucket is not None:
                        self._finalize(symbol, bucket)
                    bucket = {"sec": sec, "price": price, "quote_volume": 0.0, "buy_quote": 0.0, "trades": 0}
                    self._current[symbol] = bucket
                bucket["price"] = price
                quote = price * qty
                bucket["quote_volume"] += quote
                bucket["buy_quote"] += quote if is_buy else 0.0
                bucket["trades"] += 1
        except Exception:
            return

    def _finalize(self, symbol: str, bucket: dict):
        history = self._history[symbol]
        previous_volume = sum(x["quote_volume"] for x in list(history)[-5:]) / max(1, min(5, len(history)))
        item = {"ts": float(bucket["sec"]), "price": bucket["price"], "quote_volume": bucket["quote_volume"], "buy_quote": bucket["buy_quote"], "trades": bucket["trades"]}
        history.append(item)
        prices = [x["price"] for x in history]
        def ch(n):
            if len(prices) <= n or prices[-1] <= 0:
                return 0.0
            return prices[-1] / prices[-1 - n] - 1.0
        vol_ratio = bucket["quote_volume"] / previous_volume if previous_volume > 0 else 1.0
        buy_ratio = bucket["buy_quote"] / bucket["quote_volume"] if bucket["quote_volume"] > 0 else 0.5
        c1, c2, c3 = ch(1), ch(2), ch(3)
        # Fast-pump score. Thresholds are intentionally demanding: this layer
        # is for a genuine short burst, not ordinary one-second noise.
        accel = max(0.0, c1 * 10000) + max(0.0, c2 * 5000) + max(0.0, c3 * 2500)
        vol_component = min(1.0, max(0.0, (vol_ratio - 1.0) / 4.0))
        buy_component = max(0.0, min(1.0, (buy_ratio - 0.5) / 0.35))
        score = max(0.0, min(1.0, 0.45 * min(1.0, accel / 6.0) + 0.30 * vol_component + 0.25 * buy_component))
        if c1 >= 0.0012 and c2 >= 0.0018 and vol_ratio >= 2.0 and buy_ratio >= 0.58 and score >= 0.62:
            state = "IGNITION"
        elif c1 >= 0.0006 and vol_ratio >= 1.5 and buy_ratio >= 0.55 and score >= 0.45:
            state = "EARLY_ROCKET"
        elif c1 < -0.0010 and c2 < -0.0015:
            state = "FADE"
        else:
            state = "WAIT"
        self._latest[symbol] = Pulse(symbol, time.time(), prices[-1], c1, c2, c3, bucket["quote_volume"], vol_ratio, buy_ratio, bucket["trades"], 0.0, score, state)


def discover_usdt_symbols(limit: int = 30) -> list[str]:
    """Return liquid Binance USDT spot symbols for the realtime stream."""
    try:
        with urllib.request.urlopen("https://api.binance.com/api/v3/ticker/24hr", timeout=5) as r:
            rows = json.loads(r.read().decode())
        rows = [r for r in rows if r.get("symbol", "").endswith("USDT") and not r.get("symbol", "").startswith(("USDT", "USDC", "FDUSD"))]
        rows.sort(key=lambda r: float(r.get("quoteVolume") or 0), reverse=True)
        return [r["symbol"] for r in rows[:limit]]
    except Exception:
        return []
