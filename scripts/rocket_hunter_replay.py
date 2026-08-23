"""Replay harness for Rocket Hunter.

The benchmark reports whether market data actually offers enough qualified
3-minute opportunities to approach the 130-150/day target. It must never
manufacture trades to hit the target.
"""
from __future__ import annotations
from collections import Counter
from app.rocket_hunter import RocketSnapshot, scan


def evaluate_stream(snapshots: list[RocketSnapshot], day_count: int = 1) -> dict:
    signals = [scan(s) for s in snapshots]
    qualified = [x for x in signals if x.phase in {'EARLY_ROCKET', 'IGNITION'}]
    # Approximate non-overlapping 3-minute execution slots: a new trade is
    # allowed only after the prior 3-minute slot expires.
    selected = []
    last_index = -3
    for i, sig in enumerate(signals):
        if i - last_index < 3 or sig.phase == 'IGNORE':
            continue
        selected.append(sig); last_index = i
    counts = Counter(x.phase for x in signals)
    return {
        'observations': len(signals),
        'qualified_opportunities': len(qualified),
        'simulated_executions': len(selected),
        'target_min_per_day': 130,
        'target_max_per_day': 150,
        'target_reached': 130 <= len(selected) / max(day_count, 1) <= 150,
        'target_was_forced': False,
        'phase_counts': dict(counts),
        'note': '130-150/day is a validation target, not a forced trade quota; zero-trade periods are valid.'
    }
