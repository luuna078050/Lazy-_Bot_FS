from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR
from fastapi import HTTPException
import asyncio
import time
from datetime import datetime, timezone

PRICE_FRESH_SECONDS = 3.0
TICKER_FRESH_SECONDS = 5.0

def fresh_price(symbol):
    s = str(symbol or '').upper().replace('/', '')
    now = time.time()
    try:
        with RADAR.lock:
            pulses = list(RADAR.pulses.get(s, ()))
            tick = RADAR.tickers.get(s)
            last_update = float(RADAR.last_update or 0)
        if pulses:
            row = pulses[-1]
            age = now - float(row.get('sec', 0) or 0)
            price = float(row.get('price', 0) or 0)
            if price > 0 and age <= PRICE_FRESH_SECONDS:
                return price
        if tick:
            price = float(tick.get('c', 0) or 0)
            if price > 0 and last_update and now - last_update <= TICKER_FRESH_SECONDS:
                return price
    except Exception:
        pass
    return 0.0

_original_price = legacy.price

def price_fixed(symbol):
    p = fresh_price(symbol)
    if p > 0:
        return p
    return _original_price(symbol)

legacy.price = price_fixed

_old_close = legacy.close

async def close_snapshot_safe(p, reason):
    symbol = str(p.get('symbol', '')).upper().replace('/', '')
    if legacy.S.get('mode') != 'PAPER':
        result = await _old_close(p, reason)
        stamp = datetime.now(timezone.utc).isoformat()
        for item in reversed(legacy.S.get('closed', [])):
            if str(item.get('id')) == str(p.get('id')) or str(item.get('symbol','')).upper().replace('/','') == symbol:
                item['closed_at'] = stamp
                item['close_time'] = stamp
                break
        return result
    try:
        ep = float(p.get('entry') or 0)
        stake = float(p.get('stake') or 0)
        xp = float(p.get('current') or 0)
        if xp <= 0:
            xp = fresh_price(symbol) or ep
        if ep <= 0 or stake <= 0 or xp <= 0:
            raise RuntimeError(f'Invalid close snapshot entry={ep} current={xp} stake={stake}')
        pnl = (xp / ep - 1.0) * stake
        actual_reason = reason
        if reason == 'PROFIT_TARGET' and pnl < -1e-9:
            actual_reason = 'PRICE_RETRACE'
            print(f'[PT_REJECT] {symbol} snapshot_pnl={pnl:.6f}', flush=True)
        legacy.S['free'] = float(legacy.S.get('free', 0.0) or 0.0) + stake
        if legacy.S.get('reinvest'):
            legacy.S['bot'] = float(legacy.S.get('bot', 0.0) or 0.0) + pnl
        else:
            legacy.S['account'] = float(legacy.S.get('account', 0.0) or 0.0) + pnl
            legacy.S['free'] = max(0.0, float(legacy.S.get('bot', 0.0) or 0.0) - legacy.invested())
        legacy.refresh_reserve()
        stamp = datetime.now(timezone.utc).isoformat()
        legacy.S['orders'].insert(0, {'time': stamp, 'symbol': symbol, 'side': 'SELL', 'price': xp, 'pnl': pnl, 'reason': actual_reason, 'snapshot': True})
        closed = dict(p, exit=xp, pnl=pnl, reason=actual_reason, closed_at=stamp, close_time=stamp)
        legacy.S['realized'] = float(legacy.S.get('realized', 0.0) or 0.0) + pnl
        legacy.S['session_realized'] = float(legacy.S.get('session_realized', 0.0) or 0.0) + pnl
        legacy.S['session_trades'] = int(legacy.S.get('session_trades', 0) or 0) + 1
        legacy.S['closed'].insert(0, closed)
        legacy.S['closed'] = legacy.S['closed'][:100]
        if p in legacy.S.get('positions', []):
            legacy.S['positions'].remove(p)
        print(f'[TRADE] CLOSE_OK {symbol} reason={actual_reason} snapshot_price={xp:.12g} pnl={pnl:.6f}', flush=True)
        return True
    except Exception as e:
        legacy.S['error'] = f'Close {symbol}: {type(e).__name__}: {e}'
        print(f'[TRADE] CLOSE_ERROR {symbol} reason={reason} {type(e).__name__}: {e}', flush=True)
        return False

legacy.close = close_snapshot_safe

for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/api/paper/emergency' and 'POST' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

async def _emergency_one(p):
    symbol = str(p.get('symbol', '')).upper().replace('/', '')
    try:
        cp = fresh_price(symbol)
        if cp > 0:
            p['current'] = cp
        ok = await asyncio.wait_for(close_snapshot_safe(p, 'EMERGENCY_STOP'), timeout=12.0)
        print(f'[EMERGENCY] {symbol} result={"CLOSED" if ok else "FAILED"} current={p.get("current")}', flush=True)
        return ok
    except Exception as e:
        legacy.S['error'] = f'Emergency {symbol}: {type(e).__name__}: {e}'
        print(f'[EMERGENCY] {symbol} result=FAILED {type(e).__name__}: {e}', flush=True)
        return False

@legacy.app.post('/api/paper/emergency')
async def emergency_fixed():
    legacy.S['running'] = False
    positions = list(legacy.S.get('positions', []))
    if not positions:
        legacy.S['stop_requested'] = None
        return await legacy.state()
    sem = asyncio.Semaphore(3)
    async def run_one(p):
        async with sem:
            return await _emergency_one(p)
    results = await asyncio.gather(*(run_one(p) for p in positions), return_exceptions=False)
    failed = [positions[i].get('symbol') for i, ok in enumerate(results) if not ok and positions[i] in legacy.S.get('positions', [])]
    if not legacy.S.get('positions'):
        legacy.S['stop_requested'] = None
        legacy.S['session_started'] = None
        legacy.S['error'] = None
    elif failed:
        legacy.S['stop_requested'] = None
        legacy.S['error'] = 'Emergency close failed: ' + ', '.join(map(str, failed))
    return await legacy.state()

html = legacy.HTML
css = '''<style data-open-positions-compact>
#pos .pos-line{font-size:11px!important;line-height:1.1!important;min-height:29px!important;padding:4px 0!important}
#pos .pos-main{font-size:11px!important}
#pos .pos-delta{font-size:11px!important}
#pos .pos-age{font-size:10px!important}
#pos .pos-emergency{font-size:10px!important;padding:5px 7px!important}
</style>'''
if 'data-open-positions-compact' not in html and '</head>' in html:
    html = html.replace('</head>', css + '</head>', 1)
legacy.HTML = html
print('LIVE_PRICE_FIX enabled source=aggTrade->miniTicker emergency=bounded-all-close OPEN_POSITIONS_FONT=11px', flush=True)
