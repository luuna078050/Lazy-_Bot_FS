from __future__ import annotations
import time
import threading
from . import profit_first_engine_v3 as base
from .market_radar import RADAR

# New-start PAPER mode must be observable in a short test. Strategy diagnostics
# remain visible; entry gating is not allowed to silently prevent all fills.
ENTRY_SCORE = 0.0


def _analysis(symbol):
    try:
        return RADAR.analyze(symbol.replace('/', '').upper())
    except Exception:
        return None


def _horizon(tf):
    return {'1m': 60, '3m': 180, '5m': 300}.get(tf, 180)


def _pnl(cap, entry, last, fee_pct):
    qty = cap / entry if entry else 0.0
    gross = (last - entry) * qty
    fee = (cap + last * qty) * fee_pct / 100.0
    return gross - fee, gross, fee


def _close(key, pos, last, reason):
    cap = float(pos['allocated_usdt'])
    net, gross, fee = _pnl(cap, float(pos['entry_price']), last, float(pos.get('fee_pct', .10)))
    base.STATE['free_usdt'] += cap
    base.STATE['account_balance_usdt'] += net
    base.STATE['realized_pnl'] += net
    if net > 0:
        base.STATE['profit_reserve_usdt'] += net
    base.STATE['trades'].append({'symbol': pos['symbol'], 'side': 'SELL', 'entry_price': pos['entry_price'], 'exit_price': last, 'allocated_usdt': cap, 'gross_pnl': gross, 'fee': fee, 'net_pnl': net, 'reason': reason, 'opened_at': pos['opened_at'], 'closed_at': base.now(), 'timeframe': pos['timeframe']})
    base.STATE['pnl_window'].append({'ts': time.time(), 'pnl': net})
    base.STATE['order_history'].append({'symbol': pos['symbol'], 'side': 'SELL', 'status': 'FILLED', 'price': last, 'net_pnl': net, 'reason': reason, 'time': base.now()})
    base.STATE['open_positions'].pop(key, None)
    base.STATE['orders'].pop(key, None)
    base.COOLDOWN[pos['symbol']] = time.time() + 5.0


def _open(key, symbol, allocation, timeframe, a):
    price = float(a['price'])
    fee = float(base.STATE['config'].get('fee_pct', .10))
    horizon = _horizon(timeframe)
    target = max(0.03, allocation * 0.0025)
    base.STATE['free_usdt'] -= allocation
    base.STATE['open_positions'][key] = {'symbol': symbol, 'entry_price': price, 'amount': allocation / price, 'allocated_usdt': allocation, 'opened_at': base.now(), 'opened_ts': time.time(), 'fee_pct': fee, 'signal': 'PAPER_CONFIRMED', 'timeframe': timeframe, 'hold_seconds': horizon, 'max_hold_seconds': horizon, 'target_profit_usdt': target, 'quality': float(a.get('score', 0)), 'entry_threshold': ENTRY_SCORE, 'stage': 'OPEN', 'last_analysis': a}
    base.STATE['order_history'].append({'symbol': symbol, 'side': 'BUY', 'status': 'FILLED', 'price': price, 'cost': allocation, 'type': 'PAPER_MARKET', 'reason': 'PAPER_SIGNAL_CONFIRMED', 'time': base.now()})


def _manage(key, pos):
    a = _analysis(pos['symbol'])
    if not a:
        return
    last = float(a['price'])
    net, _, _ = _pnl(float(pos['allocated_usdt']), float(pos['entry_price']), last, float(pos.get('fee_pct', .10)))
    age = time.time() - float(pos['opened_ts'])
    wall = a.get('wall') or {}
    reason = None
    if net >= float(pos['target_profit_usdt']):
        reason = 'TARGET_PROFIT'
    elif wall.get('direction') == 'bearish' and net > 0:
        reason = 'WALL_REVERSAL_PROFIT'
    elif age >= float(pos['max_hold_seconds']):
        reason = 'TIME_EXIT' if net >= 0 else 'HYPOTHESIS_FAILED'
    elif (last / float(pos['entry_price']) - 1.0) * 100 <= -1.20:
        reason = 'CATASTROPHIC_STOP'
    if reason:
        _close(key, pos, last, reason)
        return
    pos['current_price'] = last
    pos['unrealized_pnl'] = net
    pos['age_sec'] = age
    pos['quality'] = float(a.get('score', 0))
    pos['last_analysis'] = a


def tick(symbol: str, allocation: float, timeframe: str):
    try:
        base.STATE.setdefault('diagnostics', {'ticks': 0, 'entries': 0, 'errors': 0, 'last_tick_ts': None, 'last_reason': '', 'last_error': None})
        base.STATE['diagnostics']['ticks'] += 1
        base.STATE['diagnostics']['last_tick_ts'] = time.time()
        a = _analysis(symbol)
        if not a:
            base.STATE['diagnostics']['last_reason'] = f'{symbol}: waiting for Binance market data'
            return
        key = f'{symbol}::{timeframe}'
        with base.LOCK:
            pos = base.STATE['open_positions'].get(key)
            if pos:
                _manage(key, pos)
                return
            if base.HALT_ENTRIES or base.STATE['free_usdt'] + 1e-9 < allocation:
                base.STATE['diagnostics']['last_reason'] = f'{symbol}: insufficient free capital or entries halted'
                return
            wall = a.get('wall') or {}
            score = float(a.get('score', 0) or 0)
            if score < ENTRY_SCORE or wall.get('direction') == 'bearish':
                base.STATE['diagnostics']['last_reason'] = f'{symbol}: no entry score={score:.1f} wall={wall.get("direction", "neutral")}'
                return
            _open(key, symbol, allocation, timeframe, a)
            base.STATE['diagnostics']['entries'] += 1
            base.STATE['diagnostics']['last_reason'] = f'{symbol}: PAPER BUY filled at {a["price"]}'
    except Exception as exc:
        base.STATE.setdefault('diagnostics', {})['errors'] = int(base.STATE.get('diagnostics', {}).get('errors', 0)) + 1
        base.STATE['diagnostics']['last_error'] = str(exc)[:300]


def start_paper(config, gateway_unused=None):
    cfg = dict(config)
    pairs = [str(x).strip().upper().replace('-', '/') for x in cfg.get('pairs', []) if str(x).strip()]
    alloc = [float(x) for x in cfg.get('allocations', [])]
    tfs = [str(x).lower() for x in cfg.get('timeframes', [])]
    capital = float(cfg.get('capital', 1000) or 1000)

    # Empty selection is a valid NEW START test: automatically take the top six
    # currently ranked Binance candidates, then the user can replace them later.
    if not pairs:
        try:
            candidates = RADAR.snapshot(10)
            pairs = [str(x.get('symbol','')).replace('-', '/').upper() for x in candidates if x.get('symbol')][:6]
        except Exception:
            pairs = []
        if not pairs:
            pairs = ['BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT','XRP/USDT','ADA/USDT']
        tfs = ['3m'] * len(pairs)
        alloc = [100.0 / len(pairs)] * len(pairs)
    if not 1 <= len(pairs) <= 10:
        raise ValueError('Выберите от 1 до 10 пар.')
    if not alloc:
        alloc = [100.0 / len(pairs)] * len(pairs)
    if len(alloc) != len(pairs) or any(x <= 0 for x in alloc) or not 0 < sum(alloc) <= 100.0001:
        raise ValueError('Доли должны быть больше 0% и в сумме не превышать 100%.')
    if capital <= 0:
        raise ValueError('Бюджет PAPER должен быть больше 0 USDT.')
    if not tfs:
        tfs = [str(cfg.get('timeframe', '3m')).lower()] * len(pairs)
    if len(tfs) != len(pairs) or any(x not in {'1m', '3m', '5m'} for x in tfs):
        raise ValueError('Допустимые таймфреймы: 1m, 3m, 5m.')
    base.tick = tick
    RADAR.start()
    base.STOP.clear(); base.HALT_ENTRIES = False; base.COOLDOWN.clear()
    with base.LOCK:
        base.STATE.update({'running': True, 'mode': 'paper', 'started_at': base.now(), 'stopped_at': None, 'initial_balance': capital, 'account_balance_usdt': capital, 'free_usdt': capital, 'realized_pnl': 0.0, 'profit_reserve_usdt': 0.0, 'assets': {}, 'open_positions': {}, 'orders': {}, 'order_history': [], 'trades': [], 'error': None, 'stop_type': None, 'pnl_window': [], 'diagnostics': {'ticks': 0, 'entries': 0, 'errors': 0, 'last_tick_ts': None, 'last_reason': 'starting Binance market feed', 'last_error': None}, 'config': {'pairs': pairs, 'allocations': alloc, 'allocated_pct': sum(alloc), 'unused_capital_pct': 100 - sum(alloc), 'initial_balance': capital, 'fee_pct': float(cfg.get('fee_pct', .10)), 'timeframes': tfs, 'risk_mode': 'PROFIT_FIRST', 'target_win_rate': 70.0}})
    def loop():
        while not base.STOP.is_set():
            try:
                with base.LOCK:
                    c = dict(base.STATE['config'])
                for i, sym in enumerate(c['pairs']):
                    tick(sym, float(c['initial_balance']) * float(c['allocations'][i]) / 100.0, c['timeframes'][i])
            except Exception as exc:
                with base.LOCK:
                    base.STATE['error'] = str(exc)[:300]
                    base.STATE['diagnostics']['last_error'] = str(exc)[:300]
            time.sleep(1)
        with base.LOCK:
            base.STATE['running'] = False; base.STATE['stopped_at'] = base.now()
    base.THREAD = threading.Thread(target=loop, daemon=True, name='fast-scalper-paper')
    base.THREAD.start()
    return snapshot()


def stop_paper(gateway_unused=None):
    base.HALT_ENTRIES = True; base.STOP.set()
    with base.LOCK:
        for key, pos in list(base.STATE['open_positions'].items()):
            a = _analysis(pos['symbol'])
            _close(key, pos, float(a['price']) if a else float(pos['entry_price']), 'MANUAL_STOP')
        base.STATE['orders'].clear(); base.STATE['running'] = False; base.STATE['stopped_at'] = base.now(); base.STATE['stop_type'] = 'STOP'
    return snapshot()


def emergency_stop_paper(gateway_unused=None):
    base.HALT_ENTRIES = True; base.STOP.set()
    with base.LOCK:
        for key, pos in list(base.STATE['open_positions'].items()):
            a = _analysis(pos['symbol'])
            _close(key, pos, float(a['price']) if a else float(pos['entry_price']), 'EMERGENCY_STOP')
        base.STATE['orders'].clear(); base.STATE['running'] = False; base.STATE['stopped_at'] = base.now(); base.STATE['stop_type'] = 'EMERGENCY_STOP'
    return snapshot()


def snapshot():
    s = base.snapshot()
    capital = float(s.get('initial_balance', 0) or 0)
    realized = float(s.get('realized_pnl', 0) or 0)
    s['account_balance_usdt'] = capital + realized
    s['balance_usdt'] = capital + realized
    s['free_usdt'] = float(s.get('free_usdt', 0) or 0)
    s['invested_usdt'] = max(0.0, s['account_balance_usdt'] - s['free_usdt'])
    s['bot_balance_usdt'] = capital + realized
    s['diagnostics'] = dict(base.STATE.get('diagnostics') or {})
    s['strategy'] = {'paper_execution': 'LIVE_BINANCE_PRICE_STREAM_SIMULATED_FILLS', 'entry_score': ENTRY_SCORE, 'timeframes': ['1m', '3m', '5m'], 'max_pairs': 10, 'duplicate_pair_different_tf': True}
    return s
