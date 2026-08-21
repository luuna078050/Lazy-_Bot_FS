from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ScalperConfig:
    entry_timeframes: tuple = ("1m", "3m", "5m")
    context_timeframes: tuple = ("10m", "15m", "30m", "1h", "4h")
    candidate_limit: int = 10
    active_symbols: int = 5
    capital_modes: tuple = (0.10, 0.20, 0.30)
    target_opportunity_pct: float = 0.20


@dataclass
class Opportunity:
    symbol: str
    score: float
    expected_move_pct: float
    mode_fraction: float
    reason: str


class ScalperEngine:
    """Multi-pair fast scalper decision layer.

    It observes continuously, trades only when the complete evidence set agrees,
    and treats 1m/3m/5m as execution timeframes rather than mandatory holding times.
    """

    def __init__(self, config: Optional[ScalperConfig] = None):
        self.config = config or ScalperConfig()

    def select_opportunities(self, ranked_symbols: List[Opportunity]) -> List[Opportunity]:
        eligible = [x for x in ranked_symbols if x.expected_move_pct > 0 and x.score >= 0.70]
        return sorted(eligible, key=lambda x: x.score, reverse=True)[: self.config.active_symbols]

    def should_reenter_after_retracement(self, peak_price: float, current_price: float,
                                         retracement_pct: float, confirmation_score: float) -> bool:
        if peak_price <= 0 or current_price >= peak_price:
            return False
        actual = (peak_price - current_price) / peak_price
        return 0.01 <= actual <= retracement_pct and confirmation_score >= 0.75

    def choose_capital_fraction(self, score: float) -> float:
        if score >= 0.90:
            return self.config.capital_modes[2]
        if score >= 0.80:
            return self.config.capital_modes[1]
        if score >= 0.70:
            return self.config.capital_modes[0]
        return 0.0
