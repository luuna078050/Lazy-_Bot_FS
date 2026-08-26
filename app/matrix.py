from dataclasses import dataclass
from time import time

from .config import SETTINGS

@dataclass
class Candidate:
    symbol: str
    score: float
    signal: str = "WAIT"
    hot: float = 0.0
    flow: float = 0.0
    change_1m: float = 0.0
    change_3m: float = 0.0
    change_5m: float = 0.0
    price: float = 0.0

class RankingMatrix:
    """Pure ranking layer. No orders, balance mutations or UI side effects."""
    def rank(self, candidates: list[Candidate]) -> list[Candidate]:
        return sorted(candidates, key=lambda x: x.score, reverse=True)[:SETTINGS.max_pairs]

    def blocks(self, candidates: list[Candidate]) -> list[list[Candidate]]:
        ranked = self.rank(candidates)
        return [ranked[:5], ranked[5:10]]

class PortfolioAllocation:
    def auto(self, candidates: list[Candidate], capital: float) -> dict[str, float]:
        ranked = RankingMatrix().rank(candidates)
        if not ranked or capital <= 0:
            return {}
        weights = [max(0.01, c.score) for c in ranked]
        total = sum(weights)
        return {c.symbol: capital * w / total for c, w in zip(ranked, weights)}

    def manual(self, allocations: dict[str, float], capital: float) -> dict[str, float]:
        clean = {k: max(0.0, float(v)) for k, v in allocations.items() if float(v) > 0}
        total = sum(clean.values())
        if total > capital + 1e-9:
            raise ValueError("Ручное распределение превышает доступный капитал")
        return clean

class MinuteThroughput:
    def __init__(self):
        self.closes: list[tuple[float, float]] = []

    def record(self, net_pnl: float) -> None:
        self.closes.append((time(), float(net_pnl)))
        self._trim()

    def _trim(self) -> None:
        cutoff = time() - SETTINGS.window_seconds
        self.closes = [(ts, pnl) for ts, pnl in self.closes if ts >= cutoff]

    def pnl_last_minute(self) -> float:
        self._trim()
        return sum(pnl for _, pnl in self.closes)

    def target_for(self, capital: float) -> float:
        return capital * SETTINGS.target_pnl_per_min_per_100 / 100.0
