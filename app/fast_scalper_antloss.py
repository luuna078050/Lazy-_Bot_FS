from . import fast_scalper_beta_001_legacy as legacy
import asyncio
import time

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
        try:
            snapshot = legacy.price(p['symbol']) or p['current']
            p['current'] = snapshot
            live = (snapshot / p['entry'] - 1) * 100
            age = time.time() - p['opened']

            if legacy.S['profit'] > 0 and live >= legacy.S['profit']:
                print(f"[TRADE] CLOSE {p['symbol']} reason=PROFIT_TARGET age={age:.1f}s live={live:.4f}% price={snapshot}", flush=True)
                await _close_at_snapshot(p, 'PROFIT_TARGET', snapshot)
                continue

            if age >= legacy.MAX_AGE:
                print(f"[TRADE] CLOSE {p['symbol']} reason=TIMEOUT age={age:.1f}s live={live:.4f}% price={snapshot}", flush=True)
                await _close_at_snapshot(p, 'TIMEOUT', snapshot)
                continue
        except Exception as e:
            legacy.S['error'] = f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'

_original_open_pos = legacy.open_pos
async def open_pos_logged(i, s):
    before_ids = {p.get('id') for p in legacy.S.get('positions', [])}
    await _original_open_pos(i, s)
    for p in legacy.S.get('positions', []):
        if p.get('id') not in before_ids and p.get('slot') == i and p.get('symbol') == s:
            p.setdefault('timeout_armed', False)
            print(f"[TRADE] OPEN {p.get('symbol')} slot={p.get('slot')} stake={p.get('stake')} entry={p.get('entry')} opened_at={p.get('opened_at')} mode={legacy.S.get('mode')}", flush=True)
            break
legacy.open_pos = open_pos_logged

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
