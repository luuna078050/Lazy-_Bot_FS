from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR
from fastapi import HTTPException
from pydantic import BaseModel, Field
import asyncio
import time

# TOP-10 slots. The Radar pipeline remains based on the existing TOP-150 universe.
legacy.MAX_SLOTS = 10
legacy.S['slots'] = (list(legacy.S.get('slots', [])) + [None] * legacy.MAX_SLOTS)[:legacy.MAX_SLOTS]

# Rotation pool is TOP-20; the underlying TOP-150 -> 80 -> 40 -> 25 stages stay intact.
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
        if getattr(r, 'path', None) == path and 'POST' in (getattr(r, 'methods', set()) or set()):
            legacy.app.router.routes.remove(r)

# Replace the old six-slot routes with ten-slot versions.
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

# Loss guard: a MARKET SELL can fill below the PT snapshot. If the realized
# result is negative, it is no longer treated as a normal PT and the symbol is
# blocked before it can immediately re-enter.
LOSS_COOLDOWN=60.0
_previous_manage = legacy.manage
async def manage_with_loss_guard():
    before={str(x.get('id')) for x in legacy.S.get('closed',[])}
    await _previous_manage()
    from . import fast_scalper_antloss as anti
    for item in list(legacy.S.get('closed',[])):
        if str(item.get('id')) in before: continue
        pnl=float(item.get('pnl') or 0.0)
        reason=item.get('reason')
        if pnl < -1e-9 and reason=='PROFIT_TARGET':
            item['reason']='LOSS_AFTER_PT'
            symbol=str(item.get('symbol','')).upper().replace('/','')
            if symbol: anti._cooldowns[symbol]=time.time()+LOSS_COOLDOWN
            print(f'[TRADE] LOSS_GUARD {symbol} realized_pnl={pnl:.6f} cooldown={LOSS_COOLDOWN:.0f}s',flush=True)
legacy.manage=manage_with_loss_guard

# Session timer: BOT OFF stops new entries immediately. Existing positions may
# finish under the existing grace period. The session clock freezes only after
# the final position is closed, exactly as requested.
def freeze_session_if_stopped():
    if legacy.S.get('stop_requested') and not legacy.S.get('positions'):
        started=legacy.S.get('session_started')
        if started:
            try:
                legacy.S['session_elapsed']=max(0.0,time.time()-legacy.datetime.fromisoformat(started).timestamp())
            except Exception: pass
        legacy.S['session_started']=None
        legacy.S['stop_requested']=None

remove_post('/api/paper/stop')
@legacy.app.post('/api/paper/stop')
async def stop_final():
    legacy.S['running']=False
    legacy.S['stop_requested']=time.time() if legacy.S.get('positions') else None
    freeze_session_if_stopped()
    print(f'[BOT] OFF requested positions={len(legacy.S.get("positions",[]))}',flush=True)
    return await legacy.state()

# Keep the current repaired engine, but make it call the loss-guarded manager
# and freeze the session as soon as the last position disappears.
async def engine_repair_final():
    from . import fast_scalper_antloss as anti
    asyncio.create_task(anti._radar_loop())
    while True:
        try:
            if legacy.S.get('running') or legacy.S.get('stop_requested'):
                await legacy.manage()
                freeze_session_if_stopped()
            if legacy.S.get('running'):
                positions=legacy.S.get('positions',[])
                occupied_slots={p.get('slot') for p in positions}
                occupied_symbols={str(p.get('symbol','')).upper().replace('/','') for p in positions}
                tasks=[]
                for i,s in enumerate(list(legacy.S.get('slots',[]))):
                    if s and i not in occupied_slots and str(s).upper().replace('/','') not in occupied_symbols:
                        tasks.append(legacy.open_pos(i,s))
                if tasks: await asyncio.gather(*tasks)
            await asyncio.sleep(1)
        except asyncio.CancelledError: raise
        except Exception as e:
            legacy.S['error']=f'Engine: {type(e).__name__}: {e}'
            print(f'[ENGINE] {type(e).__name__}: {e}',flush=True)
            await asyncio.sleep(1)
legacy.engine=engine_repair_final

# UI: TOP-10 in two columns, smaller Slots heading, and an explicit red/green
# trading status directly inside Open Positions.
html=legacy.HTML
html=html.replace('Slots · TOP-6','Slots · TOP-10')
html=html.replace('AUTO TOP-6','AUTO TOP-10')
html=html.replace('Array.from({length:6','Array.from({length:10')
html=html.replace('for(let i=0;i<6;i++)','for(let i=0;i<10;i++)')
html=html.replace('Maximum 6 pairs','Maximum 10 pairs')
html=html.replace('.grid6{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}', '.grid6{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}')
html=html.replace('.section-title{margin:0 0 12px;font-size:28px}', '.section-title{margin:0 0 12px;font-size:28px}.slots-title{font-size:26px!important}')
html=html.replace('class="section-title">Slots', 'class="section-title slots-title">Slots')
html=html.replace('<div class="card"><h2 class="section-title">Open Positions</h2><div id="pos" class="muted">No open positions</div></div>', '<div class="card"><h2 class="section-title">Open Positions</h2><div id="tradeStatus" class="trade-status">BOT ON · TRADING ACTIVE</div><div id="pos" class="muted">No open positions</div></div>')
html=html.replace('.pos-line{display:grid;', '.trade-status{display:inline-block;font-size:11px;font-weight:900;padding:5px 9px;border-radius:8px;margin-bottom:8px;background:#078b53;color:#fff}.trade-status.off{background:#a72e3f}.pos-line{display:grid;')

# Update the renderer without replacing the whole renderer body.
needle="function render(){const m=state.mode||'PAPER';"
insert="function render(){const m=state.mode||'PAPER';const ts=$('tradeStatus');if(ts){const on=!!state.running;ts.textContent=on?'BOT ON · TRADING ACTIVE':(state.positions&&state.positions.length?'BOT OFF · CLOSING POSITIONS':'BOT OFF · TRADING STOPPED');ts.className='trade-status'+(on?'':' off');}"
html=html.replace(needle,insert,1)

legacy.HTML=html
