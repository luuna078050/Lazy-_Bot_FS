from __future__ import annotations

import asyncio
import math
import re
import time
from fastapi import HTTPException
from pydantic import BaseModel

from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_radar_timeframes_fix as tf_fix
from .market_radar import RADAR

# Candidate strategy: 150 -> 80 -> 40 -> 20 -> 3-5 confirmed entry candidates.
# This is intentionally a candidate layer, not yet the final production strategy.
tf_fix.STAGE3 = 20
tf_fix.FINAL = 20

DEFAULT_PROFIT = 0.33
SOFT_TIMEOUT = 90.0
HARD_TIMEOUT = 300.0
MAX_ENTRY_CANDIDATES = 5


def _ema(values, period):
    if not values:
        return 0.0
    k = 2.0 / (period + 1.0)
    e = float(values[0])
    for v in values[1:]:
        e = float(v) * k + e * (1.0 - k)
    return e


def _rsi(values, period=14):
    if len(values) < period + 1:
        return 50.0
    gains = []
    losses = []
    for a, b in zip(values[-period-1:-1], values[-period:]):
        d = float(b) - float(a)
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al <= 1e-12:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - (100.0 / (1.0 + ag / al))


def _indicator_gate(symbol):
    s = str(symbol).upper().replace('/', '')
    with RADAR.lock:
        bars = list(RADAR.bars.get(s, {}).get('3m', ()))
    closes = [float(x.get('close') or 0) for x in bars if float(x.get('close') or 0) > 0]
    if len(closes) < 22:
        return {'ema9': 0.0, 'ema21': 0.0, 'rsi14': 50.0, 'ready': False}
    return {
        'ema9': _ema(closes[-60:], 9),
        'ema21': _ema(closes[-60:], 21),
        'rsi14': _rsi(closes, 14),
        'ready': True,
    }


def _candidate_score(row, ind):
    # Entry quality is a confluence score; radar score remains the market-ranking score.
    checks = 0
    if ind['ready'] and ind['ema9'] > ind['ema21']:
        checks += 1
    if 55.0 <= ind['rsi14'] <= 72.0:
        checks += 1
    if float(row.get('change_30s_pct', 0)) > 0:
        checks += 1
    if float(row.get('change_1m_pct', 0)) > 0:
        checks += 1
    if float(row.get('change_3m_pct', 0)) > 0:
        checks += 1
    if float(row.get('change_5m_pct', 0)) > -0.20:
        checks += 1
    if float(row.get('change_15m_pct', 0)) > -0.50:
        checks += 1
    if float(row.get('change_30m_pct', 0)) > -1.00:
        checks += 1
    if float(row.get('volume_ratio', 0)) >= 0.80:
        checks += 1
    pulse = max(0.0, float(row.get('pump_score', 0) or 0))
    return checks, float(row.get('score', 0) or 0) + checks * 4.0 + pulse * 5.0


async def radar_candidate(force=False):
    if not force and legacy.S.get('last_radar') and time.time() - legacy.S['last_radar'] < 5:
        return
    try:
        rows = RADAR.snapshot(20)
        ranked = []
        for x in rows:
            s = str(x.get('symbol', '')).replace('/', '').upper()
            if not s:
                continue
            ind = _indicator_gate(s)
            checks, entry_score = _candidate_score(x, ind)
            # A full entry needs at least 7/9 confirmations, including usable 3m data.
            entry_ok = bool(ind['ready'] and checks >= 7)
            signal = 'BUY' if entry_ok else 'WATCH'
            row = dict(x)
            row.update({
                'signal': signal,
                'entry_score': round(entry_score, 2),
                'entry_confirmations': checks,
                'ema9_3m': round(ind['ema9'], 10),
                'ema21_3m': round(ind['ema21'], 10),
                'rsi14_3m': round(ind['rsi14'], 2),
                'entry_allowed': entry_ok,
                'candidate_pool': 'TOP-20',
            })
            ranked.append(row)
        ranked.sort(key=lambda x: (float(x.get('entry_score', 0)), float(x.get('score', 0))), reverse=True)
        legacy.S['ranking'] = ranked[:20]
        legacy.S['last_radar'] = time.time()
        legacy.S['error'] = None if not getattr(RADAR, 'last_error', None) else 'Radar WebSocket: ' + RADAR.last_error
    except Exception as e:
        legacy.S['error'] = f'Radar: {type(e).__name__}: {e}'
        legacy.S['last_radar'] = time.time()

legacy.radar = radar_candidate
legacy.MAX_AGE = SOFT_TIMEOUT


class CandidateSlotsBody(BaseModel):
    slots: list[str] = []
    profit_pct: float = DEFAULT_PROFIT
    reinvest: bool = False


def _clean_slots(values):
    out = []
    for x in values or []:
        s = str(x).upper().replace('/', '').strip()
        if s and s not in out:
            out.append(s)
    bad = [s for s in out if not re.fullmatch(r'[A-Z0-9]+USDT', s)]
    if bad:
        raise HTTPException(400, 'Invalid Binance pairs: ' + ','.join(bad))
    return out[:20]


def _pinned_slots():
    return {int(p.get('slot')) for p in legacy.S.get('positions', [])
            if str(p.get('slot', '')).lstrip('-').isdigit()}

async def apply_top20(b: CandidateSlotsBody):
    await legacy.radar(True)
    ranked = []
    seen = set()
    for x in legacy.S.get('ranking', []):
        s = str(x.get('symbol', '')).upper().replace('/', '')
        if s and s not in seen and re.fullmatch(r'[A-Z0-9]+USDT', s):
            ranked.append(s)
            seen.add(s)
    target = ranked[:20]
    old = (list(legacy.S.get('slots', [])) + [None] * 20)[:20]
    final_slots = list(old)
    pinned = _pinned_slots()
    used = {str(x).upper().replace('/', '') for x in final_slots if x}
    for i in range(20):
        if i in pinned:
            print(f'[ROTATION] PIN slot={i} pair={final_slots[i]} reason=OPEN_POSITION', flush=True)
            continue
        candidate = next((s for s in target if s not in used), None)
        if candidate:
            previous = final_slots[i]
            if previous:
                used.discard(str(previous).upper().replace('/', ''))
            final_slots[i] = candidate
            used.add(candidate)
            print(f'[ROTATION] ASSIGN slot={i} {previous or "EMPTY"} -> {candidate}', flush=True)
        else:
            final_slots[i] = None
    legacy.S['slots'] = final_slots
    legacy.S['profit'] = float(b.profit_pct)
    legacy.S['reinvest'] = bool(b.reinvest)
    legacy.S['error'] = None
    return await legacy.state()


def _remove_post(path):
    for r in list(legacy.app.router.routes):
        if getattr(r, 'path', None) == path and 'POST' in (getattr(r, 'methods', set()) or set()):
            legacy.app.router.routes.remove(r)

_remove_post('/api/slots')
@legacy.app.post('/api/slots')
async def slots_candidate(b: CandidateSlotsBody):
    a = _clean_slots(b.slots)
    old = (list(legacy.S.get('slots', [])) + [None] * 20)[:20]
    new = (a + [None] * 20)[:20]
    pinned = []
    for i in _pinned_slots():
        old_s = str(old[i] or '').upper().replace('/', '')
        if old_s and str(new[i] or '').upper().replace('/', '') != old_s:
            new[i] = old[i]
            pinned.append(old_s)
    legacy.S['slots'] = new
    legacy.S['profit'] = float(b.profit_pct)
    legacy.S['reinvest'] = bool(b.reinvest)
    if pinned:
        legacy.S['error'] = 'Open positions pinned: ' + ', '.join(pinned)
    return await legacy.state()

for _path in ('/api/slots/auto-top6', '/api/slots/auto-top10', '/api/slots/auto-top20'):
    _remove_post(_path)

@legacy.app.post('/api/slots/auto-top20')
async def auto_top20_candidate(b: CandidateSlotsBody):
    return await apply_top20(b)

@legacy.app.post('/api/slots/auto-top10')
async def auto_top10_alias(b: CandidateSlotsBody):
    return await apply_top20(b)

@legacy.app.post('/api/slots/auto-top6')
async def auto_top6_alias(b: CandidateSlotsBody):
    return await apply_top20(b)


async def manage_candidate():
    now = time.time()
    for p in list(legacy.S.get('positions', [])):
        try:
            snapshot = legacy.price(p['symbol']) or p.get('current') or p.get('entry')
            p['current'] = snapshot
            entry = float(p.get('entry') or 0)
            stake = float(p.get('stake') or 0)
            live = ((float(snapshot) / entry) - 1) * 100 if entry else 0.0
            p['delta_usdt'] = live / 100.0 * stake
            p['age_seconds'] = max(0, int(now - float(p.get('opened') or now)))
            p['age'] = p['age_seconds']
            if float(legacy.S.get('profit', DEFAULT_PROFIT) or 0) > 0 and live >= float(legacy.S['profit']):
                await legacy.close(p, 'PROFIT_TARGET')
                continue
            if p['age_seconds'] >= SOFT_TIMEOUT and not p.get('timeout_armed'):
                if live >= 0:
                    await legacy.close(p, 'TIMEOUT')
                    continue
                p['timeout_armed'] = True
                print(f'[TRADE] HOLD {p["symbol"]} reason=TIMEOUT_DEFERRED age={p["age_seconds"]}s live={live:.4f}%', flush=True)
            if p in legacy.S.get('positions', []) and p['age_seconds'] >= HARD_TIMEOUT:
                await legacy.close(p, 'MAX_HOLD')
        except Exception as e:
            legacy.S['error'] = f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'
            print(f'[ENGINE] MANAGE_ERROR {p.get("symbol")} {type(e).__name__}: {e}', flush=True)
    if legacy.S.get('stop_requested') and not legacy.S.get('positions'):
        legacy.S['stop_requested'] = None

legacy.manage = manage_candidate

_original_open_candidate = legacy.open_pos

async def open_candidate(i, symbol):
    if not symbol:
        return
    s = str(symbol).upper().replace('/', '')
    if any(str(p.get('symbol', '')).upper().replace('/', '') == s for p in legacy.S.get('positions', [])):
        return
    row = next((x for x in legacy.S.get('ranking', []) if str(x.get('symbol', '')).upper().replace('/', '') == s), None)
    if not row or not bool(row.get('entry_allowed')):
        return
    # Only the top 5 currently-confirmed signals may enter.
    confirmed = [x for x in legacy.S.get('ranking', []) if x.get('entry_allowed')]
    confirmed.sort(key=lambda x: float(x.get('entry_score', 0) or 0), reverse=True)
    leaders = {str(x.get('symbol', '')).upper().replace('/', '') for x in confirmed[:MAX_ENTRY_CANDIDATES]}
    if s not in leaders:
        return
    await _original_open_candidate(i, s)

legacy.open_pos = open_candidate


async def engine_candidate():
    while True:
        try:
            if legacy.S.get('running') or legacy.S.get('stop_requested'):
                await manage_candidate()
            if legacy.S.get('running'):
                await radar_candidate(False)
                occupied = {str(p.get('symbol', '')).upper().replace('/', '') for p in legacy.S.get('positions', [])}
                for i, s in enumerate(list(legacy.S.get('slots', []))):
                    if not s or any(p.get('slot') == i for p in legacy.S.get('positions', [])):
                        continue
                    n = str(s).upper().replace('/', '')
                    if n in occupied:
                        continue
                    await open_candidate(i, n)
                    occupied = {str(p.get('symbol', '')).upper().replace('/', '') for p in legacy.S.get('positions', [])}
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            legacy.S['error'] = f'Engine: {type(e).__name__}: {e}'
            print(f'[ENGINE] {type(e).__name__}: {e}', flush=True)
            await asyncio.sleep(1)

legacy.engine = engine_candidate

# Default target requested by the user. Values below 0.33 remain selectable.
legacy.S['profit'] = DEFAULT_PROFIT

# Candidate UI: 20 rotation slots and 0.33 default target.
html = legacy.HTML
html = html.replace('Slots · TOP-10', 'Slots · TOP-20').replace('AUTO TOP-10', 'AUTO TOP-20')
html = html.replace('Maximum 10 pairs', 'Maximum 20 pairs')
html = html.replace('Array.from({length:10}', 'Array.from({length:20}')
html = html.replace('for(let i=0;i<10;i++)', 'for(let i=0;i<20;i++)')
html = html.replace('/api/slots/auto-top10', '/api/slots/auto-top20')
html = html.replace('Maximum 10 pairs', 'Maximum 20 pairs')
html = html.replace('value="0.41"', 'value="0.33"')
if 'value="0.33"' not in html:
    html = html.replace('id="profit" class="input" type="number" step="0.01" value="0.30"', 'id="profit" class="input" type="number" step="0.01" value="0.33"')
legacy.HTML = html

print('CANDIDATE_LOGIC_ENABLED 150>80>40>20>3-5 TP=0.33 SOFT=90 HARD=300', flush=True)
