from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_final_patch as final
from fastapi import HTTPException
from pydantic import BaseModel
import time, re

# Lifecycle: 90s is a SOFT timeout. A losing position is allowed to wait for
# break-even. 300s is the hard safety cap.
MAX_HOLD = 300.0

async def manage_fixed2():
    now=time.time(); timeout_age=float(getattr(legacy,'MAX_AGE',90) or 90)
    for p in list(legacy.S.get('positions',[])):
        try:
            p['current']=legacy.price(p['symbol']) or p.get('current',p.get('entry',0))
            entry=float(p.get('entry') or 0); stake=float(p.get('stake') or 0); cur=float(p.get('current') or entry)
            live=((cur/entry)-1)*100 if entry else 0.0
            p['delta_usdt']=((cur/entry)-1)*stake if entry else 0.0
            p['age_seconds']=max(0,int(now-float(p.get('opened') or now))); p['age']=p['age_seconds']
            if float(legacy.S.get('profit',0) or 0)>0 and live>=float(legacy.S['profit']):
                await final.close_safe(p,'PROFIT_TARGET'); continue
            # Soft timeout: close at 90s only when non-negative. Losing positions wait.
            if p['age_seconds']>=timeout_age and live>=0:
                await final.close_safe(p,'TIMEOUT'); continue
            # Hard safety cap: never let a losing position hang forever.
            if p['age_seconds']>=MAX_HOLD:
                await final.close_safe(p,'MAX_HOLD'); continue
            if legacy.S.get('stop_requested'):
                await final.close_safe(p,'BOT_OFF')
        except Exception as e:
            legacy.S['error']=f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'
            print(f'[ENGINE] MANAGE_ERROR {p.get("symbol")} {type(e).__name__}: {e}',flush=True)
legacy.manage=manage_fixed2
legacy.MAX_AGE=90

# RESET: stop first, close remaining positions, then clear pairs/session.
for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/reset' and 'POST' in (getattr(r,'methods',set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.post('/api/reset')
async def reset_fixed2():
    legacy.S['running']=False; legacy.S['stop_requested']=None
    for p in list(legacy.S.get('positions',[])):
        if not await final.close_safe(p,'RESET'):
            raise HTTPException(502,legacy.S.get('error') or f'Could not close {p.get("symbol")}')
    legacy.S['slots']=[None]*10; legacy.S['profit']=0.0; legacy.S['reinvest']=False
    legacy.S['session_elapsed']=0.0; legacy.S['session_realized']=0.0; legacy.S['session_trades']=0
    legacy.S['session_started']=None; legacy.S['day_started']=None; legacy.S['cycle']=0; legacy.S['last_radar']=0.0; legacy.S['error']=None
    if legacy.S.get('mode')=='PAPER':
        legacy.S['account']=legacy.START; legacy.S['bot']=0.0; legacy.S['free']=0.0; legacy.S['reserve']=0.0
    else:
        legacy.S['reserve']=max(0.0,float(legacy.S.get('account',0.0) or 0.0))
    return await legacy.state()

class SlotsBody(BaseModel):
    slots:list[str]=[]
    profit_pct:float=0.30
    reinvest:bool=False

# Manual slot edits never close an open trade. A slot occupied by a live
# position remains pinned until that position naturally closes.
for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/slots' and 'POST' in (getattr(r,'methods',set()) or set()):
        legacy.app.router.routes.remove(r)

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
    pinned=[]
    for i in range(10):
        old_s=str(old[i] or '').upper().replace('/','')
        if not old_s: continue
        occupied=any(int(p.get('slot',-1))==i for p in legacy.S.get('positions',[]))
        if occupied and str(new[i] or '').upper().replace('/','') != old_s:
            new[i]=old[i]
            pinned.append(old_s)
    legacy.S['slots']=new; legacy.S['profit']=float(b.profit_pct); legacy.S['reinvest']=bool(b.reinvest)
    if pinned: legacy.S['error']='Open positions pinned: '+', '.join(pinned)
    return await legacy.state()

class AutoTop10Body(BaseModel):
    slots:list[str]=[]
    profit_pct:float=0.30
    reinvest:bool=False

# AUTO TOP-10 is a ranking refresh, NOT a liquidation command.
# Occupied slots are pinned. New TOP-10 symbols fill only empty slots.
# When a pinned position closes, its slot becomes eligible on the next AUTO TOP-10.
async def auto_top10_fixed2(b:AutoTop10Body):
    await legacy.radar(True)
    ranked=[]; seen=set()
    for x in legacy.S.get('ranking',[]):
        s=str(x.get('symbol','')).upper().replace('/','')
        if s and s not in seen and re.fullmatch(r'[A-Z0-9]+USDT',s):
            ranked.append(s); seen.add(s)
    target=ranked[:10]
    old=(list(legacy.S.get('slots',[]))+[None]*10)[:10]
    final_slots=list(old)
    occupied_slots={int(p.get('slot')) for p in legacy.S.get('positions',[]) if str(p.get('slot','')).lstrip('-').isdigit()}
    used={str(x).upper().replace('/','') for x in final_slots if x}
    for i in range(10):
        if i in occupied_slots:
            print(f'[ROTATION] PIN slot={i} pair={final_slots[i]} reason=OPEN_POSITION',flush=True)
            continue
        # Only empty/free slots are rotated. Prefer the best ranked pair not already used.
        candidate=next((s for s in target if s not in used), None)
        if candidate:
            previous=final_slots[i]
            if previous and previous in used: used.discard(previous)
            final_slots[i]=candidate; used.add(candidate)
            print(f'[ROTATION] ASSIGN slot={i} {previous or "EMPTY"} -> {candidate}',flush=True)
    legacy.S['slots']=final_slots; legacy.S['profit']=float(b.profit_pct); legacy.S['reinvest']=bool(b.reinvest)
    legacy.S['error']=None
    return await legacy.state()

for r in list(legacy.app.router.routes):
    if getattr(r,'path',None) in ('/api/slots/auto-top6','/api/slots/auto-top10') and 'POST' in (getattr(r,'methods',set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.post('/api/slots/auto-top6')
async def auto_top6_fixed2(b:AutoTop10Body): return await auto_top10_fixed2(b)

@legacy.app.post('/api/slots/auto-top10')
async def auto_top10_fixed2_endpoint(b:AutoTop10Body): return await auto_top10_fixed2(b)

# Restore the approved compact UI and 10-slot control surface.
html=legacy.HTML
html=html.replace('Slots · TOP-6','Slots · TOP-10').replace('AUTO TOP-6','AUTO TOP-10')
html=html.replace('Maximum 6 pairs','Maximum 10 pairs')
html=html.replace('Array.from({length:6}', 'Array.from({length:10}')
html=html.replace('Array.from({length:6},(_,i)=>', 'Array.from({length:10},(_,i)=>')
html=html.replace('for(let i=0;i<6;i++)', 'for(let i=0;i<10;i++)')
html=html.replace('for(let i=0;i<6;i++)', 'for(let i=0;i<10;i++)')
html=html.replace("$('topBtn').addEventListener('click',autoTop6Click)", "$('topBtn').addEventListener('click',autoTop6Click)")
# The browser endpoint name remains /api/slots/auto-top6 for backward compatibility;
# its button is now visibly AUTO TOP-10.
compact='''<style data-final-compact-ui>\n.section-title{font-size:26px!important;line-height:1.1!important;margin:0 0 10px!important}\n.pos-line,.closed-line{font-size:12px!important;line-height:1.15!important}\n.rank{font-size:10px!important}\n@media(max-width:650px){.section-title{font-size:24px!important}.pos-line,.closed-line{font-size:12px!important}}\n</style>'''
if 'data-final-compact-ui' not in html: html=html.replace('</head>',compact+'</head>',1)
legacy.HTML=html
