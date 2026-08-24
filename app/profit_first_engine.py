from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .market_radar import RADAR

LOCK = threading.RLock()
STOP = threading.Event()
THREAD: threading.Thread | None = None
HALT_ENTRIES = False
COOLDOWN: dict[str, float] = {}

STATE: dict[str, Any] = {
    "running": False, "mode": "paper", "started_at": None, "stopped_at": None,
    "initial_balance": 0.0, "account_balance_usdt": 0.0, "free_usdt": 0.0,
    "realized_pnl": 0.0, "profit_reserve_usdt": 0.0, "assets": {},
    "open_positions": {}, "orders": {}, "order_history": [], "trades": [],
    "config": {}, "error": None, "stop_type": None,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def market(symbol: str) -> dict[str, Any] | None:
    key = symbol.replace("/", "").upper()
    with RADAR.lock:
        ticker = dict(RADAR.tickers.get(key) or {})
        if not ticker: return None
        price = float(ticker.get("c") or 0)
        pulse = RADAR._pulse(key)
        tf = RADAR._three_min_metrics(key, price)
    if price <= 0: return None
    return {"price": price, "change_24h_pct": float(ticker.get("P") or 0), "quote_volume_24h": float(ticker.get("q") or 0), **tf, **pulse}


def adaptive_quality_threshold() -> float:
    trades = STATE.get("trades", [])[-20:]
    if len(trades) < 8: return 58.0
    wins = sum(1 for t in trades if float(t.get("net_pnl", 0)) > 0)
    wr = wins / len(trades) * 100
    if wr < 60: return 72.0
    if wr < 70: return 66.0
    if wr < 75: return 62.0
    return 58.0


def decision(m: dict[str, Any]) -> dict[str, Any]:
    c3 = float(m.get("change_3m_pct", 0)); vr = float(m.get("volume_ratio", 1)); buy = float(m.get("buy_ratio", 0.5))
    pump = float(m.get("pump_score", 0)); c24 = float(m.get("change_24h_pct", 0)); signal = str(m.get("signal", "WAIT"))
    momentum = max(0.0, min(1.0, c3 / 0.60)); volume = max(0.0, min(1.0, (vr - 1.0) / 2.5))
    flow = max(0.0, min(1.0, (buy - 0.50) / 0.20)); pulse = max(0.0, min(1.0, pump)); trend = max(0.0, min(1.0, c24 / 5.0))
    quality = 100.0 * (0.30 * momentum + 0.25 * volume + 0.20 * flow + 0.20 * pulse + 0.05 * trend)
    confirmations = sum((c3 >= 0.05, vr >= 1.40, buy >= 0.56, pump >= 0.35 or signal == "PUMP_NOW", c24 >= 0))
    threshold = adaptive_quality_threshold()
    entry_ok = signal not in {"WAIT", "FADE"} and confirmations >= 4 and quality >= threshold
    return {"quality": round(quality, 2), "confirmations": confirmations, "threshold": threshold, "entry_ok": entry_ok}


def copy_state() -> dict[str, Any]:
    s = dict(STATE)
    s["assets"] = {k: dict(v) for k, v in STATE["assets"].items()}
    s["open_positions"] = {k: dict(v) for k, v in STATE["open_positions"].items()}
    s["orders"] = {k: dict(v) for k, v in STATE["orders"].items()}
    s["order_history"] = list(STATE["order_history"][-100:]); s["trades"] = list(STATE["trades"][-100:])
    return s


def snapshot() -> dict[str, Any]:
    with LOCK: s = copy_state()
    positions = []; unreal = 0.0
    for symbol, pos in s["open_positions"].items():
        m = market(symbol); px = float(m["price"]) if m else float(pos["entry_price"]); qty = float(pos["amount"]); cap = float(pos["allocated_usdt"])
        value = qty * px; upnl = value - cap; unreal += upnl
        positions.append({**pos, "current_price": px, "market_value": value, "unrealized_pnl": upnl, "age_sec": max(0, time.time() - float(pos["opened_ts"]))})
    equity = float(s.get("account_balance_usdt", 0)) + unreal; closed = s["trades"]; wins = sum(1 for t in closed if float(t.get("net_pnl", 0)) > 0)
    s.update({"positions": positions, "equity_usdt": equity, "unrealized_pnl": unreal, "net_pnl": equity - float(s.get("initial_balance", 0)), "balance": float(s.get("free_usdt", 0)), "pnl": float(s.get("realized_pnl", 0)), "bot_balance_usdt": float(s.get("initial_balance", 0)), "available_bot_usdt": float(s.get("free_usdt", 0)), "win_rate": round(wins / len(closed) * 100, 2) if closed else 0.0, "closed_trades": len(closed), "target_win_rate": 70.0, "adaptive_quality_threshold": adaptive_quality_threshold(), "profit_policy": "FIXED_BOT_CAPITAL_TO_MAIN_ACCOUNT"})
    return s


def pnl(cap: float, entry: float, last: float, fee_pct: float) -> tuple[float, float, float]:
    amount = cap / entry; gross = (last - entry) * amount; fee = (cap + last * amount) * fee_pct / 100
    return gross - fee, gross, fee


def close(symbol: str, pos: dict[str, Any], last: float, reason: str) -> None:
    cap = float(pos["allocated_usdt"]); entry = float(pos["entry_price"]); fee_pct = float(pos["fee_pct"]); net, gross, fee = pnl(cap, entry, last, fee_pct)
    STATE["free_usdt"] += cap; STATE["account_balance_usdt"] += net; STATE["realized_pnl"] += net; STATE["profit_reserve_usdt"] = float(STATE.get("profit_reserve_usdt", 0)) + max(0.0, net)
    STATE["trades"].append({"symbol": symbol, "side": "SELL", "entry_price": entry, "exit_price": last, "allocated_usdt": cap, "gross_pnl": gross, "fee": fee, "net_pnl": net, "reason": reason, "opened_at": pos["opened_at"], "closed_at": now(), "signal": pos.get("signal"), "quality": pos.get("quality"), "confirmations": pos.get("confirmations"), "timeframe": "3m"})
    STATE["order_history"].append({"symbol": symbol, "side": "SELL", "status": "FILLED", "price": last, "net_pnl": net, "reason": reason, "time": now()}); STATE["open_positions"].pop(symbol, None); STATE["orders"].pop(symbol, None); COOLDOWN[symbol] = time.time() + 12


def tick(symbol: str, allocation: float) -> None:
    m = market(symbol)
    if not m: return
    last = float(m["price"])
    with LOCK:
        pos = STATE["open_positions"].get(symbol); cfg = dict(STATE["config"]); fee_pct = float(cfg["fee_pct"])
        if pos:
            net, _, _ = pnl(float(pos["allocated_usdt"]), float(pos["entry_price"]), last, fee_pct); age = time.time() - float(pos["opened_ts"]); move_pct = (last / float(pos["entry_price"]) - 1) * 100; reason = None
            target_usdt = max(float(cfg["min_profit_usdt"]), float(cfg["target_profit_usdt"]))
            if net >= target_usdt: reason = "TARGET_PROFIT"
            elif net > 0 and age >= float(pos["hold_seconds"]): reason = "TIME_EXIT_PROFIT"
            elif net >= 0 and str(m.get("signal")) == "FADE": reason = "REVERSAL_PROFIT"
            elif move_pct <= -1.20: reason = "CATASTROPHIC_STOP"
            if reason: close(symbol, pos, last, reason)
            else:
                base = symbol.split("/")[0]; STATE["assets"][base] = {"amount": float(pos["amount"]), "current_price": last, "value_usdt": float(pos["amount"]) * last, "entry_value_usdt": float(pos["allocated_usdt"]), "unrealized_pnl": net}
            return
        if HALT_ENTRIES or STATE["free_usdt"] <= 0 or allocation <= 0 or time.time() < COOLDOWN.get(symbol, 0) or allocation > STATE["free_usdt"] + 1e-9: return
        d = decision(m)
        if not d["entry_ok"]: return
        amount = allocation / last; fills = [{"time": now(), "amount": amount, "price": last, "cost": allocation}]; STATE["free_usdt"] -= allocation
        STATE["orders"][symbol] = {"symbol": symbol, "side": "BUY", "requested_usdt": allocation, "requested_amount": amount, "filled_amount": amount, "status": "FILLED", "fills": fills}
        STATE["open_positions"][symbol] = {"symbol": symbol, "entry_price": last, "amount": amount, "allocated_usdt": allocation, "opened_at": now(), "opened_ts": time.time(), "fee_pct": fee_pct, "signal": "PUMP" if str(m.get("signal")) == "PUMP_NOW" else "CONFIRMED", "hold_seconds": int(m.get("hold_seconds", 180) or 180), "quality": d["quality"], "confirmations": d["confirmations"], "entry_threshold": d["threshold"], "fills": fills, "stage": "OPEN"}
        STATE["order_history"].append({**STATE["orders"][symbol], "price": last, "time": now()}); STATE["orders"].pop(symbol, None)


def loop() -> None:
    while not STOP.is_set():
        try:
            with LOCK: cfg = dict(STATE["config"])
            for i, symbol in enumerate(cfg["pairs"]): tick(symbol, float(cfg["initial_balance"]) * float(cfg["allocations"][i]) / 100)
        except Exception as exc:
            with LOCK: STATE["error"] = str(exc)[:300]
        time.sleep(1)
    with LOCK: STATE["running"] = False; STATE["stopped_at"] = now()


def start_paper(config: dict[str, Any], gateway_unused=None):
    global THREAD, HALT_ENTRIES
    pairs = [str(x).strip().upper().replace("-", "/") for x in config.get("pairs", []) if str(x).strip()]; allocations = [float(x) for x in config.get("allocations", [])]; capital = float(config.get("capital", 0))
    if not 1 <= len(pairs) <= 5: raise ValueError("Выберите от 1 до 5 пар.")
    if len(allocations) != len(pairs) or any(x <= 0 for x in allocations) or abs(sum(allocations) - 100) > 0.01: raise ValueError("Доли выбранных пар должны дать ровно 100%.")
    if capital <= 0: raise ValueError("Бюджет PAPER должен быть больше 0 USDT.")
    RADAR.start(); STOP.clear(); HALT_ENTRIES = False; COOLDOWN.clear()
    with LOCK:
        STATE.update({"running": True, "mode": "paper", "started_at": now(), "stopped_at": None, "initial_balance": capital, "account_balance_usdt": capital, "free_usdt": capital, "realized_pnl": 0.0, "profit_reserve_usdt": 0.0, "assets": {}, "open_positions": {}, "orders": {}, "order_history": [], "trades": [], "error": None, "stop_type": None, "config": {"pairs": pairs, "allocations": allocations, "initial_balance": capital, "min_profit_usdt": float(config.get("min_profit_usdt", 0.05)), "target_profit_usdt": float(config.get("target_profit_usdt", 0.10)), "fee_pct": float(config.get("fee_pct", 0.10)), "timeframe": "3m", "risk_mode": "PROFIT_FIRST", "target_win_rate": 70.0}})
    THREAD = threading.Thread(target=loop, daemon=True, name="fast-scalper-profit-first-paper"); THREAD.start(); return snapshot()


def stop_paper(gateway_unused=None):
    global HALT_ENTRIES
    HALT_ENTRIES = True; STOP.set()
    with LOCK: STATE["orders"].clear(); STATE["running"] = False; STATE["stopped_at"] = now(); STATE["stop_type"] = "STOP"
    return snapshot()


def emergency_stop_paper(gateway_unused=None):
    global HALT_ENTRIES
    HALT_ENTRIES = True; STOP.set()
    with LOCK:
        for symbol, pos in list(STATE["open_positions"].items()):
            m = market(symbol); last = float(m["price"]) if m else float(pos["entry_price"]); close(symbol, pos, last, "EMERGENCY_STOP")
        STATE["orders"].clear(); STATE["running"] = False; STATE["stopped_at"] = now(); STATE["stop_type"] = "EMERGENCY_STOP"
    return snapshot()
