"""LazyBot FS — 30 USDT realtime PAPER test.

Uses the live Binance public trade websocket but NEVER places a real order.
The bot models entries/exits every second so short 2-3 second Rocket Hunter
bursts can be tested before any live capital is armed.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from dotenv import load_dotenv

from app.realtime_pulse import RealtimePulse, discover_usdt_symbols

load_dotenv()

CAPITAL = float(os.getenv("TEST_BOT_BALANCE_USDT", "30"))
MAX_POSITIONS = int(os.getenv("TEST_MAX_POSITIONS", "3"))
SCAN_UNIVERSE = int(os.getenv("TEST_PULSE_UNIVERSE", "30"))
TARGET_PER_UNIT = float(os.getenv("TEST_PROFIT_TARGET_PER_UNIT", "0.25"))
FLOOR_PER_UNIT = float(os.getenv("TEST_PROFIT_FLOOR_PER_UNIT", "0.20"))
TARGET_INTERVAL = int(os.getenv("TEST_TARGET_INTERVAL_SEC", "90"))
MAX_HOLD = int(os.getenv("TEST_MAX_HOLD_SEC", "180"))
FEE_PCT = float(os.getenv("TEST_ROUND_TRIP_FEE_PCT", "0.0")) / 100.0
SL_ENABLED = os.getenv("TEST_STOP_LOSS_ENABLED", "false").lower() == "true"
SL_PCT = float(os.getenv("TEST_STOP_LOSS_PCT", "0.30")) / 100.0
STATE_FILE = Path(os.getenv("TEST_STATE_FILE", "test_scalper_30_state.json"))


@dataclass
class Position:
    symbol: str
    entry: float
    capital: float
    opened: float
    score: float
    entry_state: str

    @property
    def amount(self) -> float:
        return self.capital / self.entry


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"capital": CAPITAL, "realized_pnl": 0.0, "trades": [], "positions": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def allocation(score: float) -> float:
    # Existing LazyBot capital philosophy: 10/20/30% by signal quality.
    if score >= 0.88:
        return 0.30
    if score >= 0.78:
        return 0.20
    return 0.10


def net_profit(pos: Position, price: float) -> float:
    gross = pos.amount * (price - pos.entry)
    fees = (pos.capital + pos.amount * price) * FEE_PCT / 2.0
    return gross - fees


def close_position(state: dict, pos: Position, price: float, reason: str, now: float) -> None:
    pnl = net_profit(pos, price)
    state["realized_pnl"] += pnl
    state["capital"] += pos.capital + pnl
    state["trades"].append({
        "ts": now,
        "symbol": pos.symbol,
        "entry": pos.entry,
        "exit": price,
        "capital": pos.capital,
        "pnl": pnl,
        "pnl_per_unit": pnl / pos.capital if pos.capital else 0.0,
        "hold_sec": now - pos.opened,
        "reason": reason,
    })
    state["positions"].pop(pos.symbol, None)


def main() -> None:
    symbols = discover_usdt_symbols(SCAN_UNIVERSE)
    if not symbols:
        raise RuntimeError("Unable to discover Binance USDT spot symbols")
    pulse = RealtimePulse(symbols)
    pulse.start()
    state = load_state()
    print(json.dumps({
        "mode": "PAPER_REALTIME",
        "capital": state["capital"],
        "universe": len(symbols),
        "pulse": "1s",
        "target_profit_per_unit": TARGET_PER_UNIT,
        "profit_floor_per_unit": FLOOR_PER_UNIT,
        "target_trade_interval_sec": TARGET_INTERVAL,
        "max_hold_sec": MAX_HOLD,
        "stop_loss": SL_ENABLED,
        "live_orders": False,
    }, ensure_ascii=False))
    try:
        while True:
            now = time.time()
            snapshots = pulse.snapshot()

            # EXIT FIRST: the test bot must be able to recycle capital quickly.
            for symbol, raw in list(snapshots.items()):
                if symbol not in state["positions"]:
                    continue
                pos = Position(**state["positions"][symbol])
                price = float(raw["price"])
                age = now - pos.opened
                pnl = net_profit(pos, price)
                target = pos.capital * TARGET_PER_UNIT
                floor = pos.capital * FLOOR_PER_UNIT
                if pnl >= target:
                    close_position(state, pos, price, "TARGET_PROFIT", now)
                elif age >= TARGET_INTERVAL and pnl >= floor:
                    close_position(state, pos, price, "TIME_FLOOR", now)
                elif SL_ENABLED and price <= pos.entry * (1.0 - SL_PCT):
                    close_position(state, pos, price, "STOP_LOSS", now)
                elif age >= MAX_HOLD and pnl >= 0:
                    close_position(state, pos, price, "MAX_HOLD_RECYCLE", now)

            # ENTRY: only the strongest realtime Rocket Hunter pulses.
            candidates = sorted(snapshots.values(), key=lambda x: float(x.get("score", 0.0)), reverse=True)
            free = MAX_POSITIONS - len(state["positions"])
            for p in candidates[:5]:
                if free <= 0:
                    break
                if p.get("state") not in {"IGNITION", "EARLY_ROCKET"}:
                    continue
                score = float(p.get("score", 0.0))
                if score < 0.72:
                    continue
                symbol = p["symbol"]
                if symbol in state["positions"]:
                    continue
                if float(p.get("price_change_2s", 0.0)) < 0.0018:
                    continue
                if float(p.get("volume_ratio", 0.0)) < 2.0:
                    continue
                if float(p.get("buy_ratio", 0.5)) < 0.58:
                    continue
                pct = allocation(score)
                capital = state["capital"] * pct
                if capital <= 0.50:
                    continue
                pos = Position(symbol, float(p["price"]), capital, now, score, p["state"])
                state["capital"] -= capital
                state["positions"][symbol] = asdict(pos)
                free -= 1
                print(json.dumps({"event": "PAPER_ENTRY", **asdict(pos), "pulse_2s": p["price_change_2s"], "volume_ratio": p["volume_ratio"]}, ensure_ascii=False))

            save_state(state)
            if state["trades"]:
                recent = state["trades"][-1]
                print(json.dumps({"event": "STATUS", "free_capital": state["capital"], "realized_pnl": state["realized_pnl"], "open_positions": len(state["positions"]), "last_trade": recent}, ensure_ascii=False))
            time.sleep(1.0)
    except KeyboardInterrupt:
        pulse.stop()
        save_state(state)
        print("Stopped. State saved.")


if __name__ == "__main__":
    main()
