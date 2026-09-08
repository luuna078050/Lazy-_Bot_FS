from . import fast_scalper_beta_001_legacy as legacy
import time

async def _close_at_snapshot(p, reason, snapshot):
    # PAPER close must use the same price that triggered the decision.
    # Otherwise a second price read can turn a valid non-negative exit into a loss.
    if legacy.S.get('mode') != 'PAPER':
        return await legacy.close(p, reason)
    original_price = legacy.price
    def fixed_price(symbol):
        if symbol == p['symbol']:
            return snapshot
        return original_price(symbol)
    legacy.price = fixed_price
    try:
        return await legacy.close(p, reason)
    finally:
        legacy.price = original_price

async def manage():
    for p in list(legacy.S['positions']):
        snapshot = legacy.price(p['symbol']) or p['current']
        p['current'] = snapshot
        live = (snapshot / p['entry'] - 1) * 100
        age = time.time() - p['opened']
        if legacy.S['profit'] > 0 and live >= legacy.S['profit']:
            try:
                await _close_at_snapshot(p, 'PROFIT_TARGET', snapshot)
            except Exception as e:
                legacy.S['error'] = f'Close {p["symbol"]}: {type(e).__name__}: {e}'
        elif live >= 0 and age >= legacy.MAX_AGE:
            try:
                await _close_at_snapshot(p, 'TIMEOUT', snapshot)
            except Exception as e:
                legacy.S['error'] = f'Close {p["symbol"]}: {type(e).__name__}: {e}'
