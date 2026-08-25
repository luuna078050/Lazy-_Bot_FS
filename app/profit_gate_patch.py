from __future__ import annotations

from typing import Any
from . import profit_first_engine as engine
from .market_radar import RADAR

_ORIGINAL_PULSE = None


def _pulse_with_flow(symbol: str) -> dict[str, Any]:
    global _ORIGINAL_PULSE
    base = _ORIGINAL_PULSE(symbol) if _ORIGINAL_PULSE else {}
    with RADAR.lock:
        h = list(RADAR.pulses.get(symbol, ()))
    buy_ratio = 0.5
    if h and h[-1].get("quote", 0):
        buy_ratio = float(h[-1].get("buy_quote", 0) or 0) / float(h[-1].get("quote", 1) or 1)
    return {**base, "buy_ratio": buy_ratio}


def _decision(m: dict[str, Any]) -> dict[str, Any]:
    """Practical entry gate: require real momentum/flow, but don't starve PAPER."""
    c3 = float(m.get("change_3m_pct", 0) or 0)
    vr = float(m.get("volume_ratio", 1) or 1)
    buy = float(m.get("buy_ratio", 0.5) or 0.5)
    pump = float(m.get("pump_score", 0) or 0)
    c24 = float(m.get("change_24h_pct", 0) or 0)
    signal = str(m.get("signal", "WAIT"))

    momentum = max(0.0, min(1.0, c3 / 0.45))
    volume = max(0.0, min(1.0, (vr - 1.0) / 2.0))
    flow = max(0.0, min(1.0, (buy - 0.50) / 0.18))
    pulse = max(0.0, min(1.0, pump))
    trend = max(0.0, min(1.0, c24 / 5.0))
    quality = 100.0 * (0.32 * momentum + 0.27 * volume + 0.21 * flow + 0.15 * pulse + 0.05 * trend)

    confirmations = sum((
        c3 >= 0.03,
        vr >= 1.20,
        buy >= 0.53,
        pump >= 0.25 or signal == "PUMP_NOW",
        c24 >= -0.50,
    ))
    threshold = engine.adaptive_quality_threshold()
    # Let PAPER collect a real sample first; after 8 closed trades the adaptive
    # win-rate threshold is used unchanged and can tighten back to 72/66/62/58.
    effective_threshold = min(threshold, 44.0) if len(engine.STATE.get("trades", [])) < 8 else threshold
    entry_ok = (
        signal not in {"WAIT", "FADE"}
        and c3 >= 0.03
        and confirmations >= 3
        and quality >= effective_threshold
    )
    return {
        "quality": round(quality, 2),
        "confirmations": confirmations,
        "threshold": round(effective_threshold, 2),
        "entry_ok": entry_ok,
    }


def install() -> None:
    global _ORIGINAL_PULSE
    if _ORIGINAL_PULSE is None:
        _ORIGINAL_PULSE = RADAR._pulse
        RADAR._pulse = _pulse_with_flow
    engine.decision = _decision
