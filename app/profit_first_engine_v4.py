from __future__ import annotations

from . import profit_first_engine_v3 as base
import time

# Reuse the validated state, radar, PnL accounting and 10-pair configuration
# from v3, but replace position exits so 1.73 USDT/min per $100 is a
# portfolio-throughput benchmark, never a mandatory profit target for one trade.

def tick(symbol: str, allocation: float, timeframe: str):
    m = base.market(symbol)
    if not m:
        return
    last = float(m['price'])
    with base.LOCK:
        cfg = dict(base.STATE['config'])
        pos = base.STATE['open_positions'].get(symbol)
        fee = float(cfg.get('fee_pct', 0.10))
        if pos:
            net, _, _ = base.pnl(float(pos['allocated_usdt']), float(pos['entry_price']), last, fee)
            age = time.time() - float(pos['opened_ts'])
            freeze = float(m.get('freeze_risk', 1.0))
            velocity = float(m.get('trade_velocity', 0.0))
            # A trade can finish in seconds. The selected timeframe is only
            # the analysis horizon; it is never a forced hold duration.
            target = max(0.15, float(pos.get('soft_target_usdt', 0.15)))
            reason = None
            if net >= target and (velocity < 35 or freeze >= 0.35 or age >= 10):
                reason = 'DYNAMIC_PROFIT'
            elif net >= 0.15 and freeze >= 0.45:
                reason = 'FREEZE_PROFIT_EXIT'
            elif net > 0 and age >= float(pos.get('max_hold_seconds', 180)):
                reason = 'TIME_OPPORTUNITY_EXIT'
            elif net < 0 and age >= float(pos.get('max_hold_seconds', 180)) and freeze >= 0.55:
                reason = 'HYPOTHESIS_FAILED'
            elif (last / float(pos['entry_price']) - 1) * 100 <= -1.20:
                reason = 'CATASTROPHIC_STOP'
            if reason:
                base.close_position(symbol, pos, last, reason)
            return
        if base.HALT_ENTRIES or base.STATE['free_usdt'] <= 0 or allocation <= 0 or allocation > base.STATE['free_usdt'] + 1e-9:
            return
        if time.time() < base.COOLDOWN.get(symbol, 0):
            return
        d = base.decision(m)
        if not d['entry_ok']:
            return
        amount = allocation / last
        horizon = {'1m': 60, '3m': 180, '5m': 300}.get(timeframe, 180)
        # Soft per-trade target is deliberately small. The 1.73 USDT/min
        # objective is measured across all closed trades in the rolling minute.
        soft_target = max(0.15, allocation * 0.0025)
        base.STATE['free_usdt'] -= allocation
        base.STATE['open_positions'][symbol] = {
            'symbol': symbol, 'entry_price': last, 'amount': amount,
            'allocated_usdt': allocation, 'opened_at': base.now(),
            'opened_ts': time.time(), 'fee_pct': fee,
            'signal': 'PUMP' if m.get('signal') == 'PUMP_NOW' else 'CONFIRMED',
            'hold_seconds': horizon, 'max_hold_seconds': horizon,
            'timeframe': timeframe, 'soft_target_usdt': soft_target,
            'target_profit_usdt': soft_target,
            'target_profit_per_min_usdt': base.TARGET_PNL_PER_MIN_PER_100 * allocation / 100,
            'quality': d['quality'], 'confirmations': d['confirmations'],
            'entry_threshold': d['threshold'], 'maker_preferred': True,
            'stage': 'OPEN'
        }
        base.STATE['order_history'].append({'symbol': symbol, 'side': 'BUY', 'status': 'FILLED', 'price': last, 'cost': allocation, 'time': base.now()})


def start_paper(config, gateway_unused=None):
    base.tick = tick
    return base.start_paper(config, gateway_unused)


def stop_paper(gateway_unused=None):
    return base.stop_paper(gateway_unused)


def emergency_stop_paper(gateway_unused=None):
    return base.emergency_stop_paper(gateway_unused)


def snapshot():
    return base.snapshot()
