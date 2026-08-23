"""Run LazyBot FS with a one-second Rocket Hunter micro layer.

Strategic scanner: existing live_scalper_20.py (default every 20s).
Micro layer: Binance websocket pulse, evaluated every second.

The two layers are intentionally separate so slow REST analysis cannot block
the 1-second reaction loop.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from app.exchange_gateway import gateway
from app.realtime_execution import micro_entry
from app.realtime_pulse import RealtimePulse, discover_usdt_symbols
from scripts.live_scalper_20 import _load_state, _save_state, run_once

load_dotenv()


def main():
    ex = gateway(os.getenv("EXCHANGE", "binance"))
    state = _load_state()
    symbols = discover_usdt_symbols(int(os.getenv("PULSE_UNIVERSE", "30")))
    if not symbols:
        raise RuntimeError("Could not discover Binance USDT symbols for realtime pulse")
    pulse = RealtimePulse(symbols)
    pulse.start()

    strategic_interval = max(5, int(os.getenv("STRATEGIC_SCAN_SECONDS", "20")))

    def strategic_loop():
        while True:
            try:
                result = run_once(ex, state)
                print(json.dumps({"layer": "STRATEGIC", **result}, ensure_ascii=False, default=str))
            except Exception as exc:
                print(json.dumps({"layer": "STRATEGIC", "error": str(exc)}, ensure_ascii=False))
            time.sleep(strategic_interval)

    threading.Thread(target=strategic_loop, name="lazybot-strategic", daemon=True).start()
    print(f"LazyBot FS realtime | pulse=1s | strategic={strategic_interval}s | symbols={len(symbols)}")

    try:
        while True:
            started = time.monotonic()
            snapshots = pulse.snapshot()
            # One-second micro reaction. A pulse is deliberately much stricter
            # than a normal trend signal because it can react to a 2-3 second burst.
            candidates = sorted(snapshots.values(), key=lambda p: float(p.get("score", 0)), reverse=True)
            for p in candidates[:3]:
                event = micro_entry(
                    ex,
                    state,
                    p,
                    float(os.getenv("BOT_ACCOUNT_BALANCE", os.getenv("TEST_CAPITAL_USDT", "20"))),
                    float(os.getenv("PULSE_ALLOCATION_PCT", "10")),
                    int(os.getenv("MAX_POSITIONS", "5")),
                )
                if event:
                    print(json.dumps({"layer": "REALTIME", "event": "ENTRY", **event}, ensure_ascii=False, default=str))
                    _save_state(state)
            elapsed = time.monotonic() - started
            time.sleep(max(0.05, 1.0 - elapsed))
    except KeyboardInterrupt:
        pulse.stop()


if __name__ == "__main__":
    main()
