from . import fast_scalper_beta_001_legacy as legacy
import asyncio
import os
import time
import httpx

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

# Render Free can stop an idle web service after a period without inbound traffic.
# While the bot is actually running, keep the canonical service warm. This does
# not change trading logic and stops the test session from disappearing merely
# because the browser tab is backgrounded/closed.
async def _render_keepalive():
    base = os.getenv('RENDER_EXTERNAL_URL', 'https://fast-scalper-beta-001.onrender.com').rstrip('/')
    while True:
        try:
            if legacy.S.get('running'):
                async with httpx.AsyncClient(timeout=8) as client:
                    await client.get(base + '/api/health', params={'ka': int(time.time())})
        except Exception:
            pass
        await asyncio.sleep(300)

@legacy.app.on_event('startup')
async def _start_render_keepalive():
    asyncio.create_task(_render_keepalive())

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
