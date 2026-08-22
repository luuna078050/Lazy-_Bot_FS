from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import isfinite
from typing import Any

HORIZONS = (1, 3, 5, 15, 30, 60)

@dataclass(frozen=True)
class Scenario:
    price: float
    predicted_return_pct: float
    confidence: float
    direction: int


def scenarios() -> list[Scenario]:
    prices = (0.0001, 1.0, 100.0, 10000.0, 100000.0)
    returns = (-5.0, -0.3, 0.0, 0.1, 5.0)
    confidence = (0.0, 0.5, 1.0)
    directions = (-1, 0, 1)
    return [Scenario(*x) for x in product(prices, returns, confidence, directions)]


def target(price: float, predicted_return_pct: float) -> float:
    return price * (1.0 + predicted_return_pct / 100.0)


def validate_case(s: Scenario, horizon: int) -> dict[str, Any]:
    assert horizon in HORIZONS
    assert isfinite(s.price) and s.price > 0
    assert isfinite(s.predicted_return_pct)
    assert 0.0 <= s.confidence <= 1.0
    t = target(s.price, s.predicted_return_pct)
    assert isfinite(t) and t >= 0
    if s.direction > 0:
        assert s.predicted_return_pct >= 0 or s.confidence == 0
    if s.direction < 0:
        assert s.predicted_return_pct <= 0 or s.confidence == 0
    return {"horizon": horizon, "price": s.price, "target": t, "confidence": s.confidence}


def run_matrix(repeats: int = 5) -> dict[str, Any]:
    base = scenarios()
    # Deterministic 250-case slice per horizon; each case is repeated five times.
    cases = base[:250]
    results = []
    failures = []
    for h in HORIZONS:
        for idx, s in enumerate(cases):
            for repeat in range(repeats):
                try:
                    a = validate_case(s, h)
                    b = validate_case(s, h)
                    if a != b:
                        raise AssertionError("non-deterministic direct cross-check")
                    # Reverse cross: recompute from target and verify the implied return.
                    implied = (a["target"] / a["price"] - 1.0) * 100.0
                    if abs(implied - s.predicted_return_pct) > 1e-9:
                        raise AssertionError("reverse cross mismatch")
                    results.append((h, idx, repeat))
                except Exception as exc:
                    failures.append({"horizon": h, "case": idx, "repeat": repeat, "error": str(exc)})
    return {
        "horizons": HORIZONS,
        "cases_per_horizon": len(cases),
        "repeats": repeats,
        "runs": len(results),
        "failures": failures,
        "passed": not failures,
    }
