"""Order-book pressure and wall dynamics for Lazy Bot Scalper.

A large order is evidence, not truth. The analyzer scores weighted depth,
relative wall size, persistence and wall movement. A wall that disappears
before price reaches it increases spoof-risk instead of being treated as real
support/resistance.
"""
from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass
from time import time
from typing import Iterable, Sequence

Level = tuple[float, float]

@dataclass(frozen=True)
class Wall:
    side: str
    price: float
    amount: float
    relative_size: float
    distance_pct: float

@dataclass(frozen=True)
class OrderBookSignal:
    direction: str
    score: float
    confidence: float
    bid_ask_imbalance: float
    nearest_bid_wall: Wall | None
    nearest_ask_wall: Wall | None
    spoof_risk: float
    persistence: float

class OrderBookAnalyzer:
    def __init__(self, history_size: int = 20, wall_multiplier: float = 3.0):
        self.history_size = max(3, history_size)
        self.wall_multiplier = max(1.5, wall_multiplier)
        self._history: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=self.history_size))

    @staticmethod
    def _clean(levels: Iterable[Sequence[float]]) -> list[Level]:
        out: list[Level] = []
        for row in levels:
            try:
                price, amount = float(row[0]), float(row[1])
                if price > 0 and amount >= 0: out.append((price, amount))
            except (TypeError, ValueError, IndexError):
                continue
        return out

    def _walls(self, side: str, levels: list[Level], mid: float) -> list[Wall]:
        amounts = sorted(a for _, a in levels if a > 0)
        if not amounts or mid <= 0: return []
        median = amounts[len(amounts) // 2]
        threshold = median * self.wall_multiplier
        return sorted([Wall(side, price, amount, amount / median, abs(price - mid) / mid * 100)
                       for price, amount in levels if amount >= threshold], key=lambda w: w.distance_pct)

    @staticmethod
    def _weighted_volume(levels: list[Level], mid: float) -> float:
        return sum(amount / (1.0 + abs(price - mid) / mid * 100.0) for price, amount in levels) if mid else 0.0

    def analyze(self, symbol: str, bids: Iterable[Sequence[float]], asks: Iterable[Sequence[float]], timestamp: float | None = None) -> OrderBookSignal:
        bids_c, asks_c = self._clean(bids), self._clean(asks)
        if not bids_c or not asks_c: raise ValueError("Both bids and asks are required")
        best_bid, best_ask = max(p for p, _ in bids_c), min(p for p, _ in asks_c)
        mid = (best_bid + best_ask) / 2
        bv, av = self._weighted_volume(bids_c, mid), self._weighted_volume(asks_c, mid)
        imbalance = (bv - av) / (bv + av) if bv + av else 0.0
        bid_walls, ask_walls = self._walls("bid", bids_c, mid), self._walls("ask", asks_c, mid)
        history = self._history[symbol]
        previous = history[-1] if history else None
        previous_walls = previous.get("walls", {}) if previous else {}
        current_walls = {(w.side, round(w.price, 12)): w.amount for w in bid_walls + ask_walls}
        disappeared = 0.0
        if previous_walls:
            prev_total = sum(previous_walls.values()) or 1.0
            disappeared = sum(a for k, a in previous_walls.items() if k not in current_walls) / prev_total
        spoof_risk = min(1.0, disappeared * 1.5)
        persistence = min(len(history) + 1, self.history_size) / self.history_size
        wall_bias = 0.0
        if bid_walls: wall_bias += min(0.35, max(0.0, bid_walls[0].relative_size - 1) / 20)
        if ask_walls: wall_bias -= min(0.35, max(0.0, ask_walls[0].relative_size - 1) / 20)
        score = max(-1.0, min(1.0, imbalance * 0.75 + wall_bias * 0.25)) * (1.0 - spoof_risk * 0.6)
        direction = "bullish" if score > 0.18 else "bearish" if score < -0.18 else "neutral"
        confidence = min(1.0, abs(score) * 1.25 + persistence * 0.15)
        history.append({"ts": timestamp or time(), "walls": current_walls, "score": score})
        return OrderBookSignal(direction, round(score, 4), round(confidence, 4), round(imbalance, 4),
                               bid_walls[0] if bid_walls else None, ask_walls[0] if ask_walls else None,
                               round(spoof_risk, 4), round(persistence, 4))

orderbook_analyzer = OrderBookAnalyzer()

def analyze_orderbook(symbol: str, order_book: dict, timestamp: float | None = None) -> dict:
    signal = orderbook_analyzer.analyze(symbol, order_book.get("bids", []), order_book.get("asks", []), timestamp)
    result = signal.__dict__.copy()
    result["nearest_bid_wall"] = signal.nearest_bid_wall.__dict__ if signal.nearest_bid_wall else None
    result["nearest_ask_wall"] = signal.nearest_ask_wall.__dict__ if signal.nearest_ask_wall else None
    return result
