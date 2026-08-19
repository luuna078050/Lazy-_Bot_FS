"""LazyBot FS multi-timeframe research harness.

Purpose: keep 3m, 5m, 15m, 1h and 4h analyses separate while allowing
cross-timeframe features to be joined at the execution timeframe.

This is research/backtest code only. It never places live orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

TIMEFRAMES = ("3m", "5m", "15m", "1h", "4h")
SYMBOLS = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT")

@dataclass(frozen=True)
class FrameFeatures:
    timeframe: str
    trend: float
    momentum: float
    volatility: float
    volume_z: float

@dataclass(frozen=True)
class CrossFrameState:
    symbol: str
    execution_tf: str
    aligned: bool
    features: tuple[FrameFeatures, ...]


def validate_timeframes(timeframes: Iterable[str]) -> tuple[str, ...]:
    result = tuple(timeframes)
    unknown = set(result) - set(TIMEFRAMES)
    if unknown:
        raise ValueError(f"Unsupported timeframes: {sorted(unknown)}")
    if not result:
        raise ValueError("At least one timeframe is required")
    return result


def build_cross_frame_state(symbol: str, execution_tf: str, features: Iterable[FrameFeatures]) -> CrossFrameState:
    validate_timeframes([f.timeframe for f in features])
    if execution_tf not in TIMEFRAMES:
        raise ValueError(f"Unsupported execution timeframe: {execution_tf}")
    fs = tuple(features)
    return CrossFrameState(symbol=symbol, execution_tf=execution_tf, aligned=True, features=fs)


def causal_chain_score(state: CrossFrameState) -> float:
    """Illustrative research score, not a trading recommendation.

    Higher score means stronger agreement between the supplied timeframes.
    No future candles may be used when constructing FrameFeatures.
    """
    if not state.features:
        return 0.0
    trend = sum(f.trend for f in state.features) / len(state.features)
    momentum = sum(f.momentum for f in state.features) / len(state.features)
    volatility_penalty = sum(abs(f.volatility) for f in state.features) / len(state.features)
    return trend * 0.45 + momentum * 0.45 - volatility_penalty * 0.10
