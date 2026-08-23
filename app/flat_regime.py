"""Flat-market models for Fast Scalper.

The scalper may trade a range only when the expected NET edge is large enough
for fees, spread and slippage. Flat is a regime, not a reason to force trades.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class FlatModel(str, Enum):
    MICRO_RANGE = "MICRO_RANGE"          # tight, liquid oscillation
    WIDE_RANGE = "WIDE_RANGE"            # wider mean-reversion channel
    COMPRESSION = "COMPRESSION"          # squeeze before breakout; trade only edges

@dataclass(frozen=True)
class FlatSignal:
    model: FlatModel
    action: str
    confidence: float
    reason: str

@dataclass(frozen=True)
class FlatConfig:
    enabled: bool = True
    min_net_profit_usdt: float = 0.10
    target_net_profit_usdt: float = 0.15
    max_hold_seconds: int = 30
    max_inventory_fraction: float = 0.30
    min_range_bps: float = 8.0
    max_range_bps: float = 180.0
    min_edge_bps: float = 12.0
    breakout_buffer_bps: float = 6.0


def classify_flat(range_bps: float, compression_ratio: float, directional_score: float) -> FlatModel | None:
    """Classify a non-trending market into one of three tradable flat regimes."""
    if range_bps < 8 or abs(directional_score) > 0.35:
        return None
    if compression_ratio <= 0.55:
        return FlatModel.COMPRESSION
    if range_bps <= 45:
        return FlatModel.MICRO_RANGE
    if range_bps <= 180:
        return FlatModel.WIDE_RANGE
    return None


def evaluate_flat(
    *,
    model: FlatModel,
    price: float,
    range_low: float,
    range_high: float,
    spread_bps: float,
    estimated_round_trip_fee_bps: float,
    momentum_1s_bps: float,
    volume_ratio: float,
    cfg: FlatConfig = FlatConfig(),
) -> FlatSignal:
    """Return a range-trade decision without forcing a trade.

    BUY/SELL are spot inventory actions. A SHORT is never emitted here; the
    bear engine is responsible for Margin/Futures execution when enabled.
    """
    if not cfg.enabled or price <= 0 or range_high <= range_low:
        return FlatSignal(model, "WAIT", 0.0, "flat module disabled or invalid range")

    width_bps = (range_high - range_low) / price * 10_000
    edge_to_low_bps = (price - range_low) / price * 10_000
    edge_to_high_bps = (range_high - price) / price * 10_000
    friction_bps = max(0.0, spread_bps) + max(0.0, estimated_round_trip_fee_bps)

    # Compression is a no-chase regime: trade only at an edge and stand down
    # immediately when momentum starts escaping the range.
    if model == FlatModel.COMPRESSION:
        if abs(momentum_1s_bps) >= cfg.breakout_buffer_bps or volume_ratio >= 2.0:
            return FlatSignal(model, "WAIT", 0.0, "compression is breaking; hand off to bull/bear hunter")
        if edge_to_low_bps >= max(cfg.min_edge_bps, friction_bps * 1.5) and edge_to_high_bps >= cfg.min_edge_bps:
            return FlatSignal(model, "BUY", 0.64, "compression lower edge; mean-reversion entry only")
        return FlatSignal(model, "WAIT", 0.0, "inside compression; wait for an edge")

    if model == FlatModel.MICRO_RANGE:
        if edge_to_low_bps >= max(cfg.min_edge_bps, friction_bps * 1.5) and momentum_1s_bps > -cfg.breakout_buffer_bps:
            return FlatSignal(model, "BUY", 0.72, "micro-range lower edge with stable momentum")
        if edge_to_high_bps >= max(cfg.min_edge_bps, friction_bps * 1.5) and momentum_1s_bps < cfg.breakout_buffer_bps:
            return FlatSignal(model, "SELL", 0.72, "micro-range upper edge; release inventory")
        return FlatSignal(model, "WAIT", 0.0, "middle of micro-range")

    # Wide range: require more room because the holding time is still short.
    if edge_to_low_bps >= max(cfg.min_edge_bps * 1.5, friction_bps * 2.0) and momentum_1s_bps > -cfg.breakout_buffer_bps:
        return FlatSignal(model, "BUY", 0.68, "wide-range lower edge")
    if edge_to_high_bps >= max(cfg.min_edge_bps * 1.5, friction_bps * 2.0) and momentum_1s_bps < cfg.breakout_buffer_bps:
        return FlatSignal(model, "SELL", 0.68, "wide-range upper edge")
    return FlatSignal(model, "WAIT", 0.0, "no edge in wide range")


def flat_profile() -> dict:
    return {
        "enabled": True,
        "models": [m.value for m in FlatModel],
        "min_net_profit_usdt": 0.10,
        "target_net_profit_usdt": 0.15,
        "max_hold_seconds": 30,
        "max_inventory_fraction": 0.30,
        "principle": "range trading is optional; bull/bear ignition always has priority",
    }
