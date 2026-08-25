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

TARGET_PNL_PER_MIN_PER_100 = 1.73
COOLDOWN_SECONDS = 180
FREEZE_EXIT_MIN_PNL = 0.15

STATE: dict[str, Any] = {
    "running": False, "mode": "paper", "started_at": None, "stopped_at": None,
    "initial_balance": 0.0, "account_balance_usdt": 0.0, "free_usdt": 0.0,
    "realized_pnl": 0.0, "profit_reserve_usdt": 0.0, "assets": {},
    "open_positions": {}, "orders": {}, "order_history": [], "trades": [],
    "config": {}, "error": None, "stop_type": None,
    "pnl_window": [],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def market(symbol: str) -> dict[str, Any] | None:
    key = symbol.replace("/", "").upper()
    with RADAR.lock:
        ticker = dict(RADAR.tickers.get(key) or {})
        if not ticker:
            return None
        price = float(ticker.get("c") or 0)
        pulse = RADAR._pulse(key)
        tf = RADAR._timeframe_metrics(key, price)
        # Some older radar builds expose the compatibility alias instead.
        if not tf:
            tf = RADAR._three_min_metrics(key, price)
    if price <= 0:
        return None
    return {
        "price": price,
        "change_24h_pct": float(ticker.get("P") or 0),
        "quote_volume_24h": float(ticker.get("q") or 0),
        **tf, **pulse,
    }


def pnl(cap: float, entry: float, last: float, fee_pct: float) -> tuple[float, float, float]:
    amount = cap / entry
    gross = (last - entry) * amount
    fee = (cap + last * amount) * fee_pct / 100
    return gross - fee, gross, fee


def adaptive_quality_threshold() -> float:
    trades = STATE.get("trades", [])[-30:]
    if len(trades) < 8:
        return 52.0
    wins = sum(1 for t in trades if float(t.get("net_pnl", 0)) > 0)
    wr = wins / len(trades) * 100
    if wr < 55: return 72.0
    if wr < 65: return 66.0
    if wr < 70: return 60.0
    return 56.0


def decision(m: dict[str, Any]) -> dict[str, Any]:
    score = float(m.get("score", 0) or 0)
    c1 = float(m.get("change_1m_pct", 0) or 0)
    c3 = float(m.get("change_3m_pct", 0) or 0)
    vr = float(m.get("volume_ratio", 1) or 1)
    buy = float(m.get("buy_ratio", 0.5) or 0.5)
    surge = float(m.get("volume_surge", 0) or 0)
    stability = float(m.get("stability", 0) or 0)
    signal = str(m.get("signal", "WAIT"))
    momentum = max(0.0, min(1.0, c3 / 0.60))
    acceleration = max(0.0, min(1.0, (c1 * 2.5 + c3) / 1.2))
    flow = max(0.0, min(1.0, (buy - 0.50) / 0.18))
    volume = max(0.0, min(1.0, (vr - 1.0) / 2.0))
    quality = 100 * (0.40 * score / 100 + 0.18 * momentum + 0.12 * acceleration + 0.15 * flow + 0.10 * volume + 0.05 * stability)
    confirmations = sum((score >= 55, c3 >= 0.03, vr >= 1.20 or surge >= 0.07, buy >= 0.53, signal not in {"WAIT", "FADE"}))
    threshold = adaptive_quality_threshold()
    entry_ok = confirmations >= 3 and quality >= threshold and signal not in {"WAIT", "FADE"}
    return {"quality": round(quality, 2), "confirmations": confirmations, "threshold": threshold, "entry_ok": entry_ok}


def snapshot() -> dict[str, Any]:
    with LOCK:
        s = dict(STATE)
        s["assets"] = {k: dict(v) for k, v in STATE["assets"].items()}
        s["open_positions"] = {k: dict(v) for k, v in STATE["open_positions"].items()}
        s["orders"] = {k: dict(v) for k, v in STATE["orders"].items()}
        s["trades"] = list(STATE["trades"][-100:])
        s["order_history"] = list(STATE["order_history"][-100:])
    unreal = 0.0
    positions = []
    for symbol, pos in s["open_positions"].items():
        m = market(symbol)
        px = float(m["price"]) if m else float(pos["entry_price"])
        cap = float(pos["allocated_usdt"])
        qty = float(pos["amount"])
        upnl = qty * px - cap
        unreal += upnl
        positions.append({**pos, "current_price": px, "market_value": qty * px, "unrealized_pnl": upnl, "age_sec": max(0, time.time() - float(pos["opened_ts"]))})
    closed = s["trades"]
    wins = sum(1 for t in closed if float(t.get("net_pnl", 0)) > 0)
    minute_start = time.time() - 60
    minute_pnl = sum(float(x["pnl"]) for x in s.get("pnl_window", []) if float(x.get("ts", 0)) >= minute_start)
    capital = float(s.get("initial_balance", 0) or 0)
    target = capital * TARGET_PNL_PER_MIN_PER_100 / 100
    throughput = minute_pnl / capital * 100 if capital > 0 else 0
    s.update({
        "positions": positions, "equity_usdt": float(s.get("account_balance_usdt", 0)) + unreal,
        "unrealized_pnl": unreal, "net_pnl": float(s.get("account_balance_usdt", 0)) + unreal - capital,
        "balance": float(s.get("free_usdt", 0)), "pnl": float(s.get("realized_pnl", 0)),
        "bot_balance_usdt": capital, "available_bot_usdt": float(s.get("free_usdt", 0)),
        "win_rate": round(wins / len(closed) * 100, 2) if closed else 0.0,
        "closed_trades": len(closed), "target_win_rate": 70.0,
        "target_pnl_per_min_per_100": TARGET_PNL_PER_MIN_PER_100,
        "target_pnl_per_min_usdt": round(target, 4), "realized_pnl_last_minute": round(minute_pnl, 4),
        "throughput_pnl_per_min_per_100": round(throughput, 4),
        "capital_efficiency_mode": "PORTFOLIO_THROUGHPUT",
        "profit_policy": "FIXED_BOT_CAPITAL_TO_MAIN_ACCOUNT",
        "max_pairs": 10,
    })
    return s


def record_close(symbol: str, pos: dict[str, Any], last: float, reason: str) -> None:
    cap = float(pos["allocated_usdt"]); entry = float(pos["entry_price"]); fee_pct = float(pos["fee_pct"])
    net, gross, fee = pnl(cap, entry, last, fee_pct)
    STATE["free_usdt"] += cap
    STATE["account_balance_usdt"] += net
    STATE["realized_pnl"] += net
    if net > 0:
        STATE["profit_reserve_usdt"] += net
    trade = {"symbol": symbol, "side": "SELL", "entry_price": entry, "exit_price": last,
             "allocated_usdt": cap, "gross_pnl": gross, "fee": fee, "net_pnl": net,
             "reason": reason, "opened_at": pos["opened_at"], "closed_at": now(),
             "quality": pos.get("quality"), "timeframe": pos.get("timeframe", "3m"),
             "maker_preferred": True}
    STATE["trades"].append(trade)
    STATE["pnl_window"].append({"ts": time.time(), "pnl": net})
    STATE["order_history"].append({"symbol": symbol, "side": "SELL", "status": "FILLED", "price": last, "net_pnl": net, "reason": reason, "time": now()})
    STATE["open_positions"].pop(symbol, None)
    STATE["orders"].pop(symbol, None)
    COOLDOWN[symbol] = time.time() + COOLDOWN_SECONDS


def tick(symbol: str, allocation: float, timeframe: str) -> None:
    m = market(symbol)
    if not m:
        return
    last = float(m["price"])
    with LOCK:
        cfg = dict(STATE["config"])
        pos = STATE["open_positions"].get(symbol)
        fee_pct = float(cfg.get("fee_pct", 0.10))
        if pos:
            net, _, _ = pnl(float(pos["allocated_usdt"]), float(pos["entry_price"]), last, fee_pct)
            age = time.time() - float(pos["opened_ts"])
            freeze = (float(m.get("volume_ratio", 1)) < 0.85 or float(m.get("buy_ratio", 0.5)) < 0.49 or float(m.get("change_1m_pct", 0)) < 0.005)
            # The timeframe is a decision horizon, never a mandatory hold time.
            target = max(FREEZE_EXIT_MIN_PNL, float(pos["target_profit_usdt"]))
            reason = None
            if net >= target:
                reason = "TARGET_PROFIT"
            elif net > 0 and freeze and net >= FREEZE_EXIT_MIN_PNL:
                reason = "FREEZE_PROFIT_EXIT"
            elif net > 0 and age >= float(pos["max_hold_seconds"]) and freeze:
                reason = "TIME_OPPORTUNITY_EXIT"
            elif net < 0 and age >= float(pos["max_hold_seconds"]) and freeze:
                reason = "HYPOTHESIS_FAILED"
            elif (last / float(pos["entry_price"]) - 1) * 100 <= -1.20:
                reason = "CATASTROPHIC_STOP"
            if reason:
                record_close(symbol, pos, last, reason)
            else:
                base = symbol.split("/")[0]
                STATE["assets"][base] = {"amount": float(pos["amount"]), "current_price": last, "value_usdt": float(pos["amount"]) * last, "entry_value_usdt": float(pos["allocated_usdt"]), "unrealized_pnl": net}
            return
        if HALT_ENTRIES or STATE["free_usdt"] <= 0 or allocation <= 0 or allocation > STATE["free_usdt"] + 1e-9:
            return
        if time.time() < COOLDOWN.get(symbol, 0):
            return
        # Use live ranking data from the radar when available.
        d = decision(m)
        if not d["entry_ok"]:
            return
        amount = allocation / last
        target = allocation * TARGET_PNL_PER_MIN_PER_100 / 100
        # Shorter horizons get a tighter, faster decision window; never a forced hold.
        horizon = {"1m": 60, "3m": 180, "5m": 300}.get(timeframe, 180)
        STATE["free_usdt"] -= allocation
        STATE["open_positions"][symbol] = {
            "symbol": symbol, "entry_price": last, "amount": amount, "allocated_usdt": allocation,
            "opened_at": now(), "opened_ts": time.time(), "fee_pct": fee_pct,
            "signal": "PUMP" if str(m.get("signal")) == "PUMP_NOW" else "CONFIRMED",
            "hold_seconds": horizon, "max_hold_seconds": horizon, "timeframe": timeframe,
            "target_profit_usdt": target, "target_profit_per_min_usdt": target,
            "quality": d["quality"], "confirmations": d["confirmations"], "entry_threshold": d["threshold"],
            "maker_preferred": True, "stage": "OPEN",
        }
        STATE["order_history"].append({"symbol": symbol, "side": "BUY", "status": "FILLED", "price": last, "cost": allocation, "time": now()})


def loop() -> None:
    while not STOP.is_set():
        try:
            with LOCK:
                cfg = dict(STATE["config"])
            pairs = cfg.get("pairs", [])
            allocations = cfg.get("allocations", [])
            timeframes = cfg.get("timeframes", [])
            for i, symbol in enumerate(pairs):
                tf = timeframes[i] if i < len(timeframes) else "3m"
                alloc = float(cfg["initial_balance"]) * float(allocations[i]) / 100
                tick(symbol, alloc, tf)
        except Exception as exc:
            with LOCK:
                STATE["error"] = str(exc)[:300]
        time.sleep(1)
    with LOCK:
        STATE["running"] = False
        STATE["stopped_at"] = now()


def start_paper(config: dict[str, Any], gateway_unused=None):
    global THREAD, HALT_ENTRIES
    pairs = [str(x).strip().upper().replace("-", "/") for x in config.get("pairs", []) if str(x).strip()]
    allocations = [float(x) for x in config.get("allocations", [])]
    timeframes = [str(x).lower() for x in config.get("timeframes", [])]
    capital = float(config.get("capital", 0))
    if not 1 <= len(pairs) <= 10:
        raise ValueError("Выберите от 1 до 10 пар.")
    if len(allocations) != len(pairs) or any(x <= 0 for x in allocations) or sum(allocations) <= 0 or sum(allocations) > 100.0001:
        raise ValueError("Доли должны быть больше 0% и в сумме не превышать 100%.")
    if timeframes and len(timeframes) != len(pairs):
        raise ValueError("Количество таймфреймов должно совпадать с количеством выбранных пар.")
    if not timeframes:
        timeframes = [str(config.get("timeframe", "3m")).lower()] * len(pairs)
    if any(x not in {"1m", "3m", "5m"} for x in timeframes):
        raise ValueError("Допустимые таймфреймы: 1m, 3m, 5m.")
    if capital <= 0:
        raise ValueError("Бюджет PAPER должен быть больше 0 USDT.")
    RADAR.start(); STOP.clear(); HALT_ENTRIES = False; COOLDOWN.clear()
    with LOCK:
        STATE.update({"running": True, "mode": "paper", "started_at": now(), "stopped_at": None,
                      "initial_balance": capital, "account_balance_usdt": capital, "free_usdt": capital,
                      "realized_pnl": 0.0, "profit_reserve_usdt": 0.0, "assets": {}, "open_positions": {},
                      "orders": {}, "order_history": [], "trades": [], "error": None, "stop_type": None,
                      "pnl_window": [],
                      "config": {"pairs": pairs, "allocations": allocations, "allocated_pct": sum(allocations),
                                 "unused_capital_pct": 100 - sum(allocations), "initial_balance": capital,
                                 "min_profit_usdt": float(config.get("min_profit_usdt", 0.05)),
                                 "target_profit_usdt": float(config.get("target_profit_usdt", 0.10)),
                                 "fee_pct": float(config.get("fee_pct", 0.10)), "timeframes": timeframes,
                                 "risk_mode": "PROFIT_FIRST", "target_win_rate": 70.0,
                                 "target_pnl_per_min_per_100": TARGET_PNL_PER_MIN_PER_100}})
    THREAD = threading.Thread(target=loop, daemon=True, name="fast-scalper-throughput-paper")
    THREAD.start()
    return snapshot()


def stop_paper(gateway_unused=None):
    global HALT_ENTRIES
    HALT_ENTRIES = True; STOP.set()
    with LOCK:
        STATE["orders"].clear(); STATE["running"] = False; STATE["stopped_at"] = now(); STATE["stop_type"] = "STOP"
    return snapshot()


def emergency_stop_paper(gateway_unused=None):
    global HALT_ENTRIES
    HALT_ENTRIES = True; STOP.set()
    with LOCK:
        for symbol, pos in list(STATE["open_positions"].items()):
            m = market(symbol); last = float(m["price"]) if m else float(pos["entry_price"])
            record_close(symbol, pos, last, "EMERGENCY_STOP")
        STATE["orders"].clear(); STATE["running"] = False; STATE["stopped_at"] = now(); STATE["stop_type"] = "EMERGENCY_STOP"
    return snapshot()
