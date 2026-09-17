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
    if getattr(r,'path',None) in {'/','/api/state','/api/slots','/api/auto-top','/api/add-to-slot','/api/withdraw','/api/mode','/api/test-binance'}:
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
    candidates=[normalize_symbol(x.get('symbol')) for x in rank]
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
*{box-sizing:border-box}html,body{margin:0;background:#07101e;color:#eef3ff;font-family:Arial,Helvetica,sans-serif;overflow-x:hidden}body{min-width:320px}.wrap{max-width:760px;margin:auto;padding:12px 14px 28px}.head{margin:0 0 12px}.brand{display:flex;gap:8px;align-items:flex-start}.bolt{font-size:37px;line-height:.9}.brand h1{margin:0;font-size:27px;line-height:1.05}.sub{margin-top:5px;color:#9aa6bd;font-size:13px;white-space:nowrap;overflow:hidden}.topbar{position:absolute;right:14px;top:14px}.online{background:#062d25;color:#00d47a;border-radius:8px;padding:5px 7px;font-size:10px;font-weight:800}.gear{margin-left:7px;color:#9eabc4;font-size:20px}.card{background:#101b2f;border:1px solid #29405f;border-radius:19px;padding:13px;margin-bottom:11px;overflow:hidden}.stats{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric{background:#091326;border-radius:13px;padding:10px 11px;min-width:0}.k{font-size:12px;color:#dbe3f3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.v{font-size:18px;font-weight:800;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.unit{font-size:10px;color:#95a3bc;font-weight:400}.modes{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px;margin-top:9px}.btn{height:42px;border:0;border-radius:11px;color:#fff;background:#1763a9;font-size:11px;font-weight:800;padding:0 8px;cursor:pointer;min-width:0}.paper{background:#293b5a}.green{background:#00a85b}.red{background:#cb3049}.gray{background:#293a58}.note,.summary,.hint{color:#99a5bd;font-size:11px;margin-top:7px}.control1{display:grid;grid-template-columns:1fr 1fr .72fr .72fr;gap:7px}.input{height:42px;width:100%;background:#091326;border:1px solid #304767;border-radius:11px;color:#eef3ff;padding:0 10px;font-size:15px;outline:none;min-width:0}.profit{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;margin-top:8px}.check{display:flex;align-items:center;gap:5px;font-size:13px;white-space:nowrap}.check input{width:19px;height:19px;accent-color:#1682ee}.actions{display:grid;grid-template-columns:1.45fr 1.15fr .8fr;gap:7px;margin-top:8px}.off{display:flex;align-items:center;gap:8px;margin-top:7px}.off .btn{width:85px;height:36px}.session{font-size:11px;color:#9aa6bd;white-space:nowrap}.status{min-height:15px;color:#9aa6bd;font-size:11px;margin-top:4px}.sectionHead,.slotHead,.collapseHead{display:flex;justify-content:space-between;align-items:center;gap:8px}.title{font-size:20px;font-weight:800;line-height:1.05}.badge{background:#c52f47;border-radius:8px;padding:4px 6px;font-size:8px;font-weight:800;white-space:nowrap}.empty{color:#8e9ab1;font-size:12px;margin-top:7px}.tradeitem{font-size:11px;color:#cbd5e7;padding:7px 2px;border-bottom:1px solid #2b405d;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.collapseHead{cursor:pointer}.collapseBtn{height:32px;border:1px solid #304767;border-radius:8px;background:#091326;color:#eef3ff;padding:0 9px;font-size:10px;font-weight:800}.pool{margin-top:9px;max-height:520px;overflow:auto}.rowline{display:grid;grid-template-columns:23px minmax(70px,1fr) 62px 50px 45px 70px;gap:5px;align-items:center;padding:6px 2px;border-bottom:1px solid #263a57;font-size:9px}.pair{font-weight:800}.muted{color:#94a1b8}.addbtn{height:27px;border:0;border-radius:7px;background:#245b91;color:#fff;font-size:8px;font-weight:800;padding:0 5px;cursor:pointer}.auto{font-size:10px;color:#a4afc2;font-weight:800;display:flex;align-items:center;gap:5px}.auto input{width:18px;height:18px;accent-color:#1682ee}.slots{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:9px}.slotbox{display:grid;grid-template-columns:23px 1fr;gap:5px;align-items:center}.slotnum{font-size:9px;color:#75839c;text-align:center}.slot{height:39px;background:#091326;border:1px solid #304767;border-radius:10px;color:#edf3ff;padding:0 8px;font-size:12px;width:100%;min-width:0;outline:none}.slot:disabled{opacity:.8}.slotActions{display:flex;gap:7px;margin-top:8px}.slotActions .btn{height:36px}.slotActions .btn:first-child{flex:1}@media(max-width:520px){.online{display:none}.control1{grid-template-columns:1fr 1fr}.rowline{grid-template-columns:22px minmax(58px,1fr) 55px 44px 40px 62px;font-size:8px}.addbtn{font-size:7px}.title{font-size:19px}}
</style></head><body><div class="topbar"><span class="online">● ONLINE</span><span class="gear">⚙</span></div><main class="wrap"><header class="head"><div class="brand"><span class="bolt">⚡</span><div><h1>Fast Scalper Beta</h1><div class="sub">Version 0.01 REPAIR PAPER · Trading TF: 3m</div></div></div></header>
<section class="card"><div class="stats"><div class="metric"><div class="k">Account Balance</div><div class="v"><span id="account">1850.0000</span> <span class="unit">USDT</span></div></div><div class="metric"><div class="k">Bot Balance</div><div class="v"><span id="bot">150.0000</span> <span class="unit">USDT</span></div></div><div class="metric"><div class="k">Reserve</div><div class="v"><span id="reserve">1700.0000</span> <span class="unit">USDT</span></div></div><div class="metric"><div class="k">Session PnL</div><div class="v"><span id="pnl">0.0000</span> <span class="unit">USDT</span></div></div></div><div class="modes"><button class="btn paper" onclick="setMode('PAPER')">PAPER</button><button class="btn" onclick="setMode('BINANCE_TEST')">BINANCE TEST</button><button class="btn" onclick="testBinance()">TEST BINANCE</button></div><div class="note" id="note">AUTO TOP-10 active</div></section>
<section class="card"><div class="control1"><input id="allocation" class="input" inputmode="decimal" value="150"><button class="btn" onclick="setAllocation()">SET BOT BALANCE</button><input id="withdraw" class="input" inputmode="decimal" placeholder="USDT"><button class="btn red" onclick="withdraw()">WITHDRAW</button></div><div class="profit"><input id="profit" class="input" inputmode="decimal" value="0.33"><label class="check"><input id="reinvest" type="checkbox" checked> Reinvest</label></div><div class="actions"><button class="btn green" onclick="startBot()">BOT ON · ACTIVE</button><button class="btn red" onclick="emergency()">EMERGENCY</button><button class="btn gray" onclick="resetBot()">RESET</button></div><div class="off"><button class="btn red" onclick="stopBot()">BOT OFF</button><div class="session" id="session">SESSION 00:00 · 24H 00:00</div></div><div class="status" id="status"></div></section>
<section class="card"><div class="sectionHead"><div class="title">Open Positions</div><div id="badge" class="badge">BOT OFF · TRADING STOPPED</div></div><div id="positions"><div class="empty">No open positions</div></div></section>
<section class="card"><div class="sectionHead"><div class="title">Closed Trades</div><div id="closedCount" class="summary">0</div></div><div id="closedSummary" class="summary">No closed trades</div></section>
<section class="card"><div class="title">Last Ten</div><div id="lastTen"><div class="empty">No closed trades</div></div></section>
<section class="card"><div class="slotHead"><div class="title">Slots · TOP-10</div><label class="auto">AUTO TOP-10 <input id="autoTop" type="checkbox" checked onchange="toggleAuto()"></label></div><div class="slots" id="slots"></div><div class="slotActions"><button class="btn" onclick="addTop10()">ADD TOP 10</button><button class="btn gray" onclick="clearSlots()">CLEAR</button></div><div class="hint">AUTO ON fills free slots from current leaders. Turn it OFF to edit slots manually.</div></section>
<section class="card"><div class="collapseHead" onclick="toggleRadar()"><div class="title">Radar · Rotation Pool · TOP-20</div><button class="collapseBtn" id="radarBtn">EXPAND</button></div><div id="radarBody" style="display:none"><div class="pool" id="pool"></div></div></section></main>
<script>
const $=id=>document.getElementById(id),num=x=>Number(x||0).toFixed(4),age=s=>{s=Math.max(0,Math.floor(Number(s||0)));return String(Math.floor(s/3600)).padStart(2,'0')+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')},api=async(p,o={})=>{const r=await fetch(p,{cache:'no-store',headers:{'Content-Type':'application/json'},...o});let d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.detail||d.error||('HTTP '+r.status));return d},msg=t=>{$('status').textContent=t||''};let ranking=[],radarOpen=false;
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function refresh(){try{const s=await api('/api/state');$('account').textContent=num(s.account);$('bot').textContent=num(s.bot_balance);$('reserve').textContent=num(s.reserve);$('pnl').textContent=num(s.session_realized);$('profit').value=Number(s.profit_pct??.33).toFixed(2);$('reinvest').checked=!!s.reinvest;$('autoTop').checked=!!s.auto_top;$('note').textContent=s.auto_top?'AUTO TOP-10 active':'MANUAL TOP-10 active';$('session').textContent='SESSION '+age(s.session_age)+' · 24H '+age(s.day_age);$('badge').textContent=s.running?'BOT ON · ACTIVE':'BOT OFF · TRADING STOPPED';ranking=s.ranking||[];renderPositions(s.positions||[]);renderClosed(s.closed||[]);renderLastTen(s.closed||[]);renderSlots(s.slots||[]);if(radarOpen)renderRadar();if(s.error)msg(s.error)}catch(e){msg(e.message)}}
function renderPositions(a){$('positions').innerHTML=a.length?a.map(p=>'<div class="tradeitem"><b>'+esc(p.symbol)+'</b> · '+num(p.stake)+' USDT · PnL '+num(p.delta_usdt)+' USDT · '+age(p.age_seconds)+'</div>').join(''):'<div class="empty">No open positions</div>'}
function renderClosed(a){$('closedCount').textContent=String(a.length);$('closedSummary').textContent=a.length?'Closed: '+a.length+' · PnL: '+num(a.reduce((v,x)=>v+Number(x.pnl||0),0))+' USDT':'No closed trades'}
function renderLastTen(a){$('lastTen').innerHTML=a.length?a.slice(0,10).map((p,i)=>'<div class="tradeitem"><b>'+String(i+1).padStart(2,'0')+' · '+esc(p.symbol)+'</b> · '+num(p.stake)+' USDT · PnL '+num(p.pnl)+' USDT · '+esc(p.reason||'CLOSED')+'</div>').join(''):'<div class="empty">No closed trades</div>'}
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
refresh();setInterval(refresh,1000);
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

@legacy.app.post('/api/withdraw')
async def withdraw(b:WithdrawBody):
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before WITHDRAW')
    amount=float(b.amount)
    if amount<=0: raise HTTPException(400,'Withdrawal amount must be greater than 0')
    free=float(legacy.S.get('free',0))
    if amount>free+1e-9: raise HTTPException(400,f'Withdrawal {amount:.4f} exceeds free bot balance {free:.4f}')
    legacy.S['free']=free-amount;legacy.S['bot']=max(0,float(legacy.S.get('bot',0))-amount);legacy.S['account']=float(legacy.S.get('account',0))+amount;legacy.refresh_reserve();return state_payload()

@legacy.app.post('/api/mode')
async def mode(b:ModeBody):
    m=str(b.mode).upper().strip()
    if m not in {'PAPER','BINANCE_TEST'}: raise HTTPException(400,'Unsupported mode')
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before changing mode')
    legacy.S['mode']=m;return state_payload()

@legacy.app.post('/api/test-binance')
async def test_binance():
    try: await legacy.B.ping();return {'ok':True,'message':'Binance Testnet connection OK' if legacy.B.testnet else 'Binance API connection OK'}
    except Exception as e: raise HTTPException(400,f'Binance test failed: {type(e).__name__}: {e}')

print('FAST_SCALPER_SINGLE_RUNTIME APPROVED_UI=1 ROTATION_POOL=20 TRADE_SLOTS=10 TP_DEFAULT=0.33 AUTO_TOP=1 SLOT_EDIT=1 RADAR_ROTATION_COLLAPSED=1 LAST_TEN=1',flush=True)