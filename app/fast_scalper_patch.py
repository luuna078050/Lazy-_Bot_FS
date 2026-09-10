from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_antloss as anti
from fastapi import HTTPException
import asyncio
import time

legacy.MAX_AGE = 60
STOP_GRACE = 60.0

async def manage_safe():
    now=time.time(); stop_at=legacy.S.get('stop_requested')
    for p in list(legacy.S.get('positions', [])):
        try:
            snapshot=legacy.price(p['symbol']) or p['current']; p['current']=snapshot
            live=(snapshot/p['entry']-1)*100; age=now-p['opened']
            if legacy.S['profit']>0 and live>=legacy.S['profit']:
                print(f'[TRADE] CLOSE {p["symbol"]} reason=PROFIT_TARGET age={age:.1f}s live={live:.4f}% price={snapshot}',flush=True)
                await anti._close_at_snapshot(p,'PROFIT_TARGET',snapshot); anti._cooldowns[p['symbol']]=time.time()+anti.COOLDOWN_PROFIT; continue
            if stop_at:
                if now-stop_at>=STOP_GRACE:
                    print(f'[TRADE] CLOSE {p["symbol"]} reason=BOT_OFF age={age:.1f}s live={live:.4f}% price={snapshot}',flush=True)
                    await anti._close_at_snapshot(p,'BOT_OFF',snapshot)
                continue
            if age>=legacy.MAX_AGE:
                if live>=0:
                    print(f'[TRADE] CLOSE {p["symbol"]} reason=TIMEOUT age={age:.1f}s live={live:.4f}% price={snapshot}',flush=True)
                    await anti._close_at_snapshot(p,'TIMEOUT',snapshot); anti._cooldowns[p['symbol']]=time.time()+anti.COOLDOWN_TIMEOUT
                else:
                    p['opened']=now; p['timeout_armed']=True
                    print(f'[TRADE] HOLD {p["symbol"]} reason=TIMEOUT_DEFERRED age={age:.1f}s live={live:.4f}% price={snapshot}',flush=True)
        except Exception as e:
            legacy.S['error']=f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'; anti._cooldowns[p.get('symbol','')]=time.time()+anti.COOLDOWN_ERROR
    if stop_at and not legacy.S.get('positions'): legacy.S['stop_requested']=None

anti.manage=manage_safe; legacy.manage=manage_safe
_original_close=legacy.close
async def close_with_timestamp(p,reason):
    result=await _original_close(p,reason)
    try:
        for item in legacy.S.get('closed',[]):
            if item.get('id')==p.get('id'): item['closed_at']=time.time(); break
    except Exception: pass
    return result
legacy.close=close_with_timestamp

def remove_post(path):
    for r in list(legacy.app.router.routes):
        if getattr(r,'path',None)==path and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)

remove_post('/api/paper/stop')
@legacy.app.post('/api/paper/stop')
async def stop_fixed():
    legacy.S['running']=False; legacy.S['stop_requested']=time.time() if legacy.S.get('positions') else None
    print(f'[BOT] OFF requested positions={len(legacy.S.get("positions",[]))}',flush=True)
    return await legacy.state()

_original_start=legacy.start
async def start_clean(b):
    if legacy.S.get('positions'): raise HTTPException(400,'Close current positions before a new session')
    legacy.S['stop_requested']=None; result=await _original_start(b); legacy.S['closed']=[]; legacy.S['orders']=[]; return await legacy.state()
remove_post('/api/paper/start')
@legacy.app.post('/api/paper/start')
async def start_endpoint(b:legacy.Start): return await start_clean(b)

async def reset_fixed():
    if legacy.S.get('running') or legacy.S.get('positions'): raise HTTPException(400,'BOT OFF and no open positions required')
    s=legacy.S; s['stop_requested']=None; s['running']=False; s['bot']=0.0; s['free']=0.0; s['realized']=0.0; s['session_realized']=0.0; s['session_trades']=0; s['session_started']=None; s['session_elapsed']=0.0; s['day_started']=None; s['day_elapsed']=0.0; s['positions']=[]; s['closed']=[]; s['orders']=[]; s['slots']=[None]*legacy.MAX_SLOTS; s['profit']=0.41; s['reinvest']=False; s['cycle']=0; s['last_radar']=0.0; s['error']=None
    if s.get('mode')=='PAPER': s['account']=legacy.START; s['reserve']=legacy.START
    else: s['reserve']=max(0.0,float(s.get('account',0.0) or 0.0))
    return await legacy.state()
remove_post('/api/reset')
@legacy.app.post('/api/reset')
async def reset_endpoint(): return await reset_fixed()

# TOP-6 rotation never force-closes a live trade. A changed slot is detached
# and becomes a recovery position while the new TOP-6 slot remains available.
remove_post('/api/slots/auto-top6')
@legacy.app.post('/api/slots/auto-top6')
async def auto_top6_fixed(b:legacy.Slots):
    await legacy.radar(True); ranked=[]; seen=set()
    for x in legacy.S.get('ranking',[]):
        s=str(x.get('symbol','')).upper().replace('/','')
        if s and s not in seen: ranked.append(s); seen.add(s)
    target=ranked[:legacy.MAX_SLOTS]; old=list(legacy.S.get('slots',[]))
    for i in range(legacy.MAX_SLOTS):
        old_s=str(old[i] or '').upper().replace('/',''); new_s=str(target[i] if i<len(target) else '').upper().replace('/','')
        if old_s!=new_s:
            for p in legacy.S.get('positions',[]):
                if p.get('slot')==i:
                    live=(float(p.get('current',0))/float(p.get('entry',1))-1)*100
                    print(f'[ROTATION] KEEP {p.get("symbol")} old_slot={i} new_slot={new_s} live={live:.4f}%',flush=True)
                    p['slot']=None
    legacy.S['slots']=target+[None]*(legacy.MAX_SLOTS-len(target)); legacy.S['profit']=b.profit_pct; legacy.S['reinvest']=b.reinvest
    return await legacy.state()

# Opening a selected TOP-6 slot is intentionally independent of a second
# diagnostic filter. Radar already ranks the best candidates first and a slot
# is the user's explicit selection. The old extra history/momentum gate could
# block otherwise valid TOP-6 slots and leave 4/6 (or fewer) positions open.
_original_open_pos=legacy.open_pos
async def open_pos_safe(i,s):
    if not s:return
    symbol=str(s).upper().replace('/','')
    if any(str(p.get('symbol','')).upper().replace('/','')==symbol for p in legacy.S.get('positions',[])):
        print(f'[TRADE] SKIP {symbol} reason=DUPLICATE_SYMBOL',flush=True); return
    await _original_open_pos(i,s)
legacy.open_pos=open_pos_safe

async def engine_fixed():
    asyncio.create_task(anti._radar_loop())
    while True:
        try:
            if legacy.S.get('running') or legacy.S.get('stop_requested'): await manage_safe()
            if legacy.S.get('running'):
                occupied={str(p.get('symbol','')).upper().replace('/','') for p in legacy.S.get('positions',[])}
                for i,s in enumerate(list(legacy.S.get('slots',[]))):
                    if s and not any(p.get('slot')==i for p in legacy.S.get('positions',[])):
                        n=str(s).upper().replace('/','')
                        if n in occupied: continue
                        await legacy.open_pos(i,s); occupied={str(p.get('symbol','')).upper().replace('/','') for p in legacy.S.get('positions',[])}
            await asyncio.sleep(1)
        except asyncio.CancelledError: raise
        except Exception as e: legacy.S['error']=f'Engine: {type(e).__name__}: {e}'; await asyncio.sleep(1)
anti.manage=manage_safe; legacy.manage=manage_safe; legacy.engine=engine_fixed

# UI is rebuilt from the final HTML rather than fragile string replacements.
# This keeps the allocation/withdrawal controls unambiguous and removes the
# old BOT/IN/OUT labels from the live position rows.
html=legacy.HTML

html=html.replace('.row{display:flex;gap:8px;flex-wrap:wrap}', '.row{display:flex;gap:8px;flex-wrap:wrap}.allocation-block{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:end}.money-field{display:flex;flex-direction:column;gap:3px;min-width:0}.money-label{font-size:10px;font-weight:800;letter-spacing:.04em;color:#8b97ae}.money-input{width:100%;min-width:0}.money-actions{display:flex;gap:8px;align-items:end}.money-actions .btn{height:42px}.trade-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}.trade-line{white-space:nowrap;min-width:max-content}.line{font-size:12px;padding:5px 0;border-bottom:1px solid #24314a}.pos-line{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid #24314a}.pos-main{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pos-timer{font-weight:800;color:#8b97ae;white-space:nowrap}.profit-pos{color:#19d58a}.profit-neg{color:#ff7180}')

old_controls='<div class="card"><div class="row"><input id="allocation" class="input amount" type="number" step="0.01" min="0" placeholder="Amount"><button type="button" class="btn test" id="allocBtn">SET BOT BALANCE</button><button type="button" class="btn stop" id="withdrawBtn">WITHDRAW</button><input id="profit" class="input" type="number" step="0.01" value="0.41"><label style="padding:10px"><input id="reinvest" type="checkbox" checked> Reinvest</label></div>'
new_controls='<div class="card"><div class="allocation-block"><div class="money-field"><div class="money-label">BOT BALANCE · USDT</div><input id="allocation" class="input money-input" type="number" step="0.01" min="0" value="150" placeholder="150"></div><div class="money-actions"><button type="button" class="btn test" id="allocBtn">SET BOT BALANCE</button></div></div><div class="allocation-block" style="margin-top:8px"><div class="money-field"><div class="money-label">WITHDRAW AMOUNT · USDT</div><input id="withdrawAmount" class="input money-input" type="number" step="0.01" min="0" value="0.40" placeholder="0.40"></div><div class="money-actions"><button type="button" class="btn stop" id="withdrawBtn">WITHDRAW</button></div></div><div class="row" style="margin-top:8px;align-items:end"><div class="money-field"><div class="money-label">PROFIT TARGET · %</div><input id="profit" class="input" type="number" step="0.01" value="0.41"></div><label style="padding:10px"><input id="reinvest" type="checkbox" checked> Reinvest</label></div>'
if old_controls not in html:
    raise RuntimeError('Expected allocation control block was not found')
html=html.replace(old_controls,new_controls,1)

old_withdraw="async function withdrawClick(){try{const a=Number($('allocation').value);if(!Number.isFinite(a)||a<=0)throw Error('Enter withdrawal amount');state=await request('/api/withdraw','POST',{amount:a});$('msg').textContent='Withdrawn to Reserve: '+num(a)+' USDT';$('allocation').value='';render()}catch(e){$('msg').textContent=e.message}}"
new_withdraw="async function withdrawClick(){try{const a=Number($('withdrawAmount').value);if(!Number.isFinite(a)||a<=0)throw Error('Enter withdrawal amount');state=await request('/api/withdraw','POST',{amount:a});$('msg').textContent='Withdrawn to Reserve: '+num(a)+' USDT';$('withdrawAmount').value='';render()}catch(e){$('msg').textContent=e.message}}"
if old_withdraw not in html:
    raise RuntimeError('Expected withdrawal handler was not found')
html=html.replace(old_withdraw,new_withdraw,1)

old_render="function render(){const m=state.mode||'PAPER';$('paperBtn').className='btn mode'+(m==='PAPER'?' active':'');$('testModeBtn').className='btn mode'+(m==='BINANCE_TEST'?' test-active':'');$('account').textContent=num(state.account);$('bot').textContent=num(state.bot_balance);$('reserve').textContent=num(state.reserve);$('sp').textContent=num(state.session_realized);$('tim').textContent='SESSION '+clock(state.session_age)+' · 24H '+clock(state.day_age);const p=state.positions||[];$('pos').innerHTML=p.length?p.map(x=>`<div class=\"line\">${x.symbol} · ${num(x.stake)} USDT · ${num(x.current)}</div>`).join(''):'No open positions';$('closed').innerHTML=(state.closed||[]).slice(0,5).map(x=>`<div class=\"line\">${x.symbol} · ${x.reason} · ${num(x.pnl)} USDT · ${num(x.exit)}</div>`).join('')||'No closed trades';$('radar').innerHTML=(state.ranking||[]).slice(0,15).map((x,i)=>`<div class=\"rank\"><b>${i+1}</b><b>${x.symbol}</b><span>${num(x.price)}</span><span>${num(x.score)}</span><button type=\"button\" class=\"btn add-radar\" data-symbol=\"${x.symbol}\">${(state.slots||[]).includes(x.symbol)?'IN SLOTS':'ADD PAIR'}</button></div>`).join('')||'Radar waiting for data';document.querySelectorAll('.add-radar').forEach(b=>b.addEventListener('click',()=>addRadarPair(b.dataset.symbol)))}"
new_render="function render(){const m=state.mode||'PAPER';$('paperBtn').className='btn mode'+(m==='PAPER'?' active':'');$('testModeBtn').className='btn mode'+(m==='BINANCE_TEST'?' test-active':'');$('account').textContent=num(state.account);$('bot').textContent=num(state.bot_balance);$('reserve').textContent=num(state.reserve);$('sp').textContent=num(state.session_realized);$('tim').textContent='SESSION '+clock(state.session_age)+' · 24H '+clock(state.day_age);const p=(state.positions||[]).slice().sort((a,b)=>(Number(a.slot??999)-Number(b.slot??999)));$('pos').innerHTML=p.length?p.map(x=>{const d=(Number(x.current||0)/Number(x.entry||x.current||1)-1)*100;const age=Math.max(0,Math.floor(Date.now()/1000-Number(x.opened||Date.now()/1000)));const qty=x.qty!=null?Number(x.qty).toFixed(4):'—';return `<div class=\"pos-line\"><span class=\"pos-main\">${x.symbol} · ${qty} · ${num(x.stake)} USDT · Δ ${d>=0?'+':''}${d.toFixed(3)}%</span><span class=\"pos-timer\">${clock(age)}</span></div>`}).join(''):'No open positions';const reasonMap={TIMEOUT:'T.OUT',PROFIT_TARGET:'P.T',ROTATION:'ROT',EMERGENCY_STOP:'E.STOP',BOT_OFF:'B.OFF'};$('closed').innerHTML=(state.closed||[]).slice(0,5).map(x=>{const pnl=Number(x.pnl||0);const r=reasonMap[x.reason]||x.reason||'—';const ts=x.closed_at?Number(x.closed_at):0;const t=ts?new Date(ts*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'--:--';return `<div class=\"line trade-line ${pnl>=0?'profit-pos':'profit-neg'}\">${x.symbol} · ${r} · ${pnl>=0?'+':''}${pnl.toFixed(4)} · ${Number(x.stake||0).toFixed(2)} USDT · ${num(x.entry)}→${num(x.exit)} · ${t}</div>`}).join('')||'No closed trades';$('radar').innerHTML=(state.ranking||[]).slice(0,15).map((x,i)=>`<div class=\"rank\"><b>${i+1}</b><b>${x.symbol}</b><span>${num(x.price)}</span><span>${num(x.score)}</span><button type=\"button\" class=\"btn add-radar\" data-symbol=\"${x.symbol}\">${(state.slots||[]).includes(x.symbol)?'IN SLOTS':'ADD PAIR'}</button></div>`).join('')||'Radar waiting for data';document.querySelectorAll('.add-radar').forEach(b=>b.addEventListener('click',()=>addRadarPair(b.dataset.symbol)))}"
if old_render not in html:
    raise RuntimeError('Expected render function was not found')
html=html.replace(old_render,new_render,1)

# Before TOP-6 is explicitly selected, slots remain empty. This prevents the
# UI from presenting stale/phantom pairs as active slots after a reset.
old_load="async function load(){try{const next=await request('/api/state');state=next;if(!slotsDrawn)drawSlots();render();syncSlots()}catch(e){$('msg').textContent=e.message}}"
new_load="async function load(){try{const next=await request('/api/state');state=next;if(!slotsDrawn)drawSlots();render();syncSlots()}catch(e){$('msg').textContent=e.message}}"
if old_load not in html:
    raise RuntimeError('Expected load function was not found')
html=html.replace(old_load,new_load,1)

legacy.HTML=html
