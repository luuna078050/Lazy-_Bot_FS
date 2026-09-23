from __future__ import annotations
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_core as core
from . import market_radar

ROTATION_POOL=20
TRADE_SLOTS=10
DEFAULT_PROFIT=0.33
legacy.MAX_SLOTS=ROTATION_POOL
legacy.S['slots']=(list(legacy.S.get('slots',[]))+[None]*ROTATION_POOL)[:ROTATION_POOL]
legacy.S['profit']=DEFAULT_PROFIT
legacy.S['reinvest']=True
legacy.S['auto_top']=True
market_radar.STAGE3=20
market_radar.FINAL=20
try: market_radar.RADAR.top_n=20
except Exception: pass

class WithdrawBody(BaseModel): amount:float=0.0
class ModeBody(BaseModel): mode:str
class SlotsBody(BaseModel): slots:list[str]=[]; profit_pct:float=DEFAULT_PROFIT; reinvest:bool=True; auto_top:bool=False
class AutoBody(BaseModel): enabled:bool
class AddBody(BaseModel): symbol:str

for r in list(legacy.app.router.routes):
    if getattr(r,'path',None) in {'/','/api/state','/api/slots','/api/auto-top','/api/add-to-slot','/api/position/close','/api/withdraw','/api/mode','/api/test-binance'}:
        legacy.app.router.routes.remove(r)

def normalize_symbol(s):
    s=str(s or '').strip().upper().replace('/','')
    return s if s.endswith('USDT') and len(s)>4 else ''

def occupied_slots():
    return {int(p.get('slot')):p.get('symbol') for p in legacy.S.get('positions',[]) if p.get('slot') is not None}

def apply_auto_top():
    if not legacy.S.get('auto_top'): return
    rank=legacy.S.get('ranking',[])[:ROTATION_POOL]
    occ=occupied_slots()
    out=[None]*ROTATION_POOL
    used=set()
    for i,s in occ.items():
        if 0<=i<ROTATION_POOL:
            out[i]=s; used.add(s)
    # Only confirmed BUY candidates are execution candidates.
    candidates=[normalize_symbol(x.get('symbol')) for x in rank if x.get('entry_allowed')]
    candidates=[s for s in candidates if s and s not in used]
    for i in range(TRADE_SLOTS):
        if out[i] is None and candidates:
            out[i]=candidates.pop(0); used.add(out[i])
    legacy.S['slots']=out

def state_payload():
    apply_auto_top()
    import time
    s=legacy.S
    now=time.time()
    positions=[]
    for p in s.get('positions',[]):
        q=dict(p); entry=float(q.get('entry') or 0); cur=float(q.get('current') or entry)
        q['age_seconds']=int(max(0,now-float(q.get('opened') or now)))
        q['delta_usdt']=(cur/entry-1)*float(q.get('stake') or 0) if entry else 0.0
        positions.append(q)
    return {'version':legacy.VERSION,'running':s.get('running',False),'mode':s.get('mode'),'account':s.get('account',0),'bot_balance':s.get('bot',0),'free':s.get('free',0),'reserve':s.get('reserve',0),'realized':s.get('realized',0),'session_realized':s.get('session_realized',0),'session_trades':s.get('session_trades',0),'positions':positions,'closed':s.get('closed',[])[:20],'orders':s.get('orders',[])[:20],'ranking':s.get('ranking',[])[:ROTATION_POOL],'slots':s.get('slots',[])[:ROTATION_POOL],'profit_pct':s.get('profit',DEFAULT_PROFIT),'reinvest':s.get('reinvest',True),'auto_top':s.get('auto_top',True),'cycle':s.get('cycle',0),'session_age':int(now-float(__import__('datetime').datetime.fromisoformat(s['session_started']).timestamp())) if s.get('session_started') else int(s.get('session_elapsed',0)),'day_age':int(now-__import__('datetime').datetime.fromisoformat(s['day_started']).timestamp()) if s.get('day_started') else 0,'error':s.get('error'),'binance_configured':legacy.B.configured,'binance_testnet':legacy.B.testnet,'live_enabled':legacy.B.live}

HTML=r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta http-equiv="Cache-Control" content="no-store"><title>Fast Scalper Beta</title><style>
*{box-sizing:border-box}html,body{margin:0;background:#080e1b;color:#edf2ff;font-family:Arial,Helvetica,sans-serif;overflow-x:hidden}body{min-width:320px}.wrap{width:100%;max-width:none;margin:0;padding:10px 25px 30px}.head{margin:0 0 14px}.brand{display:flex;align-items:flex-start;gap:8px}.bolt{font-size:47px;line-height:.9}.brand h1{margin:0;font-size:35px;font-weight:800;line-height:1.03;letter-spacing:-.7px}.sub{margin-top:6px;color:#8d98b1;font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.topbar{position:absolute;right:25px;top:14px}.online{background:#062d25;color:#00d47a;border-radius:8px;padding:5px 7px;font-size:10px;font-weight:800}.gear{margin-left:7px;color:#9eabc4;font-size:20px}.card{background:#111a2d;border:1px solid #273653;border-radius:24px;padding:18px 25px;margin-bottom:15px;overflow:hidden}.stats{display:grid;grid-template-columns:1fr 1fr;gap:14px}.metric{background:#0a1223;border-radius:17px;padding:15px 18px;min-height:91px;min-width:0}.k{font-size:20px;line-height:1.05;color:#d8e0f1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.v{font-size:29px;font-weight:800;margin-top:5px;white-space:nowrap;min-width:0;overflow:hidden;text-overflow:ellipsis}.unit{font-size:16px;color:#91a0ba;font-weight:400;margin-left:6px}.modes{display:grid;grid-template-columns:1fr 1fr 1.28fr;gap:12px;margin-top:15px}.btn{height:57px;border:0;border-radius:15px;color:#fff;background:#245b91;font-size:17px;font-weight:800;padding:0 10px;cursor:pointer;white-space:nowrap;min-width:0;overflow:hidden}.paper{background:#293954}.green{background:#00a65a}.red{background:#c52f47}.gray{background:#293954}.note,.summary,.hint{color:#9ba5ba;font-size:17px;margin-top:10px}.control1{display:grid;grid-template-columns:1.21fr 1fr 2.18fr 1fr;gap:14px;align-items:end;min-width:0}.input{height:54px;width:100%;background:#091122;border:1px solid #30405e;border-radius:15px;color:#edf2ff;padding:0 16px;font-size:20px;outline:none;min-width:0}.input::placeholder{color:#7e8798}.profit{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:end;margin-top:14px}.check{height:54px;display:flex;align-items:center;gap:9px;font-size:20px;white-space:nowrap}.check input{width:27px;height:27px;accent-color:#1676e8;flex:0 0 auto}.actions{display:grid;grid-template-columns:1.9fr 1.53fr 1fr;gap:10px;margin-top:14px}.actions .btn{height:57px}.off{display:flex;align-items:center;gap:14px;margin-top:12px;min-width:0}.off .btn{width:147px;flex:0 0 147px;height:57px}.session{font-size:18px;white-space:nowrap;overflow:hidden;color:#9ba5ba}.status{min-height:17px;color:#9ba5ba;font-size:14px;margin-top:5px}.sectionHead,.slotHead,.collapseHead{display:flex;justify-content:space-between;align-items:center;gap:8px}.title{font-size:38px;font-weight:800;line-height:1.03;letter-spacing:-.5px;margin:0 0 14px}.badge{display:inline-block;background:#c52f47;border-radius:14px;padding:7px 13px;font-size:13px;font-weight:800;margin-bottom:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.empty{color:#8d96a9;font-size:18px}.tradeitem{font-size:16px;color:#c8d2e7;padding:10px 4px;border-bottom:1px solid #30405e;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.collapseHead{cursor:pointer}.collapseBtn{height:42px;border:1px solid #304767;border-radius:12px;background:#091326;color:#eef3ff;padding:0 12px;font-size:12px;font-weight:800}.pool{margin-top:9px;max-height:520px;overflow:auto}.rowline{display:grid;grid-template-columns:23px minmax(70px,1fr) 62px 50px 45px 70px;gap:5px;align-items:center;padding:7px 2px;border-bottom:1px solid #30405e;font-size:10px;min-width:0}.rowline>*{min-width:0;overflow:hidden;text-overflow:ellipsis}.pair{font-weight:800}.muted{color:#94a1b8}.addbtn{height:32px;border:0;border-radius:9px;background:#245b91;color:#fff;font-size:9px;font-weight:800;padding:0 5px;cursor:pointer;white-space:nowrap;overflow:hidden}.auto{font-size:14px;color:#a4afc2;font-weight:800;display:flex;align-items:center;gap:7px;white-space:nowrap}.auto input{width:22px;height:22px;accent-color:#1682ee}.slots{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:9px}.slotbox{display:grid;grid-template-columns:27px 1fr;gap:7px;align-items:center}.slotnum{font-size:11px;color:#75839c;text-align:center}.slot{height:48px;background:#091122;border:1px solid #30405e;border-radius:13px;color:#edf2ff;padding:0 14px;font-size:16px;width:100%;min-width:0;outline:none}.slot:disabled{opacity:.8}.slotActions{display:flex;gap:10px;margin-top:12px}.slotActions .btn{height:50px}.slotActions .btn:first-child{flex:1}.posrow{display:flex;align-items:center;gap:8px;white-space:nowrap}.posrow b{min-width:0;overflow:hidden;text-overflow:ellipsis}.pplus{color:#18c878!important;font-weight:800}.pminus{color:#ef5264!important;font-weight:800}.summary .pplus{color:#18c878!important}.summary .pminus{color:#ef5264!important}.closepos{margin-left:auto;height:42px!important;min-width:88px!important;padding:0 10px!important;font-size:12px!important;flex:0 0 auto}@media(max-width:470px){.wrap{padding-left:18px;padding-right:18px}.topbar{right:18px}.brand h1{font-size:31px}.bolt{font-size:37px}.sub{font-size:17px}.metric{padding:13px}.k{font-size:18px}.v{font-size:27px}.unit{font-size:15px}.modes{gap:7px}.modes .btn{height:53px;font-size:15px;padding:0 5px}.control1{grid-template-columns:1fr 1fr;gap:7px}.input{height:50px;padding:0 10px;font-size:19px}.control1 .btn{height:50px;font-size:13px}.profit{gap:7px}.check{font-size:16px}.check input{width:22px;height:22px}.actions{gap:7px}.actions .btn{height:52px;font-size:13px}.off{gap:9px}.off .btn{width:115px;flex-basis:115px;height:50px;font-size:15px}.session{font-size:15px}.title{font-size:31px}.empty{font-size:18px}.tradeitem{font-size:16px}.rowline{grid-template-columns:20px minmax(58px,1fr) 52px 42px 40px 64px;gap:4px;font-size:8px}.addbtn{height:29px;font-size:8px}.auto{font-size:12px}.auto input{width:20px;height:20px}.slot{height:48px;font-size:16px}.slotActions .btn{height:48px;font-size:13px}.hint,.note,.summary{font-size:15px}.closepos{height:40px!important;min-width:72px!important;font-size:11px!important}}</style></head><body><div class="topbar"><span class="online">● ONLINE</span><span class="gear">⚙</span></div><main class="wrap"><header class="head"><div class="brand"><span class="bolt">⚡</span><div><h1>Fast Scalper Beta</h1><div class="sub">Version 0.01 REPAIR PAPER · Trading TF: 3m</div></div></div></header>
<section class="card"><div class="stats"><div class="metric"><div class="k">Account Balance</div><div class="v"><span id="account">1850.0000</span> <span class="unit">USDT</span></div></div><div class="metric"><div class="k">Bot Balance</div><div class="v"><span id="bot">150.0000</span> <span class="unit">USDT</span></div></div><div class="metric"><div class="k">Reserve</div><div class="v"><span id="reserve">1700.0000</span> <span class="unit">USDT</span></div></div><div class="metric"><div class="k">Session PnL</div><div class="v"><span id="pnl">0.0000</span> <span class="unit">USDT</span></div></div></div><div class="modes"><button class="btn paper" onclick="setMode('PAPER')">PAPER</button><button class="btn" onclick="setMode('BINANCE_TEST')">BINANCE TEST</button><button class="btn" onclick="testBinance()">TEST BINANCE</button></div><div class="note" id="note">AUTO TOP-10 active</div></section>
<section class="card"><div class="control1"><input id="allocation" class="input" inputmode="decimal" value="150"><button class="btn" onclick="setAllocation()">SET BOT BALANCE</button><input id="withdraw" class="input" inputmode="decimal" placeholder="USDT"><button class="btn red" onclick="withdraw()">WITHDRAW</button></div><div class="profit"><input id="profit" class="input" inputmode="decimal" value="0.33"><label class="check"><input id="reinvest" type="checkbox" checked> Reinvest</label></div><div class="actions"><button class="btn green" onclick="startBot()">BOT ON · ACTIVE</button><button class="btn red" onclick="emergency()">EMERGENCY</button><button class="btn gray" onclick="resetBot()">RESET</button></div><div class="off"><button class="btn red" onclick="stopBot()">BOT OFF</button><div class="session" id="session">SESSION 00:00 · 24H 00:00</div></div><div class="status" id="status"></div></section>
<section class="card"><div class="sectionHead"><div class="title">Open Positions</div><div id="badge" class="badge">BOT OFF · TRADING STOPPED</div></div><div id="positions"><div class="empty">No open positions</div></div></section>
<section class="card"><div class="sectionHead"><div class="title">Closed Trades</div><div id="closedCount" class="summary">0</div></div><div id="closedSummary" class="summary">No closed trades</div></section>
<section class="card"><div class="title">Last Five</div><div id="lastFive"><div class="empty">No closed trades</div></div></section>
<section class="card"><div class="slotHead"><div class="title">Slots · TOP-10</div><label class="auto">AUTO TOP-10 <input id="autoTop" type="checkbox" checked onchange="toggleAuto()"></label></div><div class="slots" id="slots"></div><div class="slotActions"><button class="btn" onclick="addTop10()">ADD TOP 10</button><button class="btn gray" onclick="clearSlots()">CLEAR</button></div><div class="hint">AUTO ON fills free slots from current leaders. Turn it OFF to edit slots manually.</div></section>
<section class="card"><div class="collapseHead" onclick="toggleRadar()"><div class="title">Radar · Rotation Pool · TOP-20</div><button class="collapseBtn" id="radarBtn">EXPAND</button></div><div id="radarBody" style="display:none"><div class="pool" id="pool"></div></div></section></main>
<script>
const $=id=>document.getElementById(id),num=x=>Number(x||0).toFixed(4),age=s=>{s=Math.max(0,Math.floor(Number(s||0)));return String(Math.floor(s/3600)).padStart(2,'0')+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')},api=async(p,o={})=>{const r=await fetch(p,{cache:'no-store',headers:{'Content-Type':'application/json'},...o});let d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.detail||d.error||('HTTP '+r.status));return d},msg=t=>{$('status').textContent=t||''};let ranking=[],radarOpen=false;
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function refresh(){try{const s=await api('/api/state');$('account').textContent=num(s.account);$('bot').textContent=num(s.bot_balance);$('reserve').textContent=num(s.reserve);$('pnl').textContent=num(s.session_realized);$('profit').value=Number(s.profit_pct??.33).toFixed(2);$('reinvest').checked=!!s.reinvest;$('autoTop').checked=!!s.auto_top;$('note').textContent=s.auto_top?'AUTO TOP-10 active':'MANUAL TOP-10 active';$('session').textContent='SESSION '+age(s.session_age)+' · 24H '+age(s.day_age);$('badge').textContent=s.running?'BOT ON · ACTIVE':'BOT OFF · TRADING STOPPED';ranking=s.ranking||[];renderPositions(s.positions||[]);renderClosed(s.closed||[]);renderLastFive(s.closed||[]);renderSlots(s.slots||[]);if(radarOpen)renderRadar();if(s.error)msg(s.error)}catch(e){msg(e.message)}}
function renderPositions(a){$('positions').innerHTML=a.length?a.map(p=>{const d=Number(p.delta_usdt||0);return '<div class="tradeitem posrow"><b>'+esc(p.symbol)+'</b> · '+num(p.stake)+' USDT · <span class="'+(d>=0?'pplus':'pminus')+'">PnL '+(d>=0?'+':'')+num(d)+' USDT</span> · '+age(p.age_seconds)+' <button type="button" class="btn red closepos" data-close-id="'+esc(p.id||'')+'" data-close-symbol="'+esc(p.symbol||'')+'">CLOSE</button></div>'}).join(''):'<div class="empty">No open positions</div>'}
function renderClosed(a){const total=a.reduce((v,x)=>v+Number(x.pnl||0),0);const cls=total>=0?'pplus':'pminus';$('closedCount').textContent=String(a.length);$('closedSummary').innerHTML=a.length?'Closed: '+a.length+' · <span class="'+cls+'">PnL: '+(total>=0?'+':'')+num(total)+' USDT</span>':'No closed trades'}
function renderLastFive(a){$('lastFive').innerHTML=a.length?a.slice(0,5).map((p,i)=>'<div class="tradeitem"><b>'+String(i+1).padStart(2,'0')+' · '+esc(p.symbol)+'</b> · '+num(p.stake)+' USDT · PnL '+num(p.pnl)+' USDT · '+esc(p.reason||'CLOSED')+'</div>').join(''):'<div class="empty">No closed trades</div>'}
function renderSlots(a){const selected=$('autoTop').checked?ranking.slice(0,10).map(x=>x.symbol):(a||[]).slice(0,10);const el=$('slots');el.innerHTML='';for(let i=0;i<10;i++){const box=document.createElement('div');box.className='slotbox';const n=document.createElement('span');n.className='slotnum';n.textContent=String(i+1).padStart(2,'0');const x=document.createElement('input');x.className='slot';x.placeholder='USDT pair';x.value=selected[i]||'';x.disabled=$('autoTop').checked;x.addEventListener('change',saveManualSlots);box.append(n,x);el.appendChild(box)}}
function renderRadar(){let h='<div class="rowline muted"><span>#</span><span>PAIR</span><span>SIGNAL</span><span>24H</span><span>SCORE</span><span>ACTION</span></div>';ranking.slice(0,20).forEach((x,i)=>h+='<div class="rowline"><span>'+String(i+1).padStart(2,'0')+'</span><span class="pair">'+esc(x.symbol)+'</span><span>'+esc(x.signal||'WAIT')+'</span><span>'+Number(x.change??x.change_24h_pct??0).toFixed(2)+'%</span><span>'+Number(x.score??x.entry_score??0).toFixed(1)+'</span><button class="addbtn" onclick="addToSlot(\''+esc(x.symbol)+'\')">ADD TO SLOT</button></div>');$('pool').innerHTML=ranking.length?h:'<div class="empty">Waiting for radar data…</div>'}
function toggleRadar(){radarOpen=!radarOpen;$('radarBody').style.display=radarOpen?'block':'none';$('radarBtn').textContent=radarOpen?'COLLAPSE':'EXPAND';if(radarOpen)renderRadar()}
async function toggleAuto(){try{await api('/api/auto-top',{method:'POST',body:JSON.stringify({enabled:$('autoTop').checked})});msg($('autoTop').checked?'AUTO TOP-10 enabled':'Manual TOP-10 enabled');await refresh()}catch(e){msg(e.message);await refresh()}}
async function saveManualSlots(){if($('autoTop').checked)return;try{const a=[...document.querySelectorAll('.slot')].map(x=>x.value.trim().toUpperCase()).filter(Boolean);await api('/api/slots',{method:'POST',body:JSON.stringify({slots:a,profit_pct:Number($('profit').value.replace(',','.'))||.33,reinvest:$('reinvest').checked,auto_top:false})});msg('Slots saved');await refresh()}catch(e){msg(e.message)}}
async function addTop10(){try{const a=ranking.slice(0,10).map(x=>x.symbol);if(a.length<10)throw Error('Radar has fewer than 10 pairs');await api('/api/slots',{method:'POST',body:JSON.stringify({slots:a,profit_pct:Number($('profit').value.replace(',','.'))||.33,reinvest:$('reinvest').checked,auto_top:false})});$('autoTop').checked=false;msg('TOP-10 added to slots');await refresh()}catch(e){msg(e.message)}}
async function addToSlot(s){try{await api('/api/add-to-slot',{method:'POST',body:JSON.stringify({symbol:s})});msg(s+' added to slot');await refresh()}catch(e){msg(e.message)}}
async function clearSlots(){try{$('autoTop').checked=false;await api('/api/slots',{method:'POST',body:JSON.stringify({slots:[],profit_pct:Number($('profit').value.replace(',','.'))||.33,reinvest:$('reinvest').checked,auto_top:false})});msg('Slots cleared');await refresh()}catch(e){msg(e.message)}}
async function setMode(m){try{await api('/api/mode',{method:'POST',body:JSON.stringify({mode:m})});msg('Mode set: '+m);await refresh()}catch(e){msg(e.message)}}
async function testBinance(){try{const d=await api('/api/test-binance',{method:'POST'});msg(d.message||'Binance Testnet connection OK')}catch(e){msg(e.message)}}
async function setAllocation(){try{await api('/api/allocation',{method:'POST',body:JSON.stringify({amount:Number($('allocation').value.replace(',','.'))})});msg('Bot balance set');await refresh()}catch(e){msg(e.message)}}
async function withdraw(){try{const a=Number($('withdraw').value.replace(',','.'));await api('/api/withdraw',{method:'POST',body:JSON.stringify({amount:a})});$('withdraw').value='';msg('Withdraw completed');await refresh()}catch(e){msg(e.message)}}
async function startBot(){try{await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:Number($('profit').value.replace(',','.'))||0,reinvest:$('reinvest').checked})});msg('Bot active');await refresh()}catch(e){msg(e.message)}}
async function stopBot(){try{await api('/api/paper/stop',{method:'POST'});msg('Bot OFF — new entries stopped');await refresh()}catch(e){msg(e.message)}}
async function emergency(){try{await api('/api/paper/emergency',{method:'POST'});msg('Emergency stop completed');await refresh()}catch(e){msg(e.message)}}
async function resetBot(){try{await api('/api/reset',{method:'POST'});msg('Reset completed');await refresh()}catch(e){msg(e.message)}}
document.addEventListener('click',async e=>{const b=e.target.closest('.closepos');if(!b)return;try{b.disabled=true;const d=await api('/api/position/close',{method:'POST',body:JSON.stringify({id:b.dataset.closeId,symbol:b.dataset.closeSymbol})});msg('Position closed');await refresh()}catch(err){msg(err.message)}finally{b.disabled=false}});refresh();setInterval(refresh,1000);
</script></body></html>'''

@legacy.app.get('/',response_class=HTMLResponse)
async def home():
    r=HTMLResponse(HTML);r.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0';r.headers['Pragma']='no-cache';return r

@legacy.app.get('/api/state')
async def state(): return state_payload()

@legacy.app.post('/api/slots')
async def slots(b:SlotsBody):
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before editing slots')
    arr=[]
    for x in b.slots[:TRADE_SLOTS]:
        s=normalize_symbol(x)
        if s and s not in arr: arr.append(s)
    occ=occupied_slots()
    for i,p in occ.items():
        if i<TRADE_SLOTS and i<len(arr) and arr[i]!=p: raise HTTPException(400,f'Slot {i+1} has an open position and is pinned to {p}')
    legacy.S['slots']=arr+[None]*(ROTATION_POOL-len(arr));legacy.S['profit']=float(b.profit_pct);legacy.S['reinvest']=bool(b.reinvest);legacy.S['auto_top']=bool(b.auto_top)
    return state_payload()

@legacy.app.post('/api/auto-top')
async def auto_top(b:AutoBody):
    if legacy.S.get('running') and not b.enabled: raise HTTPException(400,'STOP the bot before switching to manual slots')
    legacy.S['auto_top']=bool(b.enabled);apply_auto_top();return state_payload()

@legacy.app.post('/api/add-to-slot')
async def add_to_slot(b:AddBody):
    s=normalize_symbol(b.symbol)
    if not s: raise HTTPException(400,'Invalid USDT pair')
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before editing slots')
    legacy.S['auto_top']=False
    occ=occupied_slots(); arr=list(legacy.S.get('slots',[])[:TRADE_SLOTS])
    while len(arr)<TRADE_SLOTS: arr.append(None)
    idx=next((i for i,x in enumerate(arr) if not x),None)
    if idx is None: raise HTTPException(400,'All 10 slots are occupied')
    arr[idx]=s
    for i,p in occ.items():
        if i==idx: raise HTTPException(400,f'Slot {idx+1} is pinned to {p}')
    legacy.S['slots']=arr+[None]*ROTATION_POOL- len(arr) if False else arr+[None]*(ROTATION_POOL-len(arr))
    return state_payload()

@legacy.app.post('/api/position/close')
async def position_close_runtime(b:dict):
    ident=str(b.get('id') or '').strip()
    symbol=normalize_symbol(b.get('symbol'))
    target=next((p for p in legacy.S.get('positions',[]) if (ident and str(p.get('id'))==ident) or (symbol and normalize_symbol(p.get('symbol'))==symbol)),None)
    if target is None: raise HTTPException(404,'Open position not found')
    slot=target.get('slot')
    sym=normalize_symbol(target.get('symbol'))
    try: await legacy.close(target,'MANUAL_CLOSE')
    except Exception as e: raise HTTPException(502,f'Close {target.get("symbol")}: {type(e).__name__}: {e}')
    # Manual close releases the execution slot and blocks the same pair for 3 minutes.
    try:
        si=int(slot)
        slots=list(legacy.S.get('slots',[]))
        while len(slots)<ROTATION_POOL: slots.append(None)
        if 0 <= si < TRADE_SLOTS: slots[si]=None
        legacy.S['slots']=slots[:ROTATION_POOL]
    except (TypeError,ValueError):
        pass
    if sym: legacy.S.setdefault('pair_cooldown',{})[sym]=__import__('time').time()+180.0
    return state_payload()

@legacy.app.post('/api/withdraw')
async def withdraw(b:WithdrawBody):
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before WITHDRAW')
    amount=float(b.amount)
    if amount<=0: raise HTTPException(400,'Withdrawal amount must be greater than 0')
    free=float(legacy.S.get('free',0))
    if amount>free+1e-9: raise HTTPException(400,f'Withdrawal {amount:.4f} exceeds free bot balance {free:.4f}')
    legacy.S['free']=free-amount;legacy.S['bot']=max(0,float(legacy.S.get('bot',0))-amount);legacy.S['account']=float(legacy.S.get('account',0))+amount;legacy.refresh_reserve();return state_payload()

class SettingsBody(BaseModel):
    reinvest: bool
    profit_pct: float = DEFAULT_PROFIT

@legacy.app.post('/api/settings')
async def settings(b:SettingsBody):
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before changing session settings')
    legacy.S['reinvest']=bool(b.reinvest)
    legacy.S['profit']=float(b.profit_pct)
    return state_payload()

@legacy.app.post('/api/mode')
async def mode(b:ModeBody):
    m=str(b.mode).upper().strip()
    if m not in {'PAPER','BINANCE_TEST'}: raise HTTPException(400,'Unsupported mode')
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before changing mode')
    legacy.S['mode']=m;return state_payload()

@legacy.app.post('/api/test-binance')
async def test_binance():
    diag=legacy.B.diagnostics()
    try:
        if not legacy.B.configured:
            raise RuntimeError('Binance API credentials are not configured')
        if not legacy.B.testnet:
            raise RuntimeError('BINANCE_TEST requires Binance Testnet')
        await legacy.B.ping()
        acc=await legacy.B.account()
        free_usdt=next((float(x['free']) for x in acc.get('balances',[]) if x.get('asset')=='USDT'),0.0)
        if not legacy.S.get('running') and not legacy.S.get('positions'):
            legacy.S['account']=free_usdt
            legacy.S['bot']=0.0
            legacy.S['free']=0.0
            legacy.S['reserve']=free_usdt
        return {'ok':True,'message':'Binance Testnet signed account check OK','testnet':True,'configured':True,'free_usdt':free_usdt,'diagnostics':diag}
    except Exception as e:
        raise HTTPException(400,f'Binance test failed: {type(e).__name__}: {e} | DIAGNOSTICS: {diag}')

print('FAST_SCALPER_SINGLE_RUNTIME APPROVED_UI=1 ROTATION_POOL=20 TRADE_SLOTS=10 TP_DEFAULT=0.33 AUTO_TOP=1 SLOT_EDIT=1 RADAR_ROTATION_COLLAPSED=1 LAST_FIVE=1',flush=True)
print(f'BINANCE_CONFIGURED={legacy.B.configured} BINANCE_TESTNET={legacy.B.testnet} LIVE_ENABLED={legacy.B.live}',flush=True)