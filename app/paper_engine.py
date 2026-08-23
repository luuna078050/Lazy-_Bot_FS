from __future__ import annotations
import threading, time
from datetime import datetime, timezone
from typing import Any

_state: dict[str, Any] = {
    'running': False,
    'mode': 'paper',
    'started_at': None,
    'stopped_at': None,
    'initial_balance': 0.0,
    'balance': 0.0,
    'pnl': 0.0,
    'trades': [],
    'open_positions': {},
    'config': {},
    'error': None,
}
_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()


def _now():
    return datetime.now(timezone.utc).isoformat()


def snapshot():
    with _lock:
        return {
            **_state,
            'trades': list(_state['trades'][-50:]),
            'open_positions': dict(_state['open_positions']),
        }


def _tick(symbol: str, amount_usdt: float, target_usdt: float, min_usdt: float, sl_pct: float, max_hold: int, gateway):
    g = gateway('binance')
    try:
        t = g.exchange.fetch_ticker(symbol)
        last = float(t.get('last') or 0)
        pct = float(t.get('percentage') or 0)
        if last <= 0:
            return
        with _lock:
            pos = _state['open_positions'].get(symbol)
            if pos:
                gross = (last - pos['entry_price']) * pos['amount']
                age = time.time() - pos['opened_ts']
                fee = (pos['entry_price'] * pos['amount'] + last * pos['amount']) * pos['fee_pct'] / 100
                net = gross - fee
                reason = None
                if net >= target_usdt:
                    reason = 'TARGET'
                elif sl_pct > 0 and (last / pos['entry_price'] - 1) * 100 <= -sl_pct:
                    reason = 'SL'
                elif age >= max_hold:
                    reason = 'TIMEOUT' if net >= min_usdt else 'CRITICAL_EXIT'
                if reason:
                    _state['balance'] += gross - fee
                    _state['pnl'] += gross - fee
                    _state['trades'].append({
                        'symbol': symbol, 'side': 'SELL', 'entry_price': pos['entry_price'],
                        'exit_price': last, 'amount': pos['amount'], 'gross_pnl': gross,
                        'fee': fee, 'net_pnl': gross - fee, 'reason': reason,
                        'opened_at': pos['opened_at'], 'closed_at': _now(),
                    })
                    del _state['open_positions'][symbol]
                return
            if pct < 0.15:
                return
            if _state['balance'] < amount_usdt or amount_usdt <= 0:
                return
            amount = amount_usdt / last
            fee_pct = float(_state['config'].get('fee_pct', 0.1))
            _state['balance'] -= amount_usdt
            _state['open_positions'][symbol] = {
                'symbol': symbol, 'entry_price': last, 'amount': amount,
                'allocated_usdt': amount_usdt, 'opened_at': _now(), 'opened_ts': time.time(),
                'fee_pct': fee_pct, 'signal_24h_pct': pct,
            }
    except Exception as exc:
        with _lock:
            _state['error'] = str(exc)[:300]


def _loop(gateway):
    while not _stop.is_set():
        with _lock:
            cfg = dict(_state['config'])
        pairs = cfg.get('pairs', [])
        allocs = cfg.get('allocations', [])
        for i, symbol in enumerate(pairs):
            if _stop.is_set(): break
            alloc = float(allocs[i]) if i < len(allocs) else 0
            amount = cfg['initial_balance'] * alloc / 100
            _tick(symbol, amount, cfg['target_usdt'], cfg['min_usdt'], cfg['sl_pct'], cfg['max_hold'], gateway)
        time.sleep(5)
    with _lock:
        _state['running'] = False
        _state['stopped_at'] = _now()


def start_paper(config: dict, gateway):
    global _thread
    pairs = [str(x).strip().upper() for x in config.get('pairs', []) if str(x).strip()]
    allocs = [float(x) for x in config.get('allocations', [])]
    total = sum(allocs)
    if not pairs:
        raise ValueError('Выберите хотя бы одну пару.')
    if abs(total - 100) > 0.01:
        raise ValueError('Распределение по парам должно быть ровно 100%.')
    capital = float(config.get('capital', 0))
    if capital <= 0:
        raise ValueError('Бюджет PAPER должен быть больше 0 USDT.')
    with _lock:
        _stop.clear()
        _state.update({
            'running': True, 'mode': 'paper', 'started_at': _now(), 'stopped_at': None,
            'initial_balance': capital, 'balance': capital, 'pnl': 0.0,
            'trades': [], 'open_positions': {}, 'error': None,
            'config': {
                'pairs': pairs, 'allocations': allocs, 'initial_balance': capital,
                'target_usdt': float(config.get('target_usdt', .30)),
                'min_usdt': float(config.get('min_usdt', .20)),
                'sl_pct': float(config.get('sl_pct', .50)),
                'max_hold': int(config.get('max_hold', 180)),
                'fee_pct': float(config.get('fee_pct', .1)),
            },
        })
    _thread = threading.Thread(target=_loop, args=(gateway,), daemon=True)
    _thread.start()
    return snapshot()


def stop_paper(gateway):
    _stop.set()
    with _lock:
        for symbol, pos in list(_state['open_positions'].items()):
            try:
                last = float(gateway('binance').exchange.fetch_ticker(symbol).get('last') or pos['entry_price'])
                gross = (last - pos['entry_price']) * pos['amount']
                fee = (pos['entry_price'] * pos['amount'] + last * pos['amount']) * pos['fee_pct'] / 100
                _state['balance'] += gross - fee
                _state['pnl'] += gross - fee
                _state['trades'].append({'symbol': symbol, 'side': 'SELL', 'entry_price': pos['entry_price'], 'exit_price': last, 'amount': pos['amount'], 'gross_pnl': gross, 'fee': fee, 'net_pnl': gross-fee, 'reason': 'MANUAL_STOP', 'opened_at': pos['opened_at'], 'closed_at': _now()})
            except Exception:
                _state['balance'] += pos['allocated_usdt']
            del _state['open_positions'][symbol]
        _state['running'] = False
        _state['stopped_at'] = _now()
    return snapshot()
