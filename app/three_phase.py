from __future__ import annotations

"""Three-phase scalping engine.

The engine treats MA7/25/99, RSI14, Stochastic(14,3,3), price/volume structure
and order-book boundaries as one state machine. It is deliberately conservative:
a strong BUY score cannot override an overheated/correction gate.
"""

from dataclasses import dataclass, asdict
from typing import Sequence


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _sma(v: Sequence[float], n: int) -> float:
    return sum(v[-n:]) / n if len(v) >= n else sum(v) / max(1, len(v))


def rsi14(closes: Sequence[float], n: int = 14) -> float:
    if len(closes) < n + 1:
        return 50.0
    gains = []
    losses = []
    for a, b in zip(closes[-n-1:-1], closes[-n:]):
        d = b - a
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains) / n
    al = sum(losses) / n
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def stochastic(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               n: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> tuple[float, float]:
    if len(closes) < n:
        return 50.0, 50.0
    raw = []
    start = max(0, len(closes) - n - smooth_k - smooth_d - 8)
    for i in range(start, len(closes)):
        lo = min(lows[max(0, i-n+1):i+1])
        hi = max(highs[max(0, i-n+1):i+1])
        raw.append(50.0 if hi == lo else (closes[i] - lo) / (hi - lo) * 100.0)
    k = _sma(raw, smooth_k)
    d = _sma(raw[-smooth_d:], smooth_d) if len(raw) >= smooth_d else k
    return k, d


@dataclass(frozen=True)
class ThreePhase:
    phase: str
    gate: str
    action: str
    ma7: float
    ma25: float
    ma99: float
    rsi: float
    stoch_k: float
    stoch_d: float
    overheating: float
    correction_depth_pct: float
    confidence: float

    def to_dict(self):
        return asdict(self)


def analyze_three_phase(closes: Sequence[float], highs: Sequence[float],
                        lows: Sequence[float], volumes: Sequence[float],
                        price: float | None = None,
                        support: float | None = None,
                        resistance: float | None = None) -> ThreePhase:
    if len(closes) < 30:
        return ThreePhase("UNKNOWN", "BLOCK", "WAIT", 0, 0, 0, 50, 50, 50, 0, 0, 0)

    p = float(price or closes[-1])
    ma7 = _sma(closes, 7)
    ma25 = _sma(closes, 25)
    ma99 = _sma(closes, 99) if len(closes) >= 99 else _sma(closes, min(60, len(closes)))
    rsi = rsi14(closes)
    sk, sd = stochastic(highs, lows, closes)
    lookback = min(30, len(closes))
    recent_high = max(highs[-lookback:])
    prior_high = max(highs[-min(lookback*2, len(highs)):-lookback]) if len(highs) > lookback else recent_high
    recent_low = min(lows[-lookback:])
    impulse_pct = (p / closes[-min(10, len(closes))] - 1.0) * 100.0
    range_pct = max(0.01, (recent_high - recent_low) / p * 100.0)
    vol_base = _sma(volumes[:-1], min(20, max(1, len(volumes)-1))) if len(volumes) > 1 else 1.0
    vol_ratio = volumes[-1] / vol_base if vol_base > 0 else 1.0

    overheating = 0.0
    overheating += _clamp((rsi - 65.0) / 20.0, 0, 1) * 0.35
    overheating += _clamp((sk - 75.0) / 25.0, 0, 1) * 0.25
    overheating += _clamp((p / ma25 - 1.0) / 0.02, 0, 1) * 0.20
    overheating += _clamp((ma7 / ma25 - 1.0) / 0.015, 0, 1) * 0.20

    correction_depth = max(0.0, (recent_high - p) / recent_high * 100.0)

    impulse = (
        impulse_pct >= 0.8 and ma7 > ma25 and p >= ma7 and
        (rsi >= 58 or sk >= 65) and vol_ratio >= 1.15
    )
    exhausted = overheating >= 0.55 or (rsi >= 72 and sk >= 82)
    correction = (
        correction_depth >= max(0.35, range_pct * 0.18) and
        (p < ma7 or sk < sd or rsi < 58 or impulse_pct < 0)
    )
    recovery = (
        correction_depth >= 0.35 and p >= ma7 and ma7 >= ma25 and
        sk > sd and sk >= 45 and rsi >= 45
    )

    # Three-phase state: Phase 1 impulse -> Phase 2 correction -> Phase 3 recovery.
    # The gate is authoritative: a generic BUY score cannot override NO_CHASE/WAIT.
    if recovery and not exhausted:
        phase, gate, action = "PHASE_3_RECOVERY", "ALLOW", "BUY_RECOVERY"
    elif correction or exhausted:
        phase = "PHASE_2_CORRECTION"
        gate = "BLOCK" if exhausted else "WAIT_CONFIRMATION"
        action = "NO_CHASE" if exhausted else "WAIT_PULLBACK"
    elif impulse:
        phase, gate, action = "PHASE_1_IMPULSE", "ALLOW_EARLY", "BUY_EARLY"
    else:
        phase, gate, action = "NEUTRAL", "WAIT", "WAIT"

    if support and p <= support * 1.004 and sk > sd:
        action = "SUPPORT_REACTION" if gate != "BLOCK" else action
    if resistance and p >= resistance * 0.996:
        gate = "BLOCK"
        action = "NO_CHASE"

    conf = _clamp(
        50.0
        + (10.0 if ma7 > ma25 else -10.0)
        + (rsi - 50.0) * 0.35
        + (sk - sd) * 0.20
        - overheating * 25.0,
        0, 100
    )
    return ThreePhase(phase, gate, action, ma7, ma25, ma99, rsi, sk, sd,
                      round(overheating, 4), round(correction_depth, 4),
                      round(conf, 2))
