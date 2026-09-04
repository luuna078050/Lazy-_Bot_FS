from __future__ import annotations

"""TobiCore unified decision engine.

Pure/deterministic core used by scalper and Income adapters. No live orders here.
"""

from dataclasses import dataclass, asdict
from itertools import product
from typing import Iterable

HORIZONS = (1, 3, 5, 15, 30, 60)
CROSS_MODES = ("direct", "reverse", "cross_cross")


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    price: float
    momentum: float
    trend: float
    volume_ratio: float = 1.0
    spread_bps: float = 0.0


@dataclass(frozen=True)
class Signal:
    symbol: str
    horizon_min: int
    mode: str
    direction: str
    score: float
    confidence: float
    entry: float
    tp: float
    sl: float
    risk_pct: float

    def to_dict(self):
        return asdict(self)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def score_snapshot(snapshot: MarketSnapshot, horizon_min: int) -> float:
    """Horizon-aware score. Longer horizons damp raw momentum sensitivity."""
    horizon_factor = {1: 1.00, 3: 0.95, 5: 0.90, 15: 0.78, 30: 0.65, 60: 0.52}[horizon_min]
    trend_component = snapshot.trend * 20.0
    momentum_component = snapshot.momentum * 8.0 * horizon_factor
    volume_component = (snapshot.volume_ratio - 1.0) * 8.0
    spread_penalty = max(0.0, snapshot.spread_bps - 5.0) * 1.2
    return round(_clamp(50.0 + trend_component + momentum_component + volume_component - spread_penalty), 4)


def make_signal(snapshot: MarketSnapshot, horizon_min: int, mode: str) -> Signal:
    base = score_snapshot(snapshot, horizon_min)
    if mode == "reverse":
        score = 100.0 - base
    elif mode == "cross_cross":
        score = _clamp((base + (100.0 - abs(50.0 - base) * 1.4)) / 2.0)
    else:
        score = base

    direction = "BUY" if score >= 55 else "SELL" if score <= 45 else "WAIT"
    confidence = round(_clamp(abs(score - 50.0) * 2.0), 4)
    risk = {1: 0.25, 3: 0.40, 5: 0.55, 15: 0.80, 30: 1.10, 60: 1.50}[horizon_min]
    risk = min(risk, max(0.10, 2.0 - snapshot.spread_bps / 20.0))
    if direction == "BUY":
        entry, tp, sl = snapshot.price, snapshot.price * (1 + risk * 0.03), snapshot.price * (1 - risk * 0.02)
    elif direction == "SELL":
        entry, tp, sl = snapshot.price, snapshot.price * (1 - risk * 0.03), snapshot.price * (1 + risk * 0.02)
    else:
        entry = tp = sl = snapshot.price
    return Signal(snapshot.symbol, horizon_min, mode, direction, round(score, 4), confidence,
                  round(entry, 12), round(tp, 12), round(sl, 12), round(risk, 4))


def evaluate(snapshot: MarketSnapshot, horizon_min: int, mode: str) -> dict:
    return make_signal(snapshot, horizon_min, mode).to_dict()


def matrix_cases(cases_per_horizon: int = 250) -> Iterable[tuple[MarketSnapshot, int, str, int]]:
    """Generate reproducible direct/reverse/cross-cross test cases."""
    if cases_per_horizon < 1:
        raise ValueError("cases_per_horizon must be positive")
    for h in HORIZONS:
        for i in range(cases_per_horizon):
            momentum = ((i * 17 + h * 3) % 401 - 200) / 100.0
            trend = ((i * 11 + h * 5) % 201 - 100) / 100.0
            volume = 0.6 + ((i * 13 + h) % 161) / 100.0
            spread = ((i * 7 + h) % 31) / 10.0
            snap = MarketSnapshot(f"T{i % 25:02d}USDT", 100.0 + i / 100.0, momentum, trend, volume, spread)
            for mode in CROSS_MODES:
                yield snap, h, mode, i


def run_matrix(cases_per_horizon: int = 250, repeats: int = 5) -> dict:
    """Run the full deterministic cross-check matrix.

    6 horizons x 250 cases x 3 modes x 5 repeats = 22,500 evaluations.
    Additional reverse/cross consistency checks make the matrix contract stricter.
    """
    if repeats < 1:
        raise ValueError("repeats must be positive")
    total = 0
    failures = []
    for repeat in range(repeats):
        for snap, horizon, mode, idx in matrix_cases(cases_per_horizon):
            try:
                a = evaluate(snap, horizon, mode)
                b = evaluate(snap, horizon, mode)
                total += 1
                if a != b:
                    failures.append({"repeat": repeat, "index": idx, "horizon": horizon, "mode": mode})
                if mode == "reverse":
                    direct = evaluate(snap, horizon, "direct")
                    if abs(a["score"] + direct["score"] - 100.0) > 1e-6:
                        failures.append({"repeat": repeat, "index": idx, "horizon": horizon, "mode": mode, "check": "reverse_symmetry"})
            except Exception as exc:
                failures.append({"repeat": repeat, "index": idx, "horizon": horizon, "mode": mode, "error": repr(exc)})
    expected = len(HORIZONS) * cases_per_horizon * len(CROSS_MODES) * repeats
    return {
        "ok": not failures and total == expected,
        "horizons_min": list(HORIZONS),
        "modes": list(CROSS_MODES),
        "cases_per_horizon": cases_per_horizon,
        "repeats": repeats,
        "evaluations": total,
        "expected": expected,
        "failures": failures[:50],
    }
