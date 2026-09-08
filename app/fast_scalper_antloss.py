from . import fast_scalper_beta_001_legacy as legacy
import asyncio
import time

# PAPER close must use the exact price that triggered the decision.
async def _close_at_snapshot(p, reason, snapshot):
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

# Radar is isolated from the trade loop. A slow/reconnecting Radar refresh
# must never block position management or slot filling.
async def _radar_loop():
    while True:
        try:
            if legacy.S.get('running'):
                await asyncio.wait_for(legacy.radar(False), timeout=10)
            else:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            legacy.S['error'] = f'Radar: {type(e).__name__}: {e}'
        await asyncio.sleep(1)

async def engine_fixed():
    asyncio.create_task(_radar_loop())
    while True:
        try:
            if legacy.S.get('running'):
                await manage()
                for i, s in enumerate(list(legacy.S.get('slots', []))):
                    if s and not any(p['slot'] == i for p in legacy.S.get('positions', [])):
                        await legacy.open_pos(i, s)
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            legacy.S['error'] = f'Engine: {type(e).__name__}: {e}'
            await asyncio.sleep(1)

legacy.manage = manage
legacy.engine = engine_fixed
