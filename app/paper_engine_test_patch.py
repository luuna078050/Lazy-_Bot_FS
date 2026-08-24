from __future__ import annotations

import time
from . import paper_engine_v2 as engine
from .market_radar import RADAR


def install():
    from .timeframe_patch import install as install_tf
    install_tf()
    if getattr(engine, "_fs_test_patch", False):
        return

    def market(symbol: str):
        key = symbol.replace('/', '').upper()
        with RADAR.lock:
            ticker = dict(RADAR.tickers.get(key) or {})
            pulse = RADAR._pulse(key)
        price = float(ticker.get('c') or 0)
        if price <= 0:
            return None
        tf = str(engine._state.get('config', {}).get('timeframe', '3m') or '3m').lower()
        if tf not in {'1m', '3m', '5m'}:
            tf = '3m'
        metrics = RADAR.timeframe_metrics(key, tf)
        return {
            'price': price,
            'change_24h_pct': float(ticker.get('P') or 0),
            'change_3m_pct': float(metrics.get('change_pct', 0)),
            'volume_ratio': float(metrics.get('volume_ratio', 1)),
            'timeframe': tf,
            **pulse,
        }

    def tick(symbol, allocation, target, minp, sl, maxhold):
        m = market(symbol)
        if not m:
            return
        last = float(m['price'])
        with engine._lock:
            pos = engine._state['open_positions'].get(symbol)
            if pos:
                qty = float(pos['amount']); cap = float(pos['allocated_usdt']); fee_pct = float(pos['fee_pct'])
                gross = (last - float(pos['entry_price'])) * qty
                fee = (cap + last * qty) * fee_pct / 100
                net = gross - fee
                age = time.time() - float(pos['opened_ts'])
                reason = None
                hold = float(pos.get('hold_seconds', maxhold))
                if net >= target:
                    reason = 'TARGET'
                elif sl > 0 and (last / float(pos['entry_price']) - 1) * 100 <= -sl:
                    reason = 'SL'
                elif age >= hold:
                    reason = 'PUMP_20S_EXIT' if pos.get('signal') == 'PUMP' else ('TIMEOUT' if net >= minp else 'CRITICAL_EXIT')
                if reason:
                    engine._close(symbol, pos, last, reason)
                else:
                    base = symbol.split('/')[0]
                    engine._state['assets'][base] = {
                        'amount': qty, 'current_price': last, 'value_usdt': qty * last,
                        'entry_value_usdt': cap, 'unrealized_pnl': net,
                    }
                return

            if engine._halt_entries or engine._state['free_usdt'] <= 0 or allocation <= 0:
                return
            sig = engine._signal(m)
            # The threshold is deliberately modest for PAPER so a night test
            # produces observable entries without fabricating trades. The signal
            # still comes exclusively from the live Binance WebSocket stream.
            threshold = {'1m': 0.08, '3m': 0.10, '5m': 0.12}.get(m.get('timeframe'), 0.10)
            if not (float(m.get('change_3m_pct', 0)) >= threshold or sig['signal'] == 'PUMP'):
                return
            if allocation > engine._state['free_usdt'] + 1e-9:
                return
            amount = allocation / last
            fills = [{'time': engine._now(), 'amount': amount, 'price': last, 'cost': allocation}]
            engine._state['free_usdt'] -= allocation
            order = {
                'symbol': symbol, 'side': 'BUY', 'requested_usdt': allocation,
                'requested_amount': amount, 'filled_amount': amount, 'remaining_amount': 0.0,
                'status': 'FILLED', 'fills': fills, 'signal': sig['signal'],
                'hold_seconds': sig['hold'], 'timeframe': m.get('timeframe'),
            }
            engine._state['orders'][symbol] = order
            engine._state['order_history'].append({**order, 'price': last, 'time': engine._now()})
            engine._state['open_positions'][symbol] = {
                'symbol': symbol, 'entry_price': last, 'amount': amount,
                'allocated_usdt': allocation, 'opened_at': fills[0]['time'], 'opened_ts': time.time(),
                'fee_pct': engine._state['config']['fee_pct'], 'signal': sig['signal'],
                'hold_seconds': sig['hold'], 'pump_score': sig['pump_score'], 'fills': fills,
                'stage': 'OPEN', 'timeframe': m.get('timeframe'),
            }
            base = symbol.split('/')[0]
            engine._state['assets'][base] = {
                'amount': amount, 'current_price': last, 'value_usdt': allocation,
                'entry_value_usdt': allocation, 'unrealized_pnl': 0.0,
            }

    engine._market = market
    engine._tick = tick
    engine._fs_test_patch = True
