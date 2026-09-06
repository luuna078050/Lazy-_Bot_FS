from __future__ import annotations
import time
import asyncio
from .fast_scalper_v042 import app
from . import fast_scalper_v042_base as base
from fastapi.dependencies.utils import get_dependant
from fastapi import HTTPException

# v0.4.3: ONLY repair Radar and pair/position handling.
# The existing v0.4.2 UI is reused unchanged.

base.TRADING_TF = '1m'
base.DEFAULT_HOLD_SECONDS = 60
base.S['hold_seconds'] = 60
base.Start.model_fields['hold_seconds'].default = 60
base.Slots.model_fields['hold_seconds'].default = 60

MAX_LOSS_PCT = 0.30
REENTRY_COOLDOWN = 5
MAX_LOSS_COOLDOWN = 60
slot_cooldown = {}


def close_position(p, reason):
    ep = p['entry']
    xp = p.get('current') or base.qprice(p['symbol']) or ep
    pnl = (xp / ep - 1) * p['stake']
    base.S['free'] += p['stake']
    if base.S['reinvest']:
        base.S['free'] += pnl
        base.S['bot'] += pnl
    else:
        base.S['account'] += pnl
    base.S['realized'] += pnl
    base.S['session_realized'] += pnl
    base.S['session_trades'] += 1
    base.S['closed'].insert(0, dict(p, exit=xp, pnl=pnl, reason=reason, closed_at=base.now()))
    base.S['closed'] = base.S['closed'][:100]
    base.S['orders'].insert(0, {'time': base.now(), 'symbol': p['symbol'], 'side': 'SELL', 'status': 'FILLED', 'price': xp, 'slot': p['slot'], 'pnl': pnl, 'reason': reason})
    base.S['positions'].remove(p)
    slot_cooldown[p['slot']] = time.time() + (MAX_LOSS_COOLDOWN if reason == 'MAX_LOSS' else REENTRY_COOLDOWN)

base.close_position = close_position


def fill_auto_slots_disabled():
    return None
base.fill_auto_slots = fill_auto_slots_disabled

_original_open_position = base.open_position

def open_position_guarded(slot, sym):
    if not sym or time.time() < slot_cooldown.get(slot, 0):
        return
    _original_open_position(slot, sym)

base.open_position = open_position_guarded


async def radar(force=False):
    """Reliable Radar: one market-data request, no dependency on dozens of klines."""
    if not force and base.S['last_radar'] and time.time() - base.S['last_radar'] < base.RADAR_INTERVAL:
        return
    try:
        try:
            tickers = await base.get_json('/api/v3/ticker/24hr')
            by = {x.get('symbol'): x for x in tickers if isinstance(x, dict) and x.get('symbol')}
        except Exception:
            prices = await base.get_json('/api/v3/ticker/price')
            by = {x.get('symbol'): {'symbol': x.get('symbol'), 'lastPrice': x.get('price'), 'quoteVolume': 0, 'priceChangePercent': 0} for x in prices if isinstance(x, dict) and x.get('symbol')}
        if not by:
            raise RuntimeError('No Binance market data')

        base.S['prices'] = {k: float(v.get('lastPrice') or 0) for k, v in by.items() if v.get('lastPrice')}
        manual = [cfg.get('symbol') for cfg in base.S['slots'] if cfg and cfg.get('symbol')]
        manual_set = set(manual)
        universe = list(dict.fromkeys(list(base.UNIVERSE) + manual))
        rows = []
        for sym in universe:
            t = by.get(sym)
            if not t:
                continue
            price = float(t.get('lastPrice') or 0)
            if price <= 0:
                continue
            change = float(t.get('priceChangePercent') or 0)
            volume = float(t.get('quoteVolume') or 0)
            score = max(0.0, min(100.0, 50.0 + change * 5.0))
            signal = 'BUY' if change > 0.10 else ('SELL' if change < -0.10 else 'WAIT')
            rows.append({'symbol': sym, 'price': price, 'change': change, 'volume': volume, 'score': round(score, 2), 'signal': signal, 'tf': base.TRADING_TF})

        # Volume ranks the market; manually entered pairs are always retained and shown first.
        rows.sort(key=lambda x: (x['symbol'] in manual_set, x['volume'], x['score']), reverse=True)
        base.S['ranking'] = rows[:20]
        base.S['last_radar'] = time.time()
        base.S['error'] = None if rows else 'Radar: no market rows'
    except Exception as e:
        base.S['error'] = f'Radar: {type(e).__name__}: {e}'
        base.S['last_radar'] = time.time() - base.RADAR_INTERVAL + 5

base.radar = radar


async def manage_positions():
    if not base.S['positions']:
        return
    try:
        ticks = await base.get_json('/api/v3/ticker/price')
        latest = {x.get('symbol'): float(x.get('price')) for x in ticks if isinstance(x, dict) and x.get('symbol')}
        base.S['prices'].update(latest)
    except Exception:
        latest = {}
    for p in list(base.S['positions']):
        p['current'] = latest.get(p['symbol']) or base.qprice(p['symbol']) or p.get('current') or p['entry']
        age = time.time() - p['opened']
        live = (p['current'] / p['entry'] - 1) * 100
        if base.S['profit'] > 0 and live >= base.S['profit']:
            close_position(p, 'PROFIT_TARGET')
        elif live <= -MAX_LOSS_PCT:
            close_position(p, 'MAX_LOSS')
        elif age >= base.S['hold_seconds']:
            close_position(p, 'TIMEOUT')

base.manage_positions = manage_positions


@base.app.post('/api/hold')
async def set_hold(body: dict):
    try:
        hold = int(body.get('hold_seconds'))
    except Exception:
        raise HTTPException(400, 'hold_seconds must be 60 or 180')
    if hold not in (60, 180):
        raise HTTPException(400, 'hold_seconds must be 60 or 180')
    base.S['hold_seconds'] = hold
    return await base.state()


@base.app.post('/api/slots_manual')
async def slots_manual(b: base.Slots):
    clean = [x.upper().replace('/', '').replace('-', '') for x in b.slots if x.strip()]
    if len(clean) > base.MAX_SLOTS:
        raise HTTPException(400, f'Maximum {base.MAX_SLOTS} pairs')
    if base.S['positions']:
        raise HTTPException(400, 'Close current positions before changing slots')
    base.S['slots'] = [
        {'symbol': clean[i], 'tf': base.TRADING_TF, 'auto': False} if i < len(clean) else None
        for i in range(base.MAX_SLOTS)
    ]
    base.S['profit'] = b.profit_pct
    base.S['reinvest'] = b.reinvest
    base.S['hold_seconds'] = b.hold_seconds
    await radar(True)
    return await base.state()


@base.app.post('/api/slots/auto')
async def slots_auto():
    if base.S['positions']:
        raise HTTPException(400, 'Close current positions before changing slots')
    await radar(True)
    picks = [x['symbol'] for x in base.S['ranking'][:base.MAX_SLOTS]]
    base.S['slots'] = [
        {'symbol': picks[i], 'tf': base.TRADING_TF, 'auto': True} if i < len(picks) else None
        for i in range(base.MAX_SLOTS)
    ]
    return await base.state()


for _route in base.app.routes:
    if getattr(_route, 'path', None) == '/api/slots' and 'POST' in getattr(_route, 'methods', set()):
        _route.endpoint = slots_manual
        _route.dependant = get_dependant(path=_route.path, call=slots_manual)
        break

base.HTML = base.HTML
app = base.app
