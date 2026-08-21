from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class IncomeConfig:
    starting_capital_usdt: float = 1000.0
    monthly_profit_target_usdt: float = 750.0
    weekly_review: bool = True
    timeframes: tuple = ("3m", "5m", "10m", "15m")
    max_risk_per_trade_pct: float = 0.50
    reinvest_profit: bool = False
    scalper_funding_usdt: float = 100.0


@dataclass
class IncomeDecision:
    trade: bool
    regime: str
    score: float
    reason: str


class IncomeEngine:
    """Income-oriented strategy: preserve working capital and withdraw profit.

    The $700-$800/month objective is a target scenario, not a guaranteed return.
    No trade is forced to satisfy a calendar target.
    """

    def __init__(self, config: Optional[IncomeConfig] = None):
        self.config = config or IncomeConfig()

    def decide(self, score: float, regime: str, risk_ok: bool) -> IncomeDecision:
        trade = risk_ok and score >= 0.80 and regime not in {"chaotic", "uncertain"}
        reason = "qualified opportunity" if trade else "no sufficiently strong risk-adjusted edge"
        return IncomeDecision(trade, regime, score, reason)

    def weekly_report(self, realized_profit: float, capital: float) -> Dict[str, float]:
        return {
            "capital": capital,
            "realized_profit": realized_profit,
            "monthly_target": self.config.monthly_profit_target_usdt,
            "target_progress": realized_profit / self.config.monthly_profit_target_usdt,
        }

    def transfer_to_scalper(self, realized_profit: float) -> float:
        return min(self.config.scalper_funding_usdt, max(0.0, realized_profit))
