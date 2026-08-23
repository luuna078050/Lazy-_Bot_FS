"""Configuration and validation for the 3-minute Fast Scalper UI."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class FastScalperConfig:
    capital_usdt: float = 100.0
    symbols: tuple[str, ...] = ("DGB/USDT", "ZRO/USDT", "TUT/USDT")
    allocations_pct: tuple[float, ...] = (30.0, 30.0, 40.0)
    timeframe: str = "3m"
    max_trade_seconds: int = 180
    min_profit_usdt: float = 0.20
    target_profit_usdt: float = 0.30
    stop_loss_enabled: bool = True
    stop_loss_pct: float = 0.50

def validate(cfg: FastScalperConfig) -> None:
    if cfg.capital_usdt <= 0: raise ValueError("capital_usdt must be positive")
    if len(cfg.symbols) != len(cfg.allocations_pct): raise ValueError("symbols and allocations must have equal length")
    if not 2 <= len(cfg.symbols) <= 3: raise ValueError("Fast Scalper supports 2 or 3 pairs")
    if abs(sum(cfg.allocations_pct) - 100.0) > 1e-9: raise ValueError("allocations must total 100%")
    if any(x <= 0 for x in cfg.allocations_pct): raise ValueError("each allocation must be positive")
    if cfg.timeframe != "3m": raise ValueError("Fast Scalper test profile is fixed to 3m")
    if cfg.max_trade_seconds != 180: raise ValueError("3m profile uses a 180-second trade budget")
    if cfg.min_profit_usdt <= 0 or cfg.target_profit_usdt < cfg.min_profit_usdt: raise ValueError("invalid profit thresholds")

def recommended_profit(capital_usdt: float, round_trip_fee_pct: float = 0.0) -> dict:
    fee = max(0.0, capital_usdt) * max(0.0, round_trip_fee_pct) / 100.0
    minimum = max(0.20, fee * 3.0)
    target = max(0.30, fee * 4.0)
    return {"minimum_profit_usdt": round(minimum, 4), "target_profit_usdt": round(target, 4), "estimated_fee_usdt": round(fee, 4)}
