from __future__ import annotations
import threading
import time
from . import profit_first_engine_v3 as base


def install():
    if getattr(base, '_fs_reinvest_patch', False):
        return
    original_start = base.start_paper
    original_loop = base.loop

    def loop_reinvest():
        while not base.STOP.is_set():
            try:
                with base.LOCK:
                    cfg = dict(base.STATE.get('config') or {})
                    reinvest = bool(cfg.get('reinvest_profit', getattr(base, '_fs_reinvest_request', False)))
                    initial = float(cfg.get('initial_balance', 0) or 0)
                    reserve = float(base.STATE.get('profit_reserve_usdt', 0) or 0)
                    base_capital = initial + reserve if reinvest else initial
                for i, sym in enumerate(cfg.get('pairs', [])):
                    tf = (cfg.get('timeframes') or ['3m'] * len(cfg.get('pairs', [])))[i]
                    allocation = base_capital * float(cfg.get('allocations', [])[i]) / 100
                    base.tick(sym, allocation, tf)
            except Exception as exc:
                with base.LOCK:
                    base.STATE['error'] = str(exc)[:300]
            time.sleep(1)
        with base.LOCK:
            base.STATE['running'] = False
            base.STATE['stopped_at'] = base.now()

    def start(config, gateway_unused=None):
        base._fs_reinvest_request = bool(config.get('reinvest_profit', False))
        result = original_start(config, gateway_unused)
        with base.LOCK:
            base.STATE.setdefault('config', {})['reinvest_profit'] = base._fs_reinvest_request
        return result

    base.loop = loop_reinvest
    base.start_paper = start
    base._fs_reinvest_patch = True
