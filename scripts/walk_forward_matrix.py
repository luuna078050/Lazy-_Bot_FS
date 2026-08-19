"""Walk-forward research matrix for LazyBot FS.

The market history is known, but every model fit is restricted to the past
relative to the evaluation window. This is intended to discover robust
causal/conditional chains rather than optimize one historical sample.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product

TIMEFRAMES = ("3m", "5m", "15m", "1h", "4h")
SYMBOLS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT")

@dataclass(frozen=True)
class ResearchCase:
    symbol: str
    execution_tf: str
    context_tfs: tuple[str, ...]
    train_days: int = 45
    test_days: int = 15


def cases() -> list[ResearchCase]:
    out: list[ResearchCase] = []
    for symbol, execution_tf in product(SYMBOLS, ("3m", "5m", "15m")):
        context = tuple(tf for tf in TIMEFRAMES if tf != execution_tf)
        out.append(ResearchCase(symbol, execution_tf, context))
    return out


def assert_no_lookahead(train_end_ts: int, evaluation_start_ts: int) -> None:
    if train_end_ts >= evaluation_start_ts:
        raise AssertionError("Look-ahead detected: training data overlaps evaluation window")


def target_hit_rate(trades: list[bool]) -> float:
    if not trades:
        return 0.0
    return sum(trades) / len(trades)


def qualifies_for_review(hit_rate: float, min_trades: int, trade_count: int) -> bool:
    """93-95% is a research target, never a forced outcome."""
    return trade_count >= min_trades and 0.93 <= hit_rate <= 0.95
