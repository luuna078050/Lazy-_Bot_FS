from __future__ import annotations

import json
import os
import threading

from . import profit_first_engine_v3 as base


PATH = os.getenv('FAST_SCALPER_PAPER_STATE_FILE', 'fast_scalper_paper_state.json')
_IO_LOCK = threading.Lock()


def _save_locked():
    data = {
        'running': bool(base.STATE.get('running')),
        'mode': base.STATE.get('mode', 'paper'),
        'started_at': base.STATE.get('started_at'),
        'stopped_at': base.STATE.get('stopped_at'),
        'initial_balance': base.STATE.get('initial_balance', 0.0),
        'account_balance_usdt': base.STATE.get('account_balance_usdt', 0.0),
        'free_usdt': base.STATE.get('free_usdt', 0.0),
        'realized_pnl': base.STATE.get('realized_pnl', 0.0),
        'profit_reserve_usdt': base.STATE.get('profit_reserve_usdt', 0.0),
        'open_positions': base.STATE.get('open_positions', {}),
        'orders': base.STATE.get('orders', {}),
        'order_history': list(base.STATE.get('order_history', [])[-100:]),
        'trades': list(base.STATE.get('trades', [])[-100:]),
        'config': base.STATE.get('config', {}),
        'error': base.STATE.get('error'),
        'stop_type': base.STATE.get('stop_type'),
        'pnl_window': list(base.STATE.get('pnl_window', [])[-100:]),
    }
    tmp = PATH + '.tmp'
    with _IO_LOCK:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, PATH)


def save():
    with base.LOCK:
        _save_locked()


def restore():
    if not os.path.exists(PATH):
        return False
    try:
        with open(PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if d.get('mode') != 'paper' or not d.get('config'):
            return False
        with base.LOCK:
            for key in ('mode','started_at','stopped_at','initial_balance','account_balance_usdt',
                        'free_usdt','realized_pnl','profit_reserve_usdt','open_positions','orders',
                        'order_history','trades','config','error','stop_type','pnl_window'):
                if key in d:
                    base.STATE[key] = d[key]
            base.STATE['running'] = bool(d.get('running', False))
        return bool(d.get('running', False))
    except Exception as exc:
        with base.LOCK:
            base.STATE['error'] = f'PAPER state restore: {str(exc)[:250]}'
        return False


def start_existing():
    global_thread = getattr(base, 'THREAD', None)
    if global_thread and global_thread.is_alive():
        return base.snapshot()
    if not base.STATE.get('running'):
        return base.snapshot()
    # The v4 engine is the active PAPER engine. On a process restart no
    # start_paper() call occurs, so explicitly restore its tick implementation.
    from .profit_first_engine_v4 import tick as active_tick
    base.tick = active_tick
    base.RADAR.start()
    base.STOP.clear()
    base.HALT_ENTRIES = False
    base.THREAD = threading.Thread(target=base.loop, daemon=True, name='fast-scalper-throughput-paper-resume')
    base.THREAD.start()
    return base.snapshot()


def install():
    resumed = restore()

    original_start = base.start_paper
    original_stop = base.stop_paper
    original_emergency = base.emergency_stop_paper
    original_close = base.close_position

    def start(config, gateway_unused=None):
        # Starting PAPER while it is already running must NOT wipe positions.
        if base.STATE.get('running'):
            return base.snapshot()
        result = original_start(config, gateway_unused)
        save()
        return result

    def stop(gateway_unused=None):
        result = original_stop(gateway_unused)
        save()
        return result

    def emergency(gateway_unused=None):
        result = original_emergency(gateway_unused)
        save()
        return result

    def close(sym, pos, last, reason):
        original_close(sym, pos, last, reason)
        save()

    base.start_paper = start
    base.stop_paper = stop
    base.emergency_stop_paper = emergency
    base.close_position = close

    original_tick = base.tick
    def tick(sym, allocation, tf):
        before = set(base.STATE.get('open_positions', {}).keys())
        original_tick(sym, allocation, tf)
        after = set(base.STATE.get('open_positions', {}).keys())
        if before != after:
            save()
    base.tick = tick

    if resumed:
        start_existing()
