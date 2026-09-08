from . import fast_scalper_beta_001_legacy as legacy
import time

async def manage():
    for p in list(legacy.S['positions']):
        p['current'] = legacy.price(p['symbol']) or p['current']
        live = (p['current'] / p['entry'] - 1) * 100
        if legacy.S['profit'] > 0 and live >= legacy.S['profit']:
            try:
                await legacy.close(p, 'PROFIT_TARGET')
            except Exception as e:
                legacy.S['error'] = f'Close {p["symbol"]}: {type(e).__name__}: {e}'
        elif live >= 0 and time.time() - p['opened'] >= legacy.MAX_AGE:
            try:
                await legacy.close(p, 'TIMEOUT')
            except Exception as e:
                legacy.S['error'] = f'Close {p["symbol"]}: {type(e).__name__}: {e}'
