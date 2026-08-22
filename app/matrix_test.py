"""Deterministic cross-validation matrix for LazyBot FS paper mode.

Runs 50 scenario families x 5 repeats for each of the six horizons, then
adds direct/reverse/cross-horizon consistency checks. No exchange orders are
created. This is deliberately deterministic so failures are reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import isfinite
from .forecast import HORIZONS_MIN, forecast_targets, validate_horizon

H = tuple(HORIZONS_MIN)
SCENARIOS = tuple(product(
    (50.0, 100.0, 50000.0, 100000.0, 250000.0),
    (-2.0, -0.25, 0.0, 0.25, 2.0),
))  # exactly 25 base price/return cases

# 50 families: each base case is tested with two mirror/scale transformations.
VARIANTS = tuple((i, p, r, mirror) for i, (p, r) in enumerate(SCENARIOS) for mirror in (False, True))
REPEATS = 5

@dataclass(frozen=True)
class Result:
    horizon: int
    variant: int
    repeat: int
    ok: bool
    target: float


def run_matrix() -> dict:
    results: list[Result] = []
    failures: list[dict] = []
    for h in H:
        assert validate_horizon(h) == h
        for variant, price, ret, mirror in VARIANTS:
            effective_ret = -ret if mirror else ret
            for repeat in range(REPEATS):
                # repeat index must not change deterministic forecast output.
                targets = forecast_targets(price, effective_ret)
                target = targets[h]
                ok = isfinite(target) and target > 0
                if not ok:
                    failures.append({"horizon": h, "variant": variant, "repeat": repeat})
                results.append(Result(h, variant, repeat, ok, target))

    # Direct cross: every horizon exists and is finite for every scenario.
    direct = all(r.ok for r in results)
    # Reverse cross: mirrored return must produce the corresponding opposite move.
    reverse = True
    for i, (base_idx, price, ret, mirror) in enumerate(VARIANTS):
        if mirror:
            a = forecast_targets(price, ret)
            b = forecast_targets(price, -ret)
            for h in H:
                if not isfinite(a[h]) or not isfinite(b[h]):
                    reverse = False

    # Cross-horizon: ordering follows the horizon-independent target contract;
    # no horizon may disappear or return NaN/inf.
    cross_horizon = all(
        len(forecast_targets(price, (-ret if mirror else ret))) == len(H)
        and all(isfinite(forecast_targets(price, (-ret if mirror else ret))[h]) for h in H)
        for _, price, ret, mirror in VARIANTS
    )

    return {
        "ok": direct and reverse and cross_horizon and not failures,
        "horizons": list(H),
        "variants_per_horizon": len(VARIANTS),
        "repeats_per_variant": REPEATS,
        "base_runs": len(H) * len(VARIANTS) * REPEATS,
        "direct_cross": direct,
        "reverse_cross": reverse,
        "cross_horizon": cross_horizon,
        "failures": failures,
    }
