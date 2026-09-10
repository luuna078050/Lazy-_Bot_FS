from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR
from fastapi import HTTPException
from pydantic import BaseModel, Field
import asyncio
import time
import re

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

DEFAULT_PROFIT = 0.30
legacy.S['profit'] = DEFAULT_PROFIT

class Slots10(BaseModel):
    slots:list[str] = Field(default_factory=list, max_length=10)
    profit_pct:float = Field(DEFAULT_PROFIT, ge=0, le=80)
    reinvest:bool = False

class Start10(BaseModel):
    profit_pct:float = Field(DEFAULT_PROFIT, ge=0, le=80)
    reinvest:bool = False

def remove_post(path):
    for r in list(legacy.app.router.routes):
        if getattr(r, 'path', None) == path and 'POST' in (getattr(r, 'methods', set()) or set()):
            legacy.app.router.routes.remove(r)

async def radar20(force=False):
    if not force and legacy.S.get('last_radar') and time.time()-legacy.S['last_radar'] < 60:
        return
    try:
        rows = RADAR.snapshot(20)
        out=[]
        for x in rows:
            s=str(x.get('symbol','')).replace('/','').upper()
            if s:
                out.append({'symbol':s,'price':float(x.get('price') or 0),'change':float(x.get('change_24h_pct') or 0),'volume':float(x.get('quote_volume_24h') or 0),'score':float(x.get('score') or 0),'signal':x.get('signal','WAIT'),'tf':legacy.TF})
        out.sort(key=lambda x:(x['score'],x['volume']), reverse=True)
        legacy.S['ranking']=out[:20]
        legacy.S['last_radar']=time.time()
        legacy.S['error']=None if not getattr(RADAR,'last_error',None) else 'Radar WebSocket: '+RADAR.last_error
    except Exception as e:
        legacy.S['error']=f'Radar: {type(e).__name__}: {e}'
        legacy.S['last_radar']=time.time()
legacy.radar = radar20

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
    legacy.S['slots']=new
    legacy.S['profit']=b.profit_pct
    legacy.S['reinvest']=b.reinvest
    return await legacy.state()

remove_post('/api/slots/auto-top6')
@legacy.app.post('/api/slots/auto-top6')
async def auto_top10(b:Slots10):
    await legacy.radar(True)
    ranked=[];seen=set()
    for x in legacy.S.get('ranking',[]):
        s=str(x.get('symbol','')).upper().replace('/','')
        if s and s not in seen:ranked.append(s);seen.add(s)
    target=ranked[:10]
    old=list(legacy.S.get('slots',[]))
    for i in range(10):
        old_s=str(old[i] or '').upper().replace('/','') if i<len(old) else ''
        new_s=str(target[i] if i<len(target) else '').upper().replace('/','')
        if old_s!=new_s:
            for p in legacy.S.get('positions',[]):
                if p.get('slot')==i:
                    live=(float(p.get('current',0))/float(p.get('entry',1))-1)*100
                    print(f'[ROTATION] KEEP {p.get("symbol")} old_slot={i} new_slot={new_s} live={live:.4f}%',flush=True)
                    p['slot']=None
    legacy.S['slots']=target+[None]*(10-len(target))
    legacy.S['profit']=b.profit_pct
    legacy.S['reinvest']=b.reinvest
    return await legacy.state()

remove_post('/api/paper/start')
@legacy.app.post('/api/paper/start')
async def start10(b:Start10):
    if legacy.S.get('positions'):
        raise HTTPException(400,'Close current positions before a new session')
    if legacy.S['mode']=='PAPER':
        if legacy.S['bot']<=0:
            legacy.S['bot']=legacy.S['account']; legacy.refresh_reserve(); legacy.S['free']=max(0.0,legacy.S['bot']-legacy.invested())
        legacy.S.update(profit=b.profit_pct,reinvest=b.reinvest,running=True,started=legacy.now(),session_started=legacy.now(),session_elapsed=0.0,session_realized=0.0,session_trades=0,error=None)
        legacy.S['day_started']=legacy.S['day_started'] or legacy.now()
        return await legacy.state()
    if legacy.S['mode']=='BINANCE_TEST':
        if not legacy.B.configured: raise HTTPException(400,'Binance API credentials are not configured')
        if not legacy.B.testnet: raise HTTPException(403,'BINANCE_TEST requires Binance Testnet')
        if legacy.S['bot']<=0: raise HTTPException(400,'Set Bot Allocation before starting BINANCE_TEST')
        try:
            await legacy.B.ping(); acc=await legacy.B.account(); free_usdt=next((float(x['free']) for x in acc.get('balances',[]) if x.get('asset')=='USDT'),0.0)
            if free_usdt<legacy.S['bot']: raise RuntimeError(f'Bot allocation {legacy.S["bot"]:.8f} exceeds free USDT {free_usdt:.8f}')
            legacy.S['account']=free_usdt+legacy.invested(); legacy.refresh_reserve()
            legacy.S.update(profit=b.profit_pct,reinvest=b.reinvest,running=True,started=legacy.now(),session_started=legacy.now(),session_elapsed=0.0,session_realized=0.0,session_trades=0,error=None)
            legacy.S['day_started']=legacy.S['day_started'] or legacy.now()
            return await legacy.state()
        except Exception as e:
            raise HTTPException(400,f'Binance TEST start failed: {type(e).__name__}: {e}')
    raise HTTPException(403,'Unsupported trading mode')

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

remove_post('/api/reset')
@legacy.app.post('/api/reset')
async def reset_final():
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before RESET')
    legacy.S['slots']=[None]*10; legacy.S['profit']=DEFAULT_PROFIT; legacy.S['reinvest']=False; legacy.S['session_elapsed']=0; legacy.S['error']=None
    if legacy.S['mode']=='PAPER':
        legacy.S['account']=legacy.START; legacy.S['bot']=0.0; legacy.S['free']=0.0; legacy.S['reserve']=0.0
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

async def startup_repaired():
    RADAR.start()
    asyncio.create_task(legacy.engine())
    asyncio.create_task(legacy.radar(True))
try:
    legacy.app.router.on_startup = [fn for fn in legacy.app.router.on_startup if getattr(fn, '__name__', '') != 'startup']
except Exception:
    pass
legacy.app.router.on_startup.append(startup_repaired)

# Final production mobile UI. The controls card is deliberately compact:
# Amount + SET BOT BALANCE + WITHDRAW on one line, then Profit + Reinvest,
# then ON/EMERGENCY/RESET, then OFF + SESSION. No duplicate control block.
html=legacy.HTML
html=html.replace('Slots · TOP-6','Slots · TOP-10').replace('AUTO TOP-6','AUTO TOP-10').replace('Array.from({length:6','Array.from({length:10').replace('for(let i=0;i<6;i++)','for(let i=0;i<10;i++)').replace('Maximum 6 pairs','Maximum 10 pairs')

controls_html='''<div class="card fs-controls">
  <div class="row fs-control-row fs-funding">
    <input id="allocation" class="input fs-amount" type="number" step="0.01" min="0" placeholder="Amount">
    <button type="button" class="btn test fs-fund-btn" id="allocBtn">SET BOT BALANCE</button>
    <button type="button" class="btn stop fs-withdraw-btn" id="withdrawBtn">WITHDRAW</button>
  </div>
  <div class="row fs-control-row fs-profit-row">
    <input id="profit" class="input fs-profit" type="number" step="0.01" min="0" max="80" value="0.30" placeholder="Profit Target">
    <label class="fs-reinvest"><input id="reinvest" type="checkbox" checked> <span>Reinvest</span></label>
  </div>
  <div class="row fs-control-row fs-actions">
    <button type="button" class="btn on" id="onBtn">BOT ON · ACTIVE</button>
    <button type="button" class="btn stop" id="emBtn">EMERGENCY</button>
    <button type="button" class="btn" id="resetBtn">RESET</button>
  </div>
  <div class="row fs-control-row fs-session">
    <button type="button" class="btn stop" id="offBtn">BOT OFF</button>
    <span class="muted" id="tim">SESSION 00:00 · 24H 00:00</span>
  </div>
</div>'''

# Robustly replace the entire legacy card that owns #allocation.
def replace_card_containing(source, marker, replacement):
    pos=source.find(marker)
    if pos<0:return source
    start=source.rfind('<div class="card"',0,pos)
    if start<0:return source
    depth=0
    for m in re.finditer(r'<div\b|</div\s*>',source[start:],re.I):
        token=m.group(0).lower()
        if token.startswith('<div'):
            depth+=1
        else:
            depth-=1
            if depth==0:
                end=start+m.end()
                return source[:start]+replacement+source[end:]
    return source

html=replace_card_containing(html,'id="allocation"',controls_html)

# If a previous repair layer left another legacy control card, remove only
# additional cards containing the old action ids; the single fs-controls card stays.
while True:
    matches=[];pos=0
    while True:
        p=html.find('<div class="card"',pos)
        if p<0:break
        q=html.find('</div>',p)
        if q<0:break
        # locate allocation-bearing card through balanced parser
        if 'id="allocation"' in html[p:q+7]: pass
        pos=q+7
        # handled by exact replacement above
        break
    # No broad removal: production HTML must retain all functional cards.
    break

# Compact mobile CSS. It overrides the legacy wrapping only inside fs-controls.
style='''<style>
.fs-controls{padding:12px;margin-top:8px;margin-bottom:8px}
.fs-controls .fs-control-row{display:flex;flex-wrap:nowrap;align-items:center;gap:8px;width:100%}
.fs-controls .fs-funding{min-width:0}
.fs-controls .fs-amount{flex:0 1 120px;min-width:105px;width:120px;padding:9px 10px}
.fs-controls .fs-fund-btn{flex:1 1 auto;min-width:0;padding:10px 8px;white-space:nowrap;font-size:13px}
.fs-controls .fs-withdraw-btn{flex:0 0 105px;min-width:0;padding:10px 8px;white-space:nowrap;font-size:13px}
.fs-controls .fs-profit-row{margin-top:7px}
.fs-controls .fs-profit{flex:0 1 220px;min-width:0;padding:9px 10px}
.fs-controls .fs-reinvest{display:flex;align-items:center;gap:7px;white-space:nowrap;padding:7px 4px;font-size:16px}
.fs-controls .fs-reinvest input{width:20px;height:20px;margin:0}
.fs-controls .fs-actions{margin-top:7px}
.fs-controls .fs-actions .btn{flex:1 1 0;min-width:0;padding:10px 6px;font-size:13px;white-space:nowrap}
.fs-controls .fs-session{margin-top:7px}
.fs-controls .fs-session #offBtn{flex:0 0 105px;min-width:105px;padding:10px 8px;font-size:13px;white-space:nowrap}
.fs-controls .fs-session #tim{flex:1;text-align:center;white-space:nowrap;font-size:14px}
@media(max-width:420px){
 .fs-controls .fs-amount{flex-basis:92px;width:92px;min-width:88px}
 .fs-controls .fs-fund-btn{font-size:11px}
 .fs-controls .fs-withdraw-btn{flex-basis:88px;font-size:11px}
 .fs-controls .fs-actions .btn{font-size:11px}
 .fs-controls .fs-session #offBtn{flex-basis:88px;min-width:88px;font-size:11px}
 .fs-controls .fs-session #tim{font-size:12px}
 .fs-controls .fs-reinvest{font-size:14px}
}
</style>'''
html=html.replace('</head>',style+'</head>',1)

# Add a minimal status/navigation treatment from the approved production reference
# without changing any existing API wiring.
html=html.replace('<div class="title">⚡ Fast Scalper Beta</div>','<div class="title">⚡ Fast Scalper Beta <span class="fs-online">● ONLINE</span></div>',1)
html=html.replace('</body>','<div class="fs-bottom-nav"><span class="active">⌂<small>Dashboard</small></span><span>▥<small>Positions</small></span><span>◎<small>Radar</small></span><span>⚙<small>Settings</small></span><span>▤<small>Logs</small></span></div></body>',1)
html=html.replace('</style></head>','</style><style>.fs-online{float:right;font-size:12px;background:#063f32;color:#42e89a;border-radius:14px;padding:5px 9px;vertical-align:middle}.fs-bottom-nav{position:sticky;bottom:0;display:flex;justify-content:space-around;gap:4px;background:#080e1b;border-top:1px solid #293650;padding:8px 4px;margin:14px -14px -14px}.fs-bottom-nav span{color:#8b97ae;text-align:center;font-size:20px;min-width:55px}.fs-bottom-nav span.active{color:#1689ff}.fs-bottom-nav small{display:block;font-size:9px;margin-top:2px}</style></head>')
legacy.HTML=html
legacy.S['profit']=DEFAULT_PROFIT
