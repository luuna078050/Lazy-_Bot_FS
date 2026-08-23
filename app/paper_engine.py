from __future__ import annotations
import threading, time
from datetime import datetime, timezone
from typing import Any

_state: dict[str, Any] = {
    'running': False, 'mode': 'paper', 'started_at': None, 'stopped_at': None,
    'initial_balance': 0.0, 'balance': 0.0, 'pnl': 0.0, 'trades': [],
    'open_positions': {}, 'orders': {}, 'config': {}, 'error': None,
    'stop_type': None,
}
_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()


def _now():
    return datetime.now(timezone.utc).isoformat()


def snapshot():
    with _lock:
        return {**_state, 'trades': list(_state['trades'][-100:]),
                'open_positions': {k: dict(v) for k, v in _state['open_positions'].items()},
                'orders': {k: dict(v) for k, v in _state['orders'].items()}}


def _close_position(symbol: str, pos: dict, last: float, reason: str):
    gross = (last - pos['entry_price']) * pos['amount']
    fee = (pos['entry_price'] * pos['amount'] + last * pos['amount']) * pos['fee_pct'] / 100
    net = gross - fee
    _state['balance'] += pos['allocated_usdt'] + net
    _state['pnl'] += net
    _state['trades'].append({
        'symbol': symbol, 'side': 'SELL', 'entry_price': pos['entry_price'], 'exit_price': last,
        'amount': pos['amount'], 'gross_pnl': gross, 'fee': fee, 'net_pnl': net,
        'reason': reason, 'opened_at': pos['opened_at'], 'closed_at': _now(),
        'fills': list(pos.get('fills', [])), 'fill_count': len(pos.get('fills', [])),
    })
    _state['open_positions'].pop(symbol, None)
    _state['orders'].pop(symbol, None)


def _tick(symbol: str, allocation_usdt: float, target_usdt: float, min_usdt: float,
          sl_pct: float, max_hold: int, gateway):
    try:
        last = float(gateway('binance').exchange.fetch_ticker(symbol).get('last') or 0)
        pct = float(gateway('binance').exchange.fetch_ticker(symbol).get('percentage') or 0)
        if last <= 0: return
        with _lock:
            pos = _state['open_positions'].get(symbol)
            if pos:
                gross = (last - pos['entry_price']) * pos['amount']
                age = time.time() - pos['opened_ts']
                fee = (pos['entry_price'] * pos['amount'] + last * pos['amount']) * pos['fee_pct'] / 100
                net = gross - fee
                reason = None
                if net >= target_usdt: reason = 'TARGET'
                elif sl_pct > 0 and (last / pos['entry_price'] - 1) * 100 <= -sl_pct: reason = 'SL'
                elif age >= max_hold: reason = 'TIMEOUT' if net >= min_usdt else 'CRITICAL_EXIT'
                if reason: _close_position(symbol, pos, last, reason)
                return
            if pct < 0.15 or _state['balance'] <= 0 or allocation_usdt <= 0: return
            # Simulate a Binance limit order being filled in multiple executions.
            order = _state['orders'].get(symbol)
            if not order:
                order = {'symbol': symbol, 'side': 'BUY', 'requested_usdt': allocation_usdt,
                         'requested_amount': allocation_usdt / last, 'filled_amount': 0.0,
                         'remaining_amount': allocation_usdt / last, 'status': 'NEW', 'fills': []}
                _state['orders'][symbol] = order
            remaining = order['remaining_amount']
            chunk = min(remaining, order['requested_amount'] * 0.20)
            fee_pct = float(_state['config'].get('fee_pct', 0.1))
            if chunk <= 0: return
            cost = chunk * last
            if cost > _state['balance']: chunk = _state['balance'] / last; cost = chunk * last
            if chunk <= 0: return
            _state['balance'] -= cost
            order['fills'].append({'time': _now(), 'amount': chunk, 'price': last, 'cost': cost})
            order['filled_amount'] += chunk; order['remaining_amount'] -= chunk
            order['status'] = 'FILLED' if order['remaining_amount'] <= order['requested_amount'] * 0.00001 else 'PARTIALLY_FILLED'
            avg = sum(f['amount'] * f['price'] for f in order['fills']) / order['filled_amount']
            if order['status'] == 'FILLED':
                _state['open_positions'][symbol] = {'symbol': symbol, 'entry_price': avg,
                    'amount': order['filled_amount'], 'allocated_usdt': sum(f['cost'] for f in order['fills']),
                    'opened_at': order['fills'][0]['time'], 'opened_ts': time.time(),
                    'fee_pct': fee_pct, 'signal_24h_pct': pct, 'fills': list(order['fills'])}
            else:
                _state['open_positions'][symbol] = {'symbol': symbol, 'entry_price': avg,
                    'amount': order['filled_amount'], 'allocated_usdt': sum(f['cost'] for f in order['fills']),
                    'opened_at': order['fills'][0]['time'], 'opened_ts': time.time(),
                    'fee_pct': fee_pct, 'signal_24h_pct': pct, 'fills': list(order['fills']),
                    'requested_amount': order['requested_amount'], 'remaining_amount': order['remaining_amount'],
                    'order_status': order['status']}
    except Exception as exc:
        with _lock: _state['error'] = str(exc)[:300]


def _loop(gateway):
    while not _stop.is_set():
        with _lock: cfg = dict(_state['config'])
        for i, symbol in enumerate(cfg.get('pairs', [])):
            if _stop.is_set(): break
            alloc = float(cfg.get('allocations', [])[i]) if i < len(cfg.get('allocations', [])) else 0
            _tick(symbol, cfg['initial_balance'] * alloc / 100, cfg['target_usdt'], cfg['min_usdt'], cfg['sl_pct'], cfg['max_hold'], gateway)
        time.sleep(5)
    with _lock:
        _state['running'] = False; _state['stopped_at'] = _now()


def start_paper(config: dict, gateway):
    global _thread
    pairs = [str(x).strip().upper() for x in config.get('pairs', []) if str(x).strip()]
    allocs = [float(x) for x in config.get('allocations', [])]
    if not pairs: raise ValueError('Выберите хотя бы одну пару.')
    if abs(sum(allocs) - 100) > 0.01: raise ValueError('Распределение по парам должно быть ровно 100%.')
    capital = float(config.get('capital', 0))
    if capital <= 0: raise ValueError('Бюджет PAPER должен быть больше 0 USDT.')
    with _lock:
        _stop.clear()
        _state.update({'running': True, 'mode': 'paper', 'started_at': _now(), 'stopped_at': None,
            'initial_balance': capital, 'balance': capital, 'pnl': 0.0, 'trades': [],
            'open_positions': {}, 'orders': {}, 'error': None, 'stop_type': None,
            'config': {'pairs': pairs, 'allocations': allocs, 'initial_balance': capital,
                'target_usdt': float(config.get('target_usdt', .30)), 'min_usdt': float(config.get('min_usdt', .20)),
                'sl_pct': float(config.get('sl_pct', .50)), 'max_hold': int(config.get('max_hold', 180)),
                'fee_pct': float(config.get('fee_pct', .1))}})
    _thread = threading.Thread(target=_loop, args=(gateway,), daemon=True); _thread.start()
    return snapshot()


def stop_paper(gateway):
    # Normal STOP freezes the bot. Existing simulated orders/positions remain visible and untouched.
    _stop.set()
    with _lock:
        _state['running'] = False; _state['stopped_at'] = _now(); _state['stop_type'] = 'STOP'
    return snapshot()


def emergency_stop_paper(gateway):
    _stop.set()
    with _lock:
        for symbol, pos in list(_state['open_positions'].items()):
            try:
                last = float(gateway('binance').exchange.fetch_ticker(symbol).get('last') or pos['entry_price'])
            except Exception: last = pos['entry_price']
            _close_position(symbol, pos, last, 'EMERGENCY_STOP')
        _state['orders'].clear(); _state['running'] = False; _state['stopped_at'] = _now(); _state['stop_type'] = 'EMERGENCY_STOP'
    return snapshot()
