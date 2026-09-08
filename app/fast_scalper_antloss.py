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

# Preserve the proven scalping rule:
# 1) take the configured profit target immediately;
# 2) after MAX_AGE (60s), arm TIMEOUT;
# 3) once armed, close on the first non-negative market snapshot;
# 4) never turn a TIMEOUT into a loss because of a second price read.
async def manage():
    for p in list(legacy.S['positions']):
        snapshot = legacy.price(p['symbol']) or p['current']
        p['current'] = snapshot
        live = (snapshot / p['entry'] - 1) * 100
        age = time.time() - p['opened']

        if legacy.S['profit'] > 0 and live >= legacy.S['profit']:
            try:
                print(f"[TRADE] CLOSE {p['symbol']} reason=PROFIT_TARGET age={age:.1f}s live={live:.4f}% price={snapshot}", flush=True)
                await _close_at_snapshot(p, 'PROFIT_TARGET', snapshot)
            except Exception as e:
                legacy.S['error'] = f'Close {p["symbol"]}: {type(e).__name__}: {e}'
            continue

        if age >= legacy.MAX_AGE:
            if live >= 0:
                p['timeout_armed'] = True
                try:
                    print(f"[TRADE] CLOSE {p['symbol']} reason=TIMEOUT age={age:.1f}s live={live:.4f}% price={snapshot}", flush=True)
                    await _close_at_snapshot(p, 'TIMEOUT', snapshot)
                except Exception as e:
                    legacy.S['error'] = f'Close {p["symbol"]}: {type(e).__name__}: {e}'
            else:
                if not p.get('timeout_armed'):
                    p['timeout_armed'] = True
                    print(f"[TRADE] TIMEOUT_ARM {p['symbol']} age={age:.1f}s live={live:.4f}% price={snapshot}", flush=True)

# Keep exact open/slot behavior, but log fills so the real position age can be
# verified directly against Render logs during the next PAPER test.
_original_open_pos = legacy.open_pos
async def open_pos_logged(i, s):
    before = len(legacy.S.get('positions', []))
    await _original_open_pos(i, s)
    after = legacy.S.get('positions', [])
    if len(after) > before:
        p = after[-1]
        print(f"[TRADE] OPEN {p.get('symbol')} slot={p.get('slot')} stake={p.get('stake')} entry={p.get('entry')} mode={legacy.S.get('mode')}", flush=True)
legacy.open_pos = open_pos_logged

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
