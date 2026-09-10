from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR
from fastapi import HTTPException
from pydantic import BaseModel, Field
import asyncio
import time

legacy.MAX_SLOTS = 10
legacy.S['slots'] = (list(legacy.S.get('slots', [])) + [None] * legacy.MAX_SLOTS)[:legacy.MAX_SLOTS]

import importlib
_radar_mod = importlib.import_module('.market_radar', package=__package__)
_radar_mod.FINAL = 20
RADAR.top_n = 20
_original_snapshot = RADAR.snapshot
def snapshot_top20(limit=20):
    return _original_snapshot(max(20, int(limit or 20)))
RADAR.snapshot = snapshot_top20

class Slots10(BaseModel):
    slots:list[str] = Field(default_factory=list, max_length=10)
    profit_pct:float = Field(0, ge=0, le=80)
    reinvest:bool = False

def remove_post(path):
    for r in list(legacy.app.router.routes):
        if getattr(r, 'path', None) == path and 'POST' in (getattr(r, 'methods', set()) or set()): legacy.app.router.routes.remove(r)

remove_post('/api/slots')
@legacy.app.post('/api/slots')
async def slots10(b:Slots10):
    a=[]
    for x in b.slots:
        z=str(x).upper().replace('/','').strip()
        if z and z not in a:a.append(z)
    if len(a)>10: raise HTTPException(400,'Maximum 10 pairs')
    bad=[x for x in a if not x.endswith('USDT') or len(x)<=4]
    if bad: raise HTTPException(400,'Invalid Binance pairs: '+','.join(bad))
    new=a+[None]*(10-len(a)); old=list(legacy.S.get('slots',[]))
    for i in range(10):
        old_s=str(old[i] or '').upper().replace('/','') if i<len(old) else ''
        if old_s and old_s!=str(new[i] or '').upper():
            for p in list(legacy.S.get('positions',[])):
                if p.get('slot')==i:
                    try: await legacy.close(p,'MANUAL_REMOVE')
                    except Exception as e: legacy.S['error']=f'Close {p.get("symbol")}: {type(e).__name__}: {e}'
    legacy.S['slots']=new; legacy.S['profit']=b.profit_pct; legacy.S['reinvest']=b.reinvest
    return await legacy.state()

remove_post('/api/slots/auto-top6')
@legacy.app.post('/api/slots/auto-top6')
async def auto_top10(b:Slots10):
    await legacy.radar(True)
    ranked=[];seen=set()
    for x in legacy.S.get('ranking',[]):
        s=str(x.get('symbol','')).upper().replace('/','')
        if s and s not in seen:ranked.append(s);seen.add(s)
    target=ranked[:10];old=list(legacy.S.get('slots',[]))
    for i in range(10):
        old_s=str(old[i] or '').upper().replace('/','') if i<len(old) else ''
        new_s=str(target[i] if i<len(target) else '').upper().replace('/','')
        if old_s!=new_s:
            for p in legacy.S.get('positions',[]):
                if p.get('slot')==i:
                    live=(float(p.get('current',0))/float(p.get('entry',1))-1)*100
                    print(f'[ROTATION] KEEP {p.get("symbol")} old_slot={i} new_slot={new_s} live={live:.4f}%',flush=True)
                    p['slot']=None
    legacy.S['slots']=target+[None]*(10-len(target));legacy.S['profit']=b.profit_pct;legacy.S['reinvest']=b.reinvest
    return await legacy.state()

LOSS_COOLDOWN=60.0
_previous_manage = legacy.manage
async def manage_with_loss_guard():
    before={str(x.get('id')) for x in legacy.S.get('closed',[])}
    await _previous_manage()
    from . import fast_scalper_antloss as anti
    for item in list(legacy.S.get('closed',[])):
        if str(item.get('id')) in before: continue
        pnl=float(item.get('pnl') or 0.0); reason=item.get('reason')
        if pnl < -1e-9 and reason=='PROFIT_TARGET':
            item['reason']='LOSS_AFTER_PT'
            symbol=str(item.get('symbol','')).upper().replace('/','')
            if symbol: anti._cooldowns[symbol]=time.time()+LOSS_COOLDOWN
            print(f'[TRADE] LOSS_GUARD {symbol} realized_pnl={pnl:.6f} cooldown={LOSS_COOLDOWN:.0f}s',flush=True)
legacy.manage=manage_with_loss_guard

def freeze_session_if_stopped():
    if legacy.S.get('stop_requested') and not legacy.S.get('positions'):
        started=legacy.S.get('session_started')
        if started:
            try: legacy.S['session_elapsed']=max(0.0,time.time()-legacy.datetime.fromisoformat(started).timestamp())
            except Exception: pass
        legacy.S['session_started']=None; legacy.S['stop_requested']=None

remove_post('/api/paper/stop')
@legacy.app.post('/api/paper/stop')
async def stop_final():
    legacy.S['running']=False; legacy.S['stop_requested']=time.time() if legacy.S.get('positions') else None; freeze_session_if_stopped()
    print(f'[BOT] OFF requested positions={len(legacy.S.get("positions",[]))}',flush=True)
    return await legacy.state()

async def engine_repair_final():
    from . import fast_scalper_antloss as anti
    asyncio.create_task(anti._radar_loop())
    while True:
        try:
            if legacy.S.get('running') or legacy.S.get('stop_requested'):
                await legacy.manage(); freeze_session_if_stopped()
            if legacy.S.get('running'):
                positions=legacy.S.get('positions',[]); occupied_slots={p.get('slot') for p in positions}; occupied_symbols={str(p.get('symbol','')).upper().replace('/','') for p in positions}; tasks=[]
                for i,s in enumerate(list(legacy.S.get('slots',[]))):
                    if s and i not in occupied_slots and str(s).upper().replace('/','') not in occupied_symbols: tasks.append(legacy.open_pos(i,s))
                if tasks: await asyncio.gather(*tasks)
            await asyncio.sleep(1)
        except asyncio.CancelledError: raise
        except Exception as e:
            legacy.S['error']=f'Engine: {type(e).__name__}: {e}'; print(f'[ENGINE] {type(e).__name__}: {e}',flush=True); await asyncio.sleep(1)
legacy.engine=engine_repair_final

# Reference UI: preserve original layout; only slots expand to ten.
html=legacy.HTML
html=html.replace('Slots · TOP-6','Slots · TOP-10').replace('AUTO TOP-6','AUTO TOP-10').replace('Array.from({length:6','Array.from({length:10').replace('for(let i=0;i<6;i++)','for(let i=0;i<10;i++)').replace('Maximum 6 pairs','Maximum 10 pairs')

# Force the control card into the exact requested mobile/desktop row arrangement:
# row 1 = Amount + SET BOT BALANCE + WITHDRAW
# row 2 = profit input + Reinvest
# row 3 = BOT ON + EMERGENCY + RESET
# row 4 = BOT OFF + session timer
layout_fix = r'''<style>
.fs-control-overlay{display:grid!important;grid-template-columns:minmax(0,1fr) minmax(0,1.45fr) minmax(120px,.8fr);gap:14px;align-items:center;width:100%;}
.fs-control-overlay .fs-r2{grid-column:1/-1;display:flex;gap:14px;align-items:center;}
.fs-control-overlay .fs-r2 input{width:calc((100% - 14px)*.5);max-width:260px;box-sizing:border-box;}
.fs-control-overlay .fs-r2 label{display:flex;align-items:center;gap:10px;font-size:18px;}
.fs-control-overlay .fs-r3{grid-column:1/-1;display:grid;grid-template-columns:1.2fr 1fr .7fr;gap:14px;align-items:center;}
.fs-control-overlay .fs-r4{grid-column:1/-1;display:flex;align-items:center;gap:14px;}
.fs-control-overlay button,.fs-control-overlay input{box-sizing:border-box;min-width:0;}
@media(max-width:560px){.fs-control-overlay{grid-template-columns:minmax(0,1fr) minmax(0,1.25fr) minmax(105px,.7fr);gap:10px}.fs-control-overlay .fs-r2{gap:10px}.fs-control-overlay .fs-r3{gap:10px}.fs-control-overlay .fs-r4{gap:10px}.fs-control-overlay .fs-r2 input{width:160px;max-width:45vw}.fs-control-overlay .fs-r2 label{font-size:17px;white-space:nowrap}}
</style><script>
(function(){
function t(e){return (e&&e.textContent||'').replace(/\s+/g,' ').trim()}
function btn(s){return Array.from(document.querySelectorAll('button')).find(e=>t(e).includes(s))}
function common(nodes){let a=nodes[0];while(a&&a!==document.body){if(nodes.every(n=>a.contains(n)))return a;a=a.parentElement}return null}
function apply(){
 const set=btn('SET BOT BALANCE'), wd=btn('WITHDRAW'), on=btn('BOT ON'), em=btn('EMERGENCY'), reset=btn('RESET'), off=btn('BOT OFF');
 if(!set||!wd||!on||!em||!reset||!off)return;
 const card=common([set,wd,on,em,reset,off]); if(!card||card.dataset.fsFixed==='1')return;
 const inputs=Array.from(card.querySelectorAll('input')).filter(e=>e.type!=='checkbox');
 const amount=inputs.find(e=>(e.placeholder||'').toLowerCase().includes('amount'))||inputs[0];
 const profit=inputs.find(e=>e!==amount)||inputs[1];
 const cb=card.querySelector('input[type="checkbox"]');
 const reinvest=cb?cb.closest('label'):null;
 const timer=Array.from(card.querySelectorAll('*')).find(e=>e.children.length===0&&/^SESSION\b/i.test(t(e)));
 if(!amount||!profit)return;
 card.dataset.fsFixed='1';
 Array.from(card.children).forEach(e=>e.style.display='none');
 const overlay=document.createElement('div');overlay.className='fs-control-overlay';
 function cell(el,cl){let d=document.createElement('div');if(cl)d.className=cl;d.appendChild(el);return d}
 overlay.appendChild(cell(amount));overlay.appendChild(cell(set));overlay.appendChild(cell(wd));
 const r2=document.createElement('div');r2.className='fs-r2';r2.appendChild(profit);if(reinvest)r2.appendChild(reinvest);overlay.appendChild(r2);
 const r3=document.createElement('div');r3.className='fs-r3';r3.appendChild(on);r3.appendChild(em);r3.appendChild(reset);overlay.appendChild(r3);
 const r4=document.createElement('div');r4.className='fs-r4';r4.appendChild(off);if(timer)r4.appendChild(timer);overlay.appendChild(r4);
 card.appendChild(overlay);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',apply);else apply();
setTimeout(apply,500);setTimeout(apply,1500);setTimeout(apply,3000);
})();</script>'''
html=html.replace('</body>',layout_fix+'</body>') if '</body>' in html else html+layout_fix
legacy.HTML=html
