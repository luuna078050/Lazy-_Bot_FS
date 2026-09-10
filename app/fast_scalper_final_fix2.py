from . import fast_scalper_beta_001_legacy as legacy
from .fast_scalper_final_patch import close_safe
from fastapi import HTTPException
from pydantic import BaseModel
import time, re

# 1) Timeout/profit management: close on target, and close at timeout even if negative.
async def manage_fixed2():
    now=time.time(); timeout_age=float(getattr(legacy,'MAX_AGE',60) or 60)
    for p in list(legacy.S.get('positions',[])):
        try:
            p['current']=legacy.price(p['symbol']) or p.get('current',p.get('entry',0))
            entry=float(p.get('entry') or 0); stake=float(p.get('stake') or 0); cur=float(p.get('current') or entry)
            live=((cur/entry)-1)*100 if entry else 0.0
            p['delta_usdt']=((cur/entry)-1)*stake if entry else 0.0
            p['age_seconds']=max(0,int(now-float(p.get('opened') or now))); p['age']=p['age_seconds']
            if float(legacy.S.get('profit',0) or 0)>0 and live>=float(legacy.S['profit']):
                await close_safe(p,'PROFIT_TARGET'); continue
            if p['age_seconds']>=timeout_age:
                await close_safe(p,'TIMEOUT'); continue
            if legacy.S.get('stop_requested'):
                await close_safe(p,'BOT_OFF')
        except Exception as e:
            legacy.S['error']=f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'
            print(f'[ENGINE] MANAGE_ERROR {p.get("symbol")} {type(e).__name__}: {e}',flush=True)
legacy.manage=manage_fixed2

# 2) RESET: stop first, close any remaining positions, then clear pairs and profit to zero.
for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/reset' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)

@legacy.app.post('/api/reset')
async def reset_fixed2():
    legacy.S['running']=False; legacy.S['stop_requested']=None
    for p in list(legacy.S.get('positions',[])):
        if not await close_safe(p,'RESET'):
            raise HTTPException(502,legacy.S.get('error') or f'Could not close {p.get("symbol")}')
    legacy.S['slots']=[None]*10; legacy.S['profit']=0.0; legacy.S['reinvest']=False
    legacy.S['session_elapsed']=0.0; legacy.S['session_realized']=0.0; legacy.S['session_trades']=0
    legacy.S['session_started']=None; legacy.S['day_started']=None; legacy.S['cycle']=0; legacy.S['last_radar']=0.0; legacy.S['error']=None
    if legacy.S.get('mode')=='PAPER':
        legacy.S['account']=legacy.START; legacy.S['bot']=0.0; legacy.S['free']=0.0; legacy.S['reserve']=0.0
    else: legacy.S['reserve']=max(0.0,float(legacy.S.get('account',0.0) or 0.0))
    return await legacy.state()

# 3) Manual slot assignment: only real Binance-style USDT symbols are accepted.
for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/slots' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)

class SlotsBody(BaseModel):
    slots:list[str]=[]
    profit_pct:float=0.30
    reinvest:bool=False

@legacy.app.post('/api/slots')
async def slots_fixed2(b:SlotsBody):
    a=[]
    for x in b.slots:
        s=str(x).upper().replace('/','').strip()
        if s and s not in a: a.append(s)
    if len(a)>10: raise HTTPException(400,'Maximum 10 pairs')
    bad=[s for s in a if not re.fullmatch(r'[A-Z0-9]+USDT',s)]
    if bad: raise HTTPException(400,'Invalid Binance pairs: '+','.join(bad))
    old=(list(legacy.S.get('slots',[]))+[None]*10)[:10]
    new=(a+[None]*10)[:10]
    for i in range(10):
        old_s=str(old[i] or '').upper().replace('/',''); new_s=str(new[i] or '').upper().replace('/','')
        if old_s and old_s!=new_s:
            for p in list(legacy.S.get('positions',[])):
                if p.get('slot')==i:
                    if not await close_safe(p,'MANUAL_REMOVE'):
                        raise HTTPException(502,legacy.S.get('error') or f'Could not close {p.get("symbol")}')
    legacy.S['slots']=new; legacy.S['profit']=float(b.profit_pct); legacy.S['reinvest']=bool(b.reinvest)
    return await legacy.state()

# 4) AUTO TOP-10: typed JSON body and safe rotation. Old position is closed before slot changes.
for r in list(legacy.app.router.routes):
    if getattr(r,'path',None) in ('/api/slots/auto-top6','/api/slots/auto-top10') and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)

class AutoTop10Body(BaseModel):
    slots:list[str]=[]
    profit_pct:float=0.30
    reinvest:bool=False

async def auto_top10_fixed2(b:AutoTop10Body):
    await legacy.radar(True)
    ranked=[]; seen=set()
    for x in legacy.S.get('ranking',[]):
        s=str(x.get('symbol','')).upper().replace('/','')
        if s and s not in seen and re.fullmatch(r'[A-Z0-9]+USDT',s): ranked.append(s); seen.add(s)
    target=ranked[:10]
    old=(list(legacy.S.get('slots',[]))+[None]*10)[:10]; final=list(old)
    for i in range(10):
        old_s=str(old[i] or '').upper().replace('/',''); new_s=target[i] if i<len(target) else ''
        if old_s==new_s: continue
        ok=True
        for p in list(legacy.S.get('positions',[])):
            ps=str(p.get('symbol','')).upper().replace('/','')
            if p.get('slot')==i or (p.get('slot') is None and old_s and ps==old_s):
                print(f'[ROTATION] CLOSE {ps} old_slot={i} new_slot={new_s}',flush=True)
                if not await close_safe(p,'ROTATION'):
                    ok=False; print(f'[ROTATION] CLOSE_FAILED {ps} old_slot={i} new_slot={new_s}',flush=True); break
        if ok:
            final[i]=new_s or None; print(f'[ROTATION] ASSIGN slot={i} {old_s or "EMPTY"} -> {new_s or "EMPTY"}',flush=True)
        else: final[i]=old[i]
    legacy.S['slots']=final; legacy.S['profit']=float(b.profit_pct); legacy.S['reinvest']=bool(b.reinvest)
    return await legacy.state()

@legacy.app.post('/api/slots/auto-top6')
async def auto_top6_fixed2(b:AutoTop10Body): return await auto_top10_fixed2(b)

@legacy.app.post('/api/slots/auto-top10')
async def auto_top10_fixed2_endpoint(b:AutoTop10Body): return await auto_top10_fixed2(b)

# 5) Restore compact typography without changing the approved layout/controls.
html=legacy.HTML
compact='''<style data-final-compact-ui>\n.section-title{font-size:26px!important;line-height:1.1!important;margin:0 0 10px!important}\n.pos-line,.closed-line{font-size:12px!important;line-height:1.15!important}\n.rank{font-size:10px!important}\n@media(max-width:650px){.section-title{font-size:24px!important}.pos-line,.closed-line{font-size:12px!important}}\n</style>'''
if 'data-final-compact-ui' not in html: html=html.replace('</head>',compact+'</head>',1)
legacy.HTML=html
