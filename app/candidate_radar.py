"""Fast Scalper candidate radar.

Ranks up to 20 USDT spot candidates and produces a distinct top-5 action board.
The ranking is intentionally opportunity-oriented: early acceleration, liquidity,
relative volume, short-term momentum and exhaustion risk are combined. A horizon
estimate is informational, never a promise of a future move.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable

@dataclass
class Candidate:
    symbol: str
    score: float
    rank: int = 0
    regime: str = "WAIT"
    horizon_min: int = 0
    momentum_pct: float = 0.0
    volume_ratio: float = 0.0
    liquidity_score: float = 0.0
    exhaustion_risk: float = 0.0
    action: str = "WATCH"
    reason: str = ""


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def score_candidate(symbol: str, change_pct: float, volume_ratio: float,
                    spread_bps: float, acceleration_pct: float,
                    buy_ratio: float = .5, volatility_pct: float = 0.0) -> Candidate:
    momentum = _clip(abs(change_pct) / 8.0)
    accel = _clip(abs(acceleration_pct) / 1.5)
    vol = _clip(volume_ratio / 4.0)
    liq = _clip(1.0 - spread_bps / 30.0)
    buyers = _clip((buy_ratio - .5) * 4.0 + .5)
    exhaustion = _clip(max(0.0, abs(change_pct) - 5.0) / 8.0 + max(0.0, volatility_pct - 6.0) / 12.0)
    score = 100.0 * _clip(.27*accel + .22*vol + .18*momentum + .15*liq + .18*buyers - .20*exhaustion)
    if acceleration_pct > .20 and volume_ratio >= 1.5 and buy_ratio >= .55 and exhaustion < .55:
        regime = "IGNITION"
        action = "ENTER_NOW" if score >= 70 else "WATCH_TRIGGER"
    elif acceleration_pct > .08 and volume_ratio >= 1.25:
        regime = "EARLY_ROCKET"
        action = "WATCH_TRIGGER"
    elif abs(change_pct) >= 2.0:
        regime = "RELOAD"
        action = "WAIT_PULLBACK"
    else:
        regime = "WAIT"
        action = "WATCH"
    if score >= 78:
        horizon = 5
    elif score >= 65:
        horizon = 30
    elif score >= 52:
        horizon = 120
    else:
        horizon = 0
    reason = f"accel {acceleration_pct:+.2f}%, vol x{volume_ratio:.2f}, buyers {buy_ratio:.0%}; exhaustion {exhaustion:.2f}"
    return Candidate(symbol, round(score, 2), 0, regime, horizon, round(change_pct, 3), round(volume_ratio, 2), round(liq*100, 1), round(exhaustion*100, 1), action, reason)


def rank_candidates(rows: Iterable[dict], limit: int = 20) -> list[dict]:
    candidates = []
    for r in rows:
        try:
            c = score_candidate(str(r['symbol']), float(r.get('change_pct', 0)), float(r.get('volume_ratio', 1)),
                                float(r.get('spread_bps', 10)), float(r.get('acceleration_pct', 0)),
                                float(r.get('buy_ratio', .5)), float(r.get('volatility_pct', 0)))
            candidates.append(c)
        except (KeyError, TypeError, ValueError):
            continue
    candidates.sort(key=lambda x: x.score, reverse=True)
    out=[]
    for i,c in enumerate(candidates[:limit],1):
        c.rank=i; out.append(asdict(c))
    return out


def top_five(rows: list[dict]) -> list[dict]:
    return rows[:5]
