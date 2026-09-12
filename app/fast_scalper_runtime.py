from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_core as core
from . import market_radar

ROTATION_POOL = core.ROTATION_POOL
TRADE_SLOTS = core.TRADE_SLOTS
DEFAULT_PROFIT = core.DEFAULT_PROFIT

legacy.MAX_SLOTS = ROTATION_POOL
legacy.S['slots'] = (list(legacy.S.get('slots', [])) + [None] * ROTATION_POOL)[:ROTATION_POOL]
legacy.S['profit'] = DEFAULT_PROFIT
legacy.S['reinvest'] = True
legacy.S['stop_requested'] = None
market_radar.STAGE3 = 20
market_radar.FINAL = 20
try:
    market_radar.RADAR.top_n = 20
except Exception:
    pass

class WithdrawBody(BaseModel):
    amount: float = 0.0

for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/api/withdraw' and 'POST' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.post('/api/withdraw')
async def withdraw_root(b: WithdrawBody):
    if legacy.S.get('running'):
        raise HTTPException(400, 'STOP the bot before WITHDRAW')
    amount = float(b.amount)
    if amount <= 0:
        raise HTTPException(400, 'Withdrawal amount must be greater than 0')
    free = float(legacy.S.get('free', 0.0))
    if amount > free + 1e-9:
        raise HTTPException(400, f'Withdrawal {amount:.4f} exceeds free bot balance {free:.4f}')
    legacy.S['free'] = max(0.0, free - amount)
    legacy.S['bot'] = max(0.0, float(legacy.S.get('bot', 0.0)) - amount)
    legacy.S['account'] = float(legacy.S.get('account', 0.0)) + amount
    legacy.refresh_reserve()
    return await legacy.state()

APPROVED_HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Fast Scalper Beta</title><style>
*{box-sizing:border-box}html,body{margin:0;background:#080e1b;color:#edf2ff;font-family:Arial,Helvetica,sans-serif}body{min-height:100vh}.wrap{max-width:720px;margin:0 auto;padding:18px 24px 36px}.head{margin:4px 0 18px}.head h1{font-size:29px;line-height:1.05;margin:0;font-weight:800;letter-spacing:-.5px}.bolt{font-size:38px;vertical-align:-4px;margin-right:8px}.sub{font-size:18px;color:#8d98b1;margin-top:7px}.card{background:#111a2d;border:1px solid #273653;border-radius:24px;padding:25px 25px 23px;margin:0 0 18px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}.metric{background:#0a1223;border-radius:17px;padding:18px;min-height:92px}.metric .k{font-size:18px;margin-bottom:5px}.metric .v{font-size:25px;font-weight:800}.modeRow{display:grid;grid-template-columns:1fr 166px;gap:14px;margin-top:17px}.row{display:flex;gap:14px;align-items:center;margin-top:14px}.input,.select{height:54px;background:#091122;border:1px solid #30405e;border-radius:15px;color:#edf2ff;padding:0 17px;font-size:18px;outline:none;min-width:0}.amount,.profit{flex:1}.btn{height:54px;border:0;border-radius:15px;padding:0 24px;color:#fff;font-weight:800;font-size:17px;background:#245b91;white-space:nowrap}.btn.green{background:#00a65a}.btn.red{background:#b52f45}.btn.gray{background:#273753}.note{font-size:17px;line-height:1.35;color:#9ba5ba;margin-top:0}.check{font-size:18px;display:flex;align-items:center;gap:9px;white-space:nowrap}.check input{width:27px;height:27px;accent-color:#1676e8}.mainBtns{display:flex;gap:14px}.mainBtns .btn:first-child{flex:1}.offRow{display:flex;align-items:center;gap:15px;margin-top:14px}.offRow .btn{width:147px}.session{font-size:17px;color:#9ba5ba}.sectionTitle{font-size:28px;font-weight:800;margin:0 0 18px}.slots{display:grid;grid-template-columns:1fr 1fr;gap:12px}.slot{height:52px;background:#091122;border:1px solid #30405e;border-radius:14px;color:#8d96a9;padding:0 16px;font-size:17px;width:100%}.pos{display:flex;flex-direction:column;gap:10px}.pitem{background:#0a1223;border-radius:14px;padding:12px 14px;font-size:14px}.empty{color:#8d96a9;font-size:17px}.status{color:#9ba5ba;font-size:14px;margin-top:8px;min-height:18px}@media(max-width:560px){.wrap{padding:18px 24px 32px}.modeRow{grid-template-columns:1fr 150px}.btn{padding:0 17px}.mainBtns{gap:12px}.mainBtns .btn{padding:0 15px}}
</style></head><body><div class="wrap">
<div class="head"><h1><span class="bolt">⚡</span>Fast Scalper Beta</h1><div class="sub">Version 0.01 REPAIR PAPER · Trading TF: 3m</div></div>
<section class="card"><div class="grid2"><div class="metric"><div class="k">Account Balance</div><div class="v" id="account">1850.0000</div></div><div class="metric"><div class="k">Bot Balance</div><div class="v" id="bot">0.0000</div></div><div class="metric"><div class="k">Reserve</div><div class="v" id="reserve">0.0000</div></div><div class="metric"><div class="k">Session PnL</div><div class="v" id="pnl">0.0000</div></div></div><div class="modeRow"><select id="mode" class="select"><option>PAPER</option><option>BINANCE_TEST</option></select><button class="btn" onclick="setMode()">SET MODE</button></div><div class="row"><button class="btn" onclick="testBinance()">TEST BINANCE</button></div><div class="note">PAPER and BINANCE_TEST are independent modes. TEST BINANCE checks the Testnet connection.</div></section>
<section class="card"><div class="row" style="margin-top:0"><input id="allocation" class="input amount" inputmode="decimal" placeholder="Bot Allocation, USDT"><button class="btn" onclick="setAllocation()">SET BOT BALANCE</button><input id="withdraw" class="input" style="width:145px" inputmode="decimal" placeholder="WITHDRAW"><button class="btn" onclick="withdraw()">WITHDRAW</button></div><div class="row"><input id="profit" class="input profit" inputmode="decimal" value="0.33"><label class="check"><input id="reinvest" type="checkbox" checked> Reinvest</label></div><div class="mainBtns row"><button class="btn green" onclick="startBot()">BOT ON · ACTIVE</button><button class="btn red" onclick="emergency()">EMERGENCY</button><button class="btn gray" onclick="resetBot()">RESET</button></div><div class="offRow"><button class="btn red" onclick="stopBot()">BOT OFF</button><div class="session" id="session">SESSION 00:00 · 24H 00:00</div></div><div class="status" id="status"></div></section>
<section class="card"><div class="sectionTitle">Rotation Pool · TOP-20</div><div class="slots" id="slots"></div></section><section class="card"><div class="sectionTitle">Open Positions</div><div class="pos" id="positions"><div class="empty">No open positions.</div></div></section></div>
<script>
const $=id=>document.getElementById(id);const api=async(path,opts={})=>{const r=await fetch(path,{cache:'no-store',headers:{'Content-Type':'application/json',...(opts.headers||{})},...opts});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.detail||d.error||('HTTP '+r.status));return d};function val(x){return Number(x||0).toFixed(4)}function age(s){s=Math.max(0,Math.floor(Number(s||0)));return String(Math.floor(s/3600)).padStart(2,'0')+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')}function msg(t){$('status').textContent=t||''}
async function refresh(){try{const s=await api('/api/state');$('account').textContent=val(s.account);$('bot').textContent=val(s.bot_balance);$('reserve').textContent=val(s.reserve);$('pnl').textContent=val(s.session_realized);$('mode').value=s.mode==='BINANCE_TEST'?'BINANCE_TEST':'PAPER';$('profit').value=Number(s.profit_pct??.33).toFixed(2);$('reinvest').checked=!!s.reinvest;$('session').textContent='SESSION '+age(s.session_age)+' · 24H '+age(s.day_age);renderSlots(s.slots||[]);renderPositions(s.positions||[]);if(s.error)msg(s.error)}catch(e){msg(e.message)}}
function renderSlots(a){const el=$('slots');el.innerHTML='';for(let i=0;i<20;i++){const x=document.createElement('input');x.className='slot';x.value=a[i]||'';x.placeholder='USDT pair';x.addEventListener('change',saveSlots);el.appendChild(x)}}let timer;function saveSlots(){clearTimeout(timer);timer=setTimeout(async()=>{try{const a=[...document.querySelectorAll('.slot')].map(x=>x.value.trim().toUpperCase()).filter(Boolean);await api('/api/slots',{method:'POST',body:JSON.stringify({slots:a,profit_pct:Number($('profit').value.replace(',','.'))||.33,reinvest:$('reinvest').checked})};msg('Rotation Pool saved')}catch(e){msg(e.message)}},250)}
function renderPositions(a){const el=$('positions');if(!a.length){el.innerHTML='<div class="empty">No open positions.</div>';return}el.innerHTML=a.map(p=>`<div class="pitem"><b>${p.symbol}</b> · stake ${val(p.stake)} · PnL ${val(p.delta_usdt)} · age ${age(p.age_seconds)}</div>`).join('')}
async function setMode(){try{await api('/api/mode',{method:'POST',body:JSON.stringify({mode:$('mode').value})});msg('Mode set');await refresh()}catch(e){msg(e.message)}}async function testBinance(){try{const d=await api('/api/test-binance',{method:'POST'});msg(d.message||'Binance Testnet connection OK')}catch(e){msg(e.message)}}async function setAllocation(){try{await api('/api/allocation',{method:'POST',body:JSON.stringify({amount:Number($('allocation').value.replace(',','.'))})});msg('Bot balance set');await refresh()}catch(e){msg(e.message)}}async function withdraw(){try{await api('/api/withdraw',{method:'POST',body:JSON.stringify({amount:Number($('withdraw').value.replace(',','.'))})});$('withdraw').value='';msg('Withdraw completed');await refresh()}catch(e){msg(e.message)}}async function startBot(){try{await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:Number($('profit').value.replace(',','.'))||0,reinvest:$('reinvest').checked})});msg('Bot active');await refresh()}catch(e){msg(e.message)}}async function stopBot(){try{await api('/api/paper/stop',{method:'POST'});msg('Bot OFF — new entries stopped');await refresh()}catch(e){msg(e.message)}}async function emergency(){try{await api('/api/paper/emergency',{method:'POST'});msg('Emergency stop completed');await refresh()}catch(e){msg(e.message)}}async function resetBot(){try{await api('/api/reset',{method:'POST'});msg('Reset completed');await refresh()}catch(e){msg(e.message)}}refresh();setInterval(refresh,1000);
</script></body></html>'''

for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/' and 'GET' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.get('/', response_class=HTMLResponse)
async def approved_home():
    response = HTMLResponse(APPROVED_HTML)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

class ModeBody(BaseModel):
    mode: str
for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/api/mode' and 'POST' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)
@legacy.app.post('/api/mode')
async def mode_root(b: ModeBody):
    mode = str(b.mode).upper().strip()
    if mode not in {'PAPER', 'BINANCE_TEST'}: raise HTTPException(400, 'Unsupported mode')
    if legacy.S.get('running'): raise HTTPException(400, 'STOP the bot before changing mode')
    legacy.S['mode'] = mode
    return await legacy.state()

for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/api/test-binance' and 'POST' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)
@legacy.app.post('/api/test-binance')
async def test_binance_root():
    try:
        await legacy.B.ping()
        return {'ok': True, 'message': 'Binance Testnet connection OK' if legacy.B.testnet else 'Binance API connection OK'}
    except Exception as e:
        raise HTTPException(400, f'Binance test failed: {type(e).__name__}: {e}')

print('FAST_SCALPER_SINGLE_RUNTIME APPROVED_UI=1 ROTATION_POOL=20 TRADE_SLOTS=10 TP_DEFAULT=0.33 WITHDRAW=1 NO_CACHE=1', flush=True)
