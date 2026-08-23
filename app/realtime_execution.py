"""One-second Rocket Hunter execution gate.

This is deliberately narrower than the strategic 3m scanner. It can react to
a genuine 1-3 second burst from the websocket pulse, but it cannot bypass the
existing capital, validation, daily-loss, spot-only and live-arming guards.
"""
from __future__ import annotations

import os
import time


def live_enabled() -> bool:
    return os.getenv("TRADING_MODE", "paper").lower() == "live" and os.getenv("LIVE_TRADING", "false").lower() == "true" and os.getenv("LIVE_TRADING_ARMED", "false").lower() == "true"


def pulse_entry_allowed(pulse: dict, min_score: float = 0.72) -> bool:
    if not pulse:
        return False
    if pulse.get("state") not in {"IGNITION", "EARLY_ROCKET"}:
        return False
    if float(pulse.get("score", 0.0)) < min_score:
        return False
    if float(pulse.get("price_change_2s", 0.0)) < 0.0018:
        return False
    if float(pulse.get("volume_ratio", 0.0)) < 2.0:
        return False
    if float(pulse.get("buy_ratio", 0.5)) < 0.58:
        return False
    return True


def micro_entry(ex, state: dict, pulse: dict, bot_balance: float, allocation_pct: float, max_positions: int = 5):
    """Paper/live guarded micro-entry. Returns an event dict or None."""
    if not pulse_entry_allowed(pulse, float(os.getenv("PULSE_MIN_SCORE", "0.72"))):
        return None
    if not os.getenv("PULSE_EXECUTION_ENABLED", "true").lower() == "true":
        return None
    if len(state.get("positions", {})) >= max_positions:
        return None
    symbol = pulse["symbol"]
    if symbol in state.get("positions", {}):
        return None
    validation_start = float(state.get("allocation_validation_start") or time.time())
    validation_days = (time.time() - validation_start) / 86400
    if os.getenv("AUTO_ALLOCATION_ENABLED", "false").lower() != "true":
        return None
    if validation_days < int(os.getenv("ALLOCATION_VALIDATION_DAYS", "14")):
        return None
    if sum(float(p.get("allocation_pct", 0)) for p in state.get("positions", {}).values()) + allocation_pct > 100:
        return None
    daily_loss = float(state.get("realized_pnl", 0.0))
    if daily_loss <= -float(os.getenv("DAILY_LOSS_LIMIT_USDT", "3")):
        return None
    price = float(pulse["price"])
    budget = bot_balance * allocation_pct / 100.0
    amount = float(ex.amount_to_precision(symbol, budget / price))
    if amount <= 0:
        return None
    order = ex.create_market_order(symbol, "buy", amount, live=live_enabled())
    allocated = amount * price
    state.setdefault("positions", {})[symbol] = {
        "entry": price,
        "amount": amount,
        "allocation_pct": allocation_pct,
        "allocated_capital": allocated,
        "score": pulse["score"],
        "opened": time.time(),
        "entry_type": "REALTIME_IGNITION",
        "pulse_2s": pulse["price_change_2s"],
        "pulse_volume_ratio": pulse["volume_ratio"],
    }
    return {"symbol": symbol, "price": price, "amount": amount, "allocation_pct": allocation_pct, "score": pulse["score"], "state": pulse["state"], "live": live_enabled(), "order": order}
