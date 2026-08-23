"""Exit policy that keeps profit targeting independent from optional SL."""
from __future__ import annotations


def decide_exit(
    entry_price: float,
    current_price: float,
    take_profit_pct: float | None,
    stop_loss_pct: float,
    stop_loss_enabled: bool,
    confirmed_reversal: bool,
) -> str | None:
    if entry_price <= 0 or current_price <= 0:
        return None

    # Percentage TP is optional. In money/time mode the caller passes None and
    # the profit_timing module owns the take-profit decision.
    if take_profit_pct is not None and take_profit_pct > 0 and current_price >= entry_price * (1.0 + take_profit_pct):
        return "take_profit"

    if stop_loss_enabled and current_price <= entry_price * (1.0 - stop_loss_pct):
        return "stop_loss"

    # A reversal is allowed to close a profitable trade. When SL is disabled,
    # an underwater trade remains open so the strategy can wait for recovery.
    pnl_pct = (current_price / entry_price - 1.0) * 100.0
    if confirmed_reversal and pnl_pct >= 0.0:
        return "confirmed_reversal"

    return None
