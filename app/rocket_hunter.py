"""Rocket Hunter: high-frequency candidate discovery for Lazy Scalper.

This module searches for *early* acceleration, not already-completed pumps.
A 130-150 trade/day figure is a validation target, never a forced quota.
"""
from __future__ import annotations
from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True)
class RocketSnapshot:
    symbol: str
    price: float
    volume_24h: float
    volume_1h: float
    volume_5m: float
    volume_3m: float
    volume_1m: float
    price_change_1m: float
    price_change_3m: float
    price_change_5m: float
    trades_5m: int
    spread_bps: float
    depth_usd: float
    buy_imbalance: float
    ma7_slope: float
    ma25_slope: float
    rsi: float
    stoch_k: float
    stoch_d: float
    higher_tf_score: float


@dataclass(frozen=True)
class RocketSignal:
    symbol: str
    score: float
    phase: str
    price: float
    expected_horizon_min: int
    entry_quality: float
    liquidity_quality: float
    acceleration: float
    reasons: tuple[str, ...]


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def scan(s: RocketSnapshot) -> RocketSignal:
    # Relative volume is more important than absolute volume: a $300k/day pair
    # can be interesting if its current flow suddenly accelerates, while a
    # $20m/day pair can be irrelevant if its flow is flat.
    base_5m = max(s.volume_1h / 12.0, 1.0)
    rel_5m = s.volume_5m / base_5m
    rel_3m = s.volume_3m / max(s.volume_1h / 20.0, 1.0)
    rel_1m = s.volume_1m / max(s.volume_1h / 60.0, 1.0)
    acceleration = _clip((rel_1m - 1.0) / 3.0) * .35 + _clip((rel_3m - 1.0) / 2.5) * .35 + _clip((rel_5m - 1.0) / 2.0) * .30

    price_accel = (.30 * _clip(s.price_change_1m / .02) + .40 * _clip(s.price_change_3m / .05) + .30 * _clip(s.price_change_5m / .08))
    momentum = .55 * price_accel + .45 * acceleration

    # Entry must happen before exhaustion. A very high RSI/stochastic after a
    # vertical move is a late-entry penalty, not a bullish confirmation.
    exhaustion = 0.0
    if s.rsi > 78: exhaustion += .30
    if s.stoch_k > 90 and s.stoch_k < s.stoch_d: exhaustion += .30
    if s.price_change_5m > .15: exhaustion += .25
    early = max(0.0, momentum - exhaustion)

    trend = _clip((s.ma7_slope * 20.0 + s.ma25_slope * 10.0) / 2.0)
    micro = .45 * _clip(abs(s.buy_imbalance)) + .30 * _clip(s.depth_usd / max(s.volume_1h * .01, 1.0)) + .25 * _clip(1.0 - s.spread_bps / 30.0)
    higher = _clip((s.higher_tf_score + 1.0) / 2.0)

    # Cheap nominal price is a candidate preference, never a bullish signal.
    low_price_bonus = .05 if 0 < s.price < .001 else 0.0
    score = .38 * early + .20 * trend + .18 * micro + .14 * higher + low_price_bonus
    score -= exhaustion * .20
    score = max(0.0, min(1.0, score))

    if score >= .72 and acceleration >= .55 and momentum >= .50:
        phase = "EARLY_ROCKET"
    elif score >= .55 and momentum >= .38:
        phase = "IGNITION"
    elif score >= .40:
        phase = "WATCH"
    else:
        phase = "IGNORE"

    reasons = []
    if acceleration >= .55: reasons.append("volume_acceleration")
    if price_accel >= .45: reasons.append("price_acceleration")
    if s.buy_imbalance > .20: reasons.append("buyer_imbalance")
    if s.spread_bps <= 12: reasons.append("tight_spread")
    if s.price < .001: reasons.append("low_nominal_price")
    if exhaustion > .35: reasons.append("late_entry_risk")
    return RocketSignal(s.symbol, round(score, 4), phase, s.price, 3, round(early, 4), round(micro, 4), round(acceleration, 4), tuple(reasons))


def rank(snapshots: list[RocketSnapshot], max_candidates: int = 20) -> list[RocketSignal]:
    signals = [scan(s) for s in snapshots]
    signals.sort(key=lambda x: (x.phase != "EARLY_ROCKET", x.score), reverse=False)
    return signals[:max_candidates]
