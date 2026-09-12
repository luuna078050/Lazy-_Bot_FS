from __future__ import annotations
import asyncio, re, time
from fastapi import HTTPException
from pydantic import BaseModel
from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR

ROTATION_POOL = 20
TRADE_SLOTS = 10
MAX_ENTRY_CANDIDATES = 5
DEFAULT_PROFIT = 0.33
SOFT_TIMEOUT = 90.0
HARD_TIMEOUT = 300.0

def _indicators(symbol):
    s = str(symbol).upper().replace('/', '')
    with RADAR.lock:
        by_tf = {tf: list(RADAR.bars.get(s, {}).get(tf, ())) for tf in ('3m', '1m')}
    tf = '3m' if len(by_tf['3m']) >= 22 else '1m'
    closes = [float(x.get('close') or 0) for x in by_tf[tf] if float(x.get('close') or 0) > 0]
    if len(closes) < 22:
        return {'ready': False, 'tf': tf, 'ema9': 0.0, 'ema21': 0.0, 'rsi': 50.0}
    vals = closes[-60:]
    def ema(period):
        k = 2.0 / (period + 1.0)
        e = vals[0]
        for v in vals[1:]: e = float(v) * k + e * (1.0 - k)
        return e
    gains, losses = [], []
    for a, b in zip(closes[-15:], closes[-14:]):
        d = b - a; gains.append(max(0.0, d)); losses.append(max(0.0, -d))
    ag = sum(gains) / 14.0; al = sum(losses) / 14.0
    rsi = 100.0 if al <= 1e-12 and ag > 0 else (50.0 if al <= 1e-12 else 100.0 - 100.0 / (1.0 + ag / al))
    return {'ready': True, 'tf': tf, 'ema9': ema(9), 'ema21': ema(21), 'rsi': rsi}

async def radar_core(force=False):
    if not force and legacy.S.get('last_radar') and time.time() - legacy.S['last_radar'] < 5: return
    try:
        rows = RADAR.snapshot(ROTATION_POOL); ranked = []
        for x in rows:
            s = str(x.get('symbol', '')).upper().replace('/', '')
            if not s: continue
            ind = _indicators(s); c = 0
            if ind['ready'] and ind['ema9'] >= ind['ema21']: c += 1
            if ind['ready'] and 45.0 <= ind['rsi'] <= 80.0: c += 1
            if float(x.get('change_30s_pct', 0) or 0) > 0: c += 1
            if float(x.get('change_1m_pct', 0) or 0) > 0: c += 1
            if float(x.get('change_3m_pct', 0) or 0) > 0: c += 1
            if float(x.get('change_5m_pct', 0) or 0) > -0.50: c += 1
            if float(x.get('change_15m_pct', 0) or 0) > -1.00: c += 1
            if float(x.get('volume_ratio', 0) or 0) >= 0.70: c += 1
            usable = bool(ind['ready'] and c >= 5)
            score = float(x.get('score', 0) or 0) + c * 4.0 + max(0.0, float(x.get('pump_score', 0) or 0)) * 4.0
            row = dict(x); row.update({'entry_allowed': usable, 'entry_score': round(score, 2), 'entry_confirmations': c, 'ema9_3m': round(ind['ema9'], 10), 'ema21_3m': round(ind['ema21'], 10), 'rsi14_3m': round(ind['rsi'], 2), 'indicator_tf': ind['tf'], 'candidate_pool': 'TOP-20', 'signal': 'BUY' if usable else 'WATCH'}); ranked.append(row)
        ranked.sort(key=lambda z: (float(z.get('entry_score', 0)), float(z.get('score', 0))), reverse=True)
        legacy.S['ranking'] = ranked[:ROTATION_POOL]; legacy.S['last_radar'] = time.time(); legacy.S['error'] = None if not getattr(RADAR, 'last_error', None) else 'Radar WebSocket: ' + RADAR.last_error; refresh_slots()
    except Exception as e:
        legacy.S['error'] = f'Radar: {type(e).__name__}: {e}'; legacy.S['last_radar'] = time.time()

def refresh_slots():
    ranked=[]; seen=set()
    for x in legacy.S.get('ranking', []):
        s=str(x.get('symbol','')).upper().replace('/','')
        if s and s not in seen and re.fullmatch(r'[A-Z0-9]+USDT',s): ranked.append(s); seen.add(s)
    target=ranked[:ROTATION_POOL]; old=(list(legacy.S.get('slots',[]))+[None]*ROTATION_POOL)[:ROTATION_POOL]
    occupied={int(p.get('slot')) for p in legacy.S.get('positions',[]) if str(p.get('slot','')).lstrip('-').isdigit()}; used={str(x).upper().replace('/','') for x in old if x}; final=list(old)
    for i in range(ROTATION_POOL):
        if i in occupied: continue
        candidate=next((s for s in target if s not in used),None)
        if candidate:
            previous=str(final[i] or '').upper().replace('/','')
            if previous: used.discard(previous)
            final[i]=candidate; used.add(candidate)
        else: final[i]=None
    legacy.S['slots']=final

legacy.radar = radar_core
legacy.MAX_AGE = SOFT_TIMEOUT

async def manage_core():
    now=time.time()
    for p in list(legacy.S.get('positions', [])):
        try:
            cur=legacy.price(p['symbol']) or p.get('current') or p.get('entry'); p['current']=cur
            entry=float(p.get('entry') or 0); stake=float(p.get('stake') or 0); live=((float(cur)/entry)-1.0)*100.0 if entry else 0.0
            p['delta_usdt']=live/100.0*stake; p['age_seconds']=max(0,int(now-float(p.get('opened') or now))); p['age']=p['age_seconds']
            target=float(legacy.S.get('profit',DEFAULT_PROFIT) or DEFAULT_PROFIT)
            if target>0 and live>=target: await legacy.close(p,'PROFIT_TARGET'); continue
            if p['age_seconds']>=SOFT_TIMEOUT and live>=0: await legacy.close(p,'TIMEOUT'); continue
            if p in legacy.S.get('positions',[]) and p['age_seconds']>=HARD_TIMEOUT: await legacy.close(p,'MAX_HOLD')
        except Exception as e: legacy.S['error']=f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'
legacy.manage=manage_core
_original_open=legacy.open_pos

async def open_core(i,symbol):
    if legacy.S.get('stop_requested') or not legacy.S.get('running'): return
    if i>=TRADE_SLOTS or not symbol or len(legacy.S.get('positions',[]))>=TRADE_SLOTS: return
    s=str(symbol).upper().replace('/','')
    if any(str(p.get('symbol','')).upper().replace('/','')==s for p in legacy.S.get('positions',[])): return
    row=next((x for x in legacy.S.get('ranking',[]) if str(x.get('symbol','')).upper().replace('/','')==s),None)
    if not row or not row.get('entry_allowed'): return
    confirmed=[x for x in legacy.S.get('ranking',[]) if x.get('entry_allowed')]; confirmed.sort(key=lambda x:float(x.get('entry_score',0) or 0),reverse=True)
    leaders={str(x.get('symbol','')).upper().replace('/','') for x in confirmed[:MAX_ENTRY_CANDIDATES]}
    if s not in leaders: return
    await _original_open(i,s)
legacy.open_pos=open_core

async def engine_core():
    while True:
        try:
            if legacy.S.get('positions'): await manage_core()
            if legacy.S.get('running') and not legacy.S.get('stop_requested'):
                await radar_core(False); occupied={int(p.get('slot')) for p in legacy.S.get('positions',[]) if str(p.get('slot','')).lstrip('-').isdigit()}
                for i,s in enumerate(list(legacy.S.get('slots',[]))[:ROTATION_POOL]):
                    if i in occupied or not s: continue
                    await open_core(i,s)
                    if len(legacy.S.get('positions',[]))>=TRADE_SLOTS: break
            await asyncio.sleep(1)
        except asyncio.CancelledError: raise
        except Exception as e: legacy.S['error']=f'Engine: {type(e).__name__}: {e}'; await asyncio.sleep(1)
legacy.engine=engine_core

for r in list(legacy.app.router.routes):
    if getattr(r,'path',None) == '/api/paper/stop' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/paper/stop')
async def stop_core():
    legacy.S['running']=False; legacy.S['stop_requested']=True; return await legacy.state()

for r in list(legacy.app.router.routes):
    if getattr(r,'path',None) == '/api/reset' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/reset')
async def reset_core():
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before RESET')
    for p in list(legacy.S.get('positions',[])): await legacy.close(p,'RESET')
    legacy.S['slots']=[None]*ROTATION_POOL; legacy.S['profit']=DEFAULT_PROFIT; legacy.S['reinvest']=True; legacy.S['stop_requested']=None
    legacy.S['session_elapsed']=0.0; legacy.S['session_realized']=0.0; legacy.S['session_trades']=0; legacy.S['session_started']=None; legacy.S['day_started']=None; legacy.S['cycle']=0; legacy.S['last_radar']=0.0; legacy.S['error']=None
    if legacy.S.get('mode')=='PAPER': legacy.S['account']=legacy.START; legacy.S['bot']=0.0; legacy.S['free']=0.0; legacy.S['reserve']=0.0
    return await legacy.state()

class SlotsBody(BaseModel):
    slots:list[str]=[]
    profit_pct:float=DEFAULT_PROFIT
    reinvest:bool=True
for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/slots' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/slots')
async def slots_core(b:SlotsBody):
    a=[]
    for x in b.slots:
        s=str(x).upper().replace('/','').strip()
        if s and s not in a: a.append(s)
    if len(a)>ROTATION_POOL: raise HTTPException(400,'Maximum 20 pairs')
    bad=[s for s in a if not re.fullmatch(r'[A-Z0-9]+USDT',s)]
    if bad: raise HTTPException(400,'Invalid Binance pairs: '+','.join(bad))
    old=(list(legacy.S.get('slots',[]))+[None]*ROTATION_POOL)[:ROTATION_POOL]; new=(a+[None]*ROTATION_POOL)[:ROTATION_POOL]
    occupied={int(p.get('slot')) for p in legacy.S.get('positions',[]) if str(p.get('slot','')).lstrip('-').isdigit()}
    for i in occupied:
        if old[i] and new[i]!=old[i]: new[i]=old[i]
    legacy.S['slots']=new; legacy.S['profit']=float(b.profit_pct); legacy.S['reinvest']=bool(b.reinvest); return await legacy.state()

legacy.S['profit']=DEFAULT_PROFIT
legacy.S['reinvest']=True
print('FAST_SCALPER_CORE ROTATION_POOL=20 TRADE_SLOTS=10 TP_DEFAULT=0.33 SOFT=90 HARD=300',flush=True)
