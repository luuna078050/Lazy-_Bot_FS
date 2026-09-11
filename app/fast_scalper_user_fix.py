from __future__ import annotations
import re, time
from fastapi import HTTPException
from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR

TRADE_SLOTS = 10
ROTATION_POOL = 20
DEFAULT_PROFIT = 0.33
SOFT_TIMEOUT = 90.0
HARD_TIMEOUT = 300.0

def _indicators(symbol):
    s = str(symbol).upper().replace('/', '')
    with RADAR.lock:
        by_tf = {tf: list(RADAR.bars.get(s, {}).get(tf, ())) for tf in ('3m','1m')}
    tf = '3m' if len(by_tf['3m']) >= 22 else '1m'
    closes = [float(x.get('close') or 0) for x in by_tf[tf] if float(x.get('close') or 0) > 0]
    if len(closes) < 22:
        return {'ready': False, 'tf': tf, 'ema9': 0.0, 'ema21': 0.0, 'rsi': 50.0}
    vals = closes[-60:]
    def ema(period):
        k=2/(period+1); e=vals[0]
        for v in vals[1:]: e=float(v)*k+e*(1-k)
        return e
    gains=[]; losses=[]
    for a,b in zip(closes[-15:],closes[-14:]):
        d=b-a; gains.append(max(0,d)); losses.append(max(0,-d))
    ag=sum(gains)/14; al=sum(losses)/14
    rsi=100 if al<=1e-12 and ag>0 else (50 if al<=1e-12 else 100-100/(1+ag/al))
    return {'ready': True, 'tf': tf, 'ema9': ema(9), 'ema21': ema(21), 'rsi': rsi}

async def radar_userfix(force=False):
    if not force and legacy.S.get('last_radar') and time.time()-legacy.S['last_radar'] < 5:
        return
    try:
        rows = RADAR.snapshot(ROTATION_POOL)
        ranked=[]
        for x in rows:
            s=str(x.get('symbol','')).upper().replace('/','')
            if not s: continue
            ind=_indicators(s)
            momentum = float(x.get('change_1m_pct',0) or 0) >= -0.15
            trend = ind['ready'] and (ind['ema9'] >= ind['ema21'] or float(x.get('change_1m_pct',0) or 0) > 0)
            usable = ind['ready'] and momentum and ind['rsi'] < 80 and trend
            entry_score=float(x.get('score',0) or 0) + (8 if usable else 0) + max(0,float(x.get('pump_score',0) or 0))*4
            row=dict(x)
            row.update({'entry_allowed':bool(usable),'entry_score':round(entry_score,2),'entry_confirmations':1 if momentum else 0,
                        'ema9_3m':round(ind['ema9'],10),'ema21_3m':round(ind['ema21'],10),'rsi14_3m':round(ind['rsi'],2),
                        'indicator_tf':ind['tf'],'candidate_pool':'TOP-20','signal':'BUY' if usable else 'WATCH'})
            ranked.append(row)
        ranked.sort(key=lambda z:(float(z.get('entry_score',0)),float(z.get('score',0))),reverse=True)
        legacy.S['ranking']=ranked[:ROTATION_POOL]
        legacy.S['last_radar']=time.time()
        legacy.S['error']=None if not getattr(RADAR,'last_error',None) else 'Radar WebSocket: '+RADAR.last_error
    except Exception as e:
        legacy.S['error']=f'Radar: {type(e).__name__}: {e}'; legacy.S['last_radar']=time.time()
legacy.radar=radar_userfix
legacy.MAX_AGE=SOFT_TIMEOUT

async def manage_userfix():
    now=time.time()
    for p in list(legacy.S.get('positions',[])):
        try:
            cur=legacy.price(p['symbol']) or p.get('current') or p.get('entry')
            p['current']=cur
            entry=float(p.get('entry') or 0); stake=float(p.get('stake') or 0)
            live=((float(cur)/entry)-1)*100 if entry else 0
            p['delta_usdt']=live/100*stake; p['age_seconds']=max(0,int(now-float(p.get('opened') or now))); p['age']=p['age_seconds']
            target=float(legacy.S.get('profit',DEFAULT_PROFIT) or DEFAULT_PROFIT)
            if target>0 and live>=target:
                await legacy.close(p,'PROFIT_TARGET'); continue
            if p['age_seconds']>=SOFT_TIMEOUT and live>=0:
                await legacy.close(p,'TIMEOUT'); continue
            if p in legacy.S.get('positions',[]) and p['age_seconds']>=HARD_TIMEOUT:
                await legacy.close(p,'MAX_HOLD')
        except Exception as e:
            legacy.S['error']=f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'
legacy.manage=manage_userfix

_old_open=legacy.open_pos
async def open_userfix(i,symbol):
    if i >= TRADE_SLOTS or not symbol or len(legacy.S.get('positions',[])) >= TRADE_SLOTS: return
    s=str(symbol).upper().replace('/','')
    if any(str(p.get('symbol','')).upper().replace('/','')==s for p in legacy.S.get('positions',[])): return
    row=next((x for x in legacy.S.get('ranking',[]) if str(x.get('symbol','')).upper().replace('/','')==s),None)
    if not row or not row.get('entry_allowed'): return
    confirmed=[x for x in legacy.S.get('ranking',[]) if x.get('entry_allowed')]
    confirmed.sort(key=lambda x:float(x.get('entry_score',0) or 0),reverse=True)
    leaders={str(x.get('symbol','')).upper().replace('/','') for x in confirmed[:TRADE_SLOTS]}
    if s not in leaders: return
    await _old_open(i,s)
legacy.open_pos=open_userfix

async def engine_userfix():
    while True:
        try:
            if legacy.S.get('positions'):
                await manage_userfix()
            if legacy.S.get('running'):
                await radar_userfix(False)
                occupied={int(p.get('slot')) for p in legacy.S.get('positions',[]) if str(p.get('slot','')).lstrip('-').isdigit()}
                for i,s in enumerate(list(legacy.S.get('slots',[]))[:TRADE_SLOTS]):
                    if i in occupied or not s: continue
                    await open_userfix(i,s)
            await __import__('asyncio').sleep(1)
        except __import__('asyncio').CancelledError: raise
        except Exception as e:
            legacy.S['error']=f'Engine: {type(e).__name__}: {e}'; await __import__('asyncio').sleep(1)
legacy.engine=engine_userfix

for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/paper/stop' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/paper/stop')
async def stop_userfix():
    legacy.S['running']=False; legacy.S['stop_requested']=None; legacy.S['error']=None
    return await legacy.state()

for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/reset' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/reset')
async def reset_userfix():
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before RESET')
    for p in list(legacy.S.get('positions',[])):
        ok=await legacy.close(p,'RESET')
        if not ok: raise HTTPException(502,legacy.S.get('error') or 'Could not close position')
    legacy.S['slots']=[None]*ROTATION_POOL; legacy.S['profit']=DEFAULT_PROFIT; legacy.S['reinvest']=True
    legacy.S['session_elapsed']=0.0; legacy.S['session_realized']=0.0; legacy.S['session_trades']=0; legacy.S['session_started']=None; legacy.S['day_started']=None; legacy.S['cycle']=0; legacy.S['last_radar']=0.0; legacy.S['error']=None
    if legacy.S.get('mode')=='PAPER': legacy.S['account']=legacy.START; legacy.S['bot']=0.0; legacy.S['free']=0.0; legacy.S['reserve']=0.0
    return await legacy.state()

html=legacy.HTML
html=html.replace('Slots · TOP-20','Rotation Pool · TOP-20').replace('AUTO TOP-20','ROTATE TOP-20')
html=html.replace('Ручное изменение слота сохраняется автоматически.','В ротации участвуют TOP-20; в торговле одновременно участвуют только 10 пар.')
old="async function load(){try{const next=await request('/api/state');state=next;if(!slotsDrawn)drawSlots();render();syncSlots()}catch(e){$('msg').textContent=e.message}}"
new="async function load(){try{const next=await request('/api/state');state=next;if(!slotsDrawn)drawSlots();render();syncSlots();if(document.activeElement!==$('profit'))$('profit').value=Number(state.profit_pct||0.33).toFixed(2);if(document.activeElement!==$('reinvest'))$('reinvest').checked=state.reinvest!==false}catch(e){$('msg').textContent=e.message}}"
html=html.replace(old,new).replace('value=\"0.41\"','value=\"0.33\"').replace('value=\"0.30\"','value=\"0.33\"')
legacy.HTML=html
legacy.S['profit']=DEFAULT_PROFIT
legacy.S['reinvest']=True
print('USER_FIX_ENABLED ROTATION_POOL=20 TRADE_SLOTS=10 TP=0.33 SOFT=90 HARD=300 BOT_OFF=HARD_STOP',flush=True)
