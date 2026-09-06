from __future__ import annotations
import time
from . import fast_scalper_v042_base as base
from fastapi.dependencies.utils import get_dependant

base.TRADING_TF='1m'
base.DEFAULT_HOLD_SECONDS=60
base.S['hold_seconds']=60
base.Start.model_fields['hold_seconds'].default=60
base.Slots.model_fields['hold_seconds'].default=60

MAX_LOSS_PCT=0.30
REENTRY_COOLDOWN=5
MAX_LOSS_COOLDOWN=60

# Prevent the same slot from immediately reopening after a close, especially after MAX_LOSS.
slot_cooldown={}

def close_position(p, reason):
    ep=p['entry']
    xp=p.get('current') or base.qprice(p['symbol']) or ep
    pnl=(xp/ep-1)*p['stake']
    base.S['free']+=p['stake']
    if base.S['reinvest']:
        base.S['free']+=pnl
        base.S['bot']+=pnl
    else:
        base.S['account']+=pnl
    base.S['realized']+=pnl
    base.S['session_realized']+=pnl
    base.S['session_trades']+=1
    base.S['closed'].insert(0,dict(p,exit=xp,pnl=pnl,reason=reason,closed_at=base.now()))
    base.S['closed']=base.S['closed'][:100]
    base.S['orders'].insert(0,{'time':base.now(),'symbol':p['symbol'],'side':'SELL','status':'FILLED','price':xp,'slot':p['slot'],'pnl':pnl,'reason':reason})
    base.S['positions'].remove(p)
    slot_cooldown[p['slot']]=time.time()+(MAX_LOSS_COOLDOWN if reason=='MAX_LOSS' else REENTRY_COOLDOWN)

base.close_position=close_position

# PAPER ON never silently repopulates slots. TOP-6 is explicit only.
def fill_auto_slots_disabled():
    return None
base.fill_auto_slots=fill_auto_slots_disabled

_original_open_position=base.open_position
def open_position_guarded(slot,sym):
    if not sym:
        return
    if time.time()<slot_cooldown.get(slot,0):
        return
    _original_open_position(slot,sym)
base.open_position=open_position_guarded

async def radar(force=False):
    if not force and base.S['last_radar'] and time.time()-base.S['last_radar']<base.RADAR_INTERVAL:
        return
    try:
        base.S['ranking']=await base.build_ranking()
        if base.S['ranking']:
            base.S['last_radar']=time.time()
            base.S['error']=None
        else:
            base.S['error']='Radar: no ranking data'
            base.S['last_radar']=time.time()-base.RADAR_INTERVAL+5
    except Exception as e:
        base.S['error']=f'Radar: {type(e).__name__}: {e}'
        base.S['last_radar']=time.time()-base.RADAR_INTERVAL+5
base.radar=radar

async def manage_positions():
    if not base.S['positions']:
        return
    try:
        ticks=await base.get_json('/api/v3/ticker/price')
        latest={x.get('symbol'):float(x.get('price')) for x in ticks if isinstance(x,dict) and x.get('symbol')}
    except Exception:
        latest={}
    for p in list(base.S['positions']):
        p['current']=latest.get(p['symbol']) or base.qprice(p['symbol']) or p.get('current') or p['entry']
        age=time.time()-p['opened']
        live=(p['current']/p['entry']-1)*100
        if base.S['profit']>0 and live>=base.S['profit']:
            close_position(p,'PROFIT_TARGET')
        elif live<=-MAX_LOSS_PCT:
            close_position(p,'MAX_LOSS')
        elif age>=base.S['hold_seconds']:
            close_position(p,'TIMEOUT')
base.manage_positions=manage_positions

@base.app.post('/api/hold')
async def set_hold(body:dict):
    try: hold=int(body.get('hold_seconds'))
    except Exception: raise base.HTTPException(400,'hold_seconds must be 60 or 180')
    if hold not in (60,180): raise base.HTTPException(400,'hold_seconds must be 60 or 180')
    base.S['hold_seconds']=hold
    return await base.state()

@base.app.post('/api/slots_manual')
async def slots_manual(b:base.Slots):
    clean=[x.upper().replace('/','') for x in b.slots if x.strip()]
    if len(clean)>base.MAX_SLOTS: raise base.HTTPException(400,f'Maximum {base.MAX_SLOTS} pairs')
    if base.S['positions']: raise base.HTTPException(400,'Close current positions before changing slots')
    base.S['slots']=[{'symbol':clean[i],'tf':base.TRADING_TF,'auto':False} if i<len(clean) else None for i in range(base.MAX_SLOTS)]
    base.S['profit']=b.profit_pct
    base.S['reinvest']=b.reinvest
    base.S['hold_seconds']=b.hold_seconds
    return await base.state()

@base.app.post('/api/slots/auto')
async def slots_auto():
    if base.S['positions']: raise base.HTTPException(400,'Close current positions before changing slots')
    if not base.S['ranking']:
        await radar(True)
    picks=[x['symbol'] for x in base.S['ranking'][:base.MAX_SLOTS]]
    base.S['slots']=[{'symbol':picks[i],'tf':base.TRADING_TF,'auto':True} if i<len(picks) else None for i in range(base.MAX_SLOTS)]
    return await base.state()

for _route in base.app.routes:
    if getattr(_route,'path',None)=='/api/slots' and 'POST' in getattr(_route,'methods',set()):
        _route.endpoint=slots_manual
        _route.dependant=get_dependant(path=_route.path,call=slots_manual)
        break

html=base.HTML
html=html.replace('Trading TF: 3m','Trading TF: 1m')
html=html.replace('<option value="60">1 min</option><option value="180" selected>3 min</option>','<option value="60" selected>1 min</option><option value="180">3 min</option>')
html=html.replace("$('hold').value=String(j.hold_seconds||180);","if(!holdEditing)$('hold').value=String(j.hold_seconds||60);")
html=html.replace('id="hold"','id="hold" onchange="holdChanged()"')
hold_handler="async function holdChanged(){holdEditing=false;try{await api('/api/hold',{method:'POST',body:JSON.stringify({hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}\n"
if hold_handler not in html:
    html=html.replace('async function start(){',hold_handler+'async function start(){',1)

# Keep the original UI, but make slot editing authoritative until the user explicitly saves it.
slot_fix=r'''<script>
(function(){
  function bootSlots(){
    const setBtn=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='SET PAIRS');
    const autoBtn=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='AUTO TOP-6');
    if(!setBtn||!autoBtn)return false;
    const card=setBtn.closest('.card')||setBtn.parentElement.parentElement;
    const inputs=[...card.querySelectorAll('input')].slice(0,6);
    let dirty=false;
    let draft=inputs.map(x=>x.value||'');
    const read=()=>inputs.map(x=>(x.value||'').trim());
    const restore=()=>{if(dirty)inputs.forEach((x,i)=>{if(x.value!==draft[i])x.value=draft[i]})};
    inputs.forEach((x,i)=>x.addEventListener('input',()=>{dirty=true;draft=read()}));
    setBtn.onclick=async function(e){
      e.preventDefault();
      try{
        const slots=read();
        const p=parseFloat(($('p')?.value||'0').replace(',','.'))||0;
        const reinvest=!!$('reinvest')?.checked;
        const hold=parseInt($('hold')?.value||'60');
        const r=await fetch('/api/slots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slots,profit_pct:p,reinvest,hold_seconds:hold})});
        if(!r.ok){const t=await r.text();throw new Error(t||('HTTP '+r.status))}
        dirty=false;draft=read();
        if(typeof window.refresh==='function')await window.refresh();
      }catch(err){alert(err.message)}
    };
    autoBtn.onclick=async function(e){
      e.preventDefault();
      try{
        const r=await fetch('/api/slots/auto',{method:'POST'});
        if(!r.ok){const t=await r.text();throw new Error(t||('HTTP '+r.status))}
        dirty=false;
        if(typeof window.refresh==='function')await window.refresh();
      }catch(err){alert(err.message)}
    };
    setInterval(restore,100);
    return true;
  }
  if(!bootSlots())setTimeout(bootSlots,250);
})();
</script>'''
if '</body>' in html:
    html=html.replace('</body>',slot_fix+'</body>')
else:
    html+=slot_fix

old_start="async function start(){try{await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}"
new_start="async function start(){try{await api('/api/slots',{method:'POST',body:JSON.stringify({slots:vals(),profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}"
if old_start in html:
    html=html.replace(old_start,new_start)
base.HTML=html
app=base.app
