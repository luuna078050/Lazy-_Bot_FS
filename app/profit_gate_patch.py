from __future__ import annotations

from typing import Any
from . import profit_first_engine as engine
from .market_radar import RADAR

_ORIGINAL_PULSE = None
_ORIGINAL_SNAPSHOT = None


def _pulse_with_flow(symbol: str) -> dict[str, Any]:
    base = _ORIGINAL_PULSE(symbol) if _ORIGINAL_PULSE else {}
    with RADAR.lock:
        h = list(RADAR.pulses.get(symbol, ()))
    buy_ratio = 0.5
    if h and h[-1].get("quote", 0):
        buy_ratio = float(h[-1].get("buy_quote", 0) or 0) / float(h[-1].get("quote", 1) or 1)
    return {**base, "buy_ratio": buy_ratio}


def _quality_score(row: dict[str, Any]) -> float:
    c3 = max(0.0, float(row.get("change_3m_pct", 0) or 0))
    vr = max(0.0, float(row.get("volume_ratio", 1) or 1) - 1.0)
    pump = max(0.0, min(1.0, float(row.get("pump_score", 0) or 0)))
    buy = max(0.0, min(1.0, float(row.get("buy_ratio", 0.5) or 0.5)))
    c24 = max(0.0, float(row.get("change_24h_pct", 0) or 0))
    momentum = min(1.0, c3 / 0.45)
    volume = min(1.0, vr / 2.0)
    flow = min(1.0, max(0.0, (buy - 0.50) / 0.18))
    trend = min(1.0, c24 / 5.0)
    return round(100.0 * (0.35 * pump + 0.25 * momentum + 0.20 * volume + 0.15 * flow + 0.05 * trend), 2)


def _snapshot(limit: int = 20):
    rows = list(_ORIGINAL_SNAPSHOT(limit) if _ORIGINAL_SNAPSHOT else [])
    for row in rows:
        row["score"] = _quality_score(row)
    rows.sort(key=lambda x: (float(x.get("score", 0) or 0), float(x.get("quote_volume_24h", 0) or 0)), reverse=True)
    return rows[: max(6, min(int(limit), 20))]


def _decision(m: dict[str, Any]) -> dict[str, Any]:
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

    confirmations = sum((c3 >= 0.03, vr >= 1.20, buy >= 0.53, pump >= 0.25 or signal == "PUMP_NOW", c24 >= -0.50))
    threshold = engine.adaptive_quality_threshold()
    effective_threshold = min(threshold, 44.0) if len(engine.STATE.get("trades", [])) < 8 else threshold
    entry_ok = signal not in {"WAIT", "FADE"} and c3 >= 0.03 and confirmations >= 3 and quality >= effective_threshold
    return {"quality": round(quality, 2), "confirmations": confirmations, "threshold": round(effective_threshold, 2), "entry_ok": entry_ok}


def install() -> None:
    global _ORIGINAL_PULSE, _ORIGINAL_SNAPSHOT
    if _ORIGINAL_PULSE is None:
        _ORIGINAL_PULSE = RADAR._pulse
        RADAR._pulse = _pulse_with_flow
    if _ORIGINAL_SNAPSHOT is None:
        _ORIGINAL_SNAPSHOT = RADAR.snapshot
        RADAR.snapshot = _snapshot
    engine.decision = _decision
