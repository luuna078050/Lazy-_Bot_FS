"""3-minute order-book wall dynamics for Fast Scalper.

Adds dynamic microstructure: wall migration, absorption/removal, breakout
confirmation and retest detection. It remains additive to the existing radar.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit, urlunsplit


def install() -> None:
    from .market_radar import MarketRadar
    if getattr(MarketRadar, "_wall_dynamics_v1", False):
        return
    MarketRadar._wall_dynamics_v1 = True
    original_init = MarketRadar.__init__
    original_build_url = MarketRadar._build_url
    original_on_message = MarketRadar._on_message
    original_timeframe_metrics = MarketRadar._timeframe_metrics
    original_opportunity_score = MarketRadar._opportunity_score

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.wall_history = defaultdict(lambda: deque(maxlen=240))
        self.wall_latest = {}
        self._current_scoring_symbol = ""
        self._current_scoring_price = 0.0

    def build_url(self):
        url = original_build_url(self)
        try:
            parts = urlsplit(url)
            marker = "/stream?streams="
            if marker not in parts.path:
                return url
            base = parts.path.split(marker, 1)[1].split("/")
            existing = set(base)
            for s in self._top_symbols():
                stream = f"{s.lower()}@depth20@100ms"
                if stream not in existing:
                    base.append(stream)
            return urlunsplit((parts.scheme, parts.netloc, marker + "/".join(base), parts.query, parts.fragment))
        except Exception:
            return url

    def record_depth(self, data):
        symbol = str(data.get("s", "")).upper()
        bids = data.get("b") or data.get("bids") or []
        asks = data.get("a") or data.get("asks") or []
        if not symbol or not bids or not asks:
            return
        try:
            bid_levels = [(float(x[0]), float(x[1])) for x in bids if float(x[0]) > 0 and float(x[1]) > 0]
            ask_levels = [(float(x[0]), float(x[1])) for x in asks if float(x[0]) > 0 and float(x[1]) > 0]
            if not bid_levels or not ask_levels:
                return
            best_bid = max(p for p, _ in bid_levels); best_ask = min(p for p, _ in ask_levels)
            mid = (best_bid + best_ask) / 2
            bid_wall = max(bid_levels, key=lambda x: x[0] * x[1]); ask_wall = max(ask_levels, key=lambda x: x[0] * x[1])
            point = {"ts": time.time(), "best_bid": best_bid, "best_ask": best_ask, "mid": mid,
                     "bid_wall_price": bid_wall[0], "bid_wall_quote": bid_wall[0] * bid_wall[1],
                     "ask_wall_price": ask_wall[0], "ask_wall_quote": ask_wall[0] * ask_wall[1]}
            with self.lock:
                hist = self.wall_history[symbol]
                if hist and point["ts"] - hist[-1]["ts"] < 0.8: hist[-1] = point
                else: hist.append(point)
                self.wall_latest[symbol] = point
        except (TypeError, ValueError, IndexError):
            return

    def on_message(self, ws, raw):
        try:
            msg = json.loads(raw); data = msg.get("data", msg)
            if isinstance(data, dict) and data.get("e") == "depthUpdate": record_depth(self, data)
        except Exception:
            pass
        return original_on_message(self, ws, raw)

    def wall_metrics(self, symbol, price):
        now = time.time()
        with self.lock: hist = [x for x in self.wall_history.get(symbol, ()) if now - x["ts"] <= 180]
        empty = {"wall_score": 0.5, "wall_direction": "neutral", "support_wall_price": None,
                 "resistance_wall_price": None, "support_shift_3m_pct": 0.0,
                 "resistance_shift_3m_pct": 0.0, "ask_wall_absorption": 0.0,
                 "bid_wall_strength": 0.0, "breakout_confirmed": False,
                 "retest_confirmed": False, "wall_persistence": 0.0}
        if not hist or price <= 0: return empty
        first, last = hist[0], hist[-1]
        def pct(a, b): return ((b / a) - 1.0) * 100 if a else 0.0
        support_shift = pct(first["bid_wall_price"], last["bid_wall_price"])
        resistance_shift = pct(first["ask_wall_price"], last["ask_wall_price"])
        prev_ask_max = max((x["ask_wall_quote"] for x in hist[:-1]), default=last["ask_wall_quote"])
        prev_bid_max = max((x["bid_wall_quote"] for x in hist[:-1]), default=last["bid_wall_quote"])
        ask_absorption = max(0.0, min(1.0, 1.0 - last["ask_wall_quote"] / prev_ask_max)) if prev_ask_max else 0.0
        bid_strength = max(0.0, min(1.0, last["bid_wall_quote"] / prev_bid_max)) if prev_bid_max else 0.0
        breakout = False; breakout_level = None
        for i in range(1, len(hist)):
            if hist[i-1]["mid"] <= hist[i-1]["ask_wall_price"] and hist[i]["mid"] > hist[i]["ask_wall_price"]:
                breakout = True; breakout_level = hist[i-1]["ask_wall_price"]
        retest = bool(breakout and breakout_level and price >= breakout_level and abs(price / breakout_level - 1) <= 0.0015)
        support_up = max(0.0, min(1.0, support_shift / 0.5))
        resistance_pressure = max(0.0, min(1.0, -resistance_shift / 0.5))
        raw = 0.5 + 0.22*support_up + 0.18*ask_absorption + 0.10*bid_strength + (0.25 if breakout else 0.0) + (0.15 if retest else 0.0) - 0.20*resistance_pressure
        score = max(0.0, min(1.0, raw))
        direction = "bullish" if score >= 0.62 else "bearish" if score <= 0.38 else "neutral"
        return {"wall_score": round(score,4), "wall_direction": direction,
                "support_wall_price": last["bid_wall_price"], "resistance_wall_price": last["ask_wall_price"],
                "support_shift_3m_pct": round(support_shift,5), "resistance_shift_3m_pct": round(resistance_shift,5),
                "ask_wall_absorption": round(ask_absorption,4), "bid_wall_strength": round(bid_strength,4),
                "breakout_confirmed": breakout, "retest_confirmed": retest,
                "wall_persistence": round(min(1.0, len(hist)/180.0),4)}

    def timeframe_metrics(self, symbol, price):
        self._current_scoring_symbol = symbol
        self._current_scoring_price = price
        return original_timeframe_metrics(self, symbol, price)

    def opportunity_score(self, hot, tf, pulse, liquidity, pct24):
        base_score, components = original_opportunity_score(self, hot, tf, pulse, liquidity, pct24)
        wall = self.wall_metrics(self._current_scoring_symbol, self._current_scoring_price)
        components = dict(components); components.update(wall)
        score = 100.0 * (0.88 * base_score / 100.0 + 0.12 * wall["wall_score"])
        return round(self._clamp(score, 0, 100), 2), components

    MarketRadar.__init__ = init
    MarketRadar._build_url = build_url
    MarketRadar._on_message = on_message
    MarketRadar._timeframe_metrics = timeframe_metrics
    MarketRadar._wall_metrics = wall_metrics
    MarketRadar._opportunity_score = opportunity_score

    def wall_snapshot(self, symbol: str, price: float | None = None):
        s = str(symbol).upper().replace("/", "")
        if not s.endswith("USDT"): s += "USDT"
        if price is None:
            with self.lock: price = float(self.tickers.get(s, {}).get("c", 0) or 0)
        return self._wall_metrics(s, float(price or 0))
    MarketRadar.wall_snapshot = wall_snapshot
