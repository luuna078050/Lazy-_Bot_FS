"""Profit/time targeting for the Lazy Scalper.

The user controls the strategy in money and time rather than percentages:
- target profit per one unit of allocated capital;
- minimum acceptable profit per one unit when the target interval is reached;
- desired interval between completed trades;
- maximum holding time for a still-valid position.

The interval is a throughput target, not a promise: the bot must not invent
trades just to satisfy a clock. Multi-pair scanning is used to increase the
chance of meeting the target without forcing a bad entry.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProfitTimeProfile:
    target_profit_per_unit: float = 0.25
    minimum_profit_per_unit: float = 0.20
    target_interval_sec: int = 90
    max_hold_sec: int = 180
    estimated_round_trip_fee_per_unit: float = 0.0

    def target_net_profit(self, allocated_capital: float) -> float:
        return max(0.0, allocated_capital) * self.target_profit_per_unit

    def minimum_net_profit(self, allocated_capital: float) -> float:
        return max(0.0, allocated_capital) * self.minimum_profit_per_unit

    def target_gross_profit(self, allocated_capital: float) -> float:
        return self.target_net_profit(allocated_capital) + self.estimated_round_trip_fee_per_unit * max(0.0, allocated_capital)

    def minimum_gross_profit(self, allocated_capital: float) -> float:
        return self.minimum_net_profit(allocated_capital) + self.estimated_round_trip_fee_per_unit * max(0.0, allocated_capital)


def should_take_profit(
    *,
    net_profit: float,
    allocated_capital: float,
    age_sec: float,
    profile: ProfitTimeProfile,
) -> bool:
    """Return True when the money target is reached.

    At the requested interval, the lower profit floor can be accepted to
    increase turnover. Before that interval, the normal target is preferred.
    """
    if allocated_capital <= 0:
        return False
    target = profile.target_net_profit(allocated_capital)
    floor = profile.minimum_net_profit(allocated_capital)
    if net_profit >= target:
        return True
    return age_sec >= profile.target_interval_sec and net_profit >= floor


def should_rotate(
    *,
    net_profit: float,
    allocated_capital: float,
    age_sec: float,
    profile: ProfitTimeProfile,
    entry_still_valid: bool,
) -> bool:
    """Indicate that a non-losing position should be recycled after its time budget."""
    if allocated_capital <= 0 or not entry_still_valid:
        return False
    if age_sec < profile.max_hold_sec:
        return False
    return net_profit >= 0.0
