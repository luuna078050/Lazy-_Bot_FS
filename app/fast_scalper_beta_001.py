from . import fast_scalper_beta_001_legacy as legacy
from fastapi import HTTPException

app = legacy.app
S = legacy.S
B = legacy.B
START = legacy.START

async def mode_fixed(b: legacy.Mode):
    m = b.mode.upper()
    if m not in {'PAPER', 'BINANCE_TEST'}:
        raise HTTPException(403, 'Unsupported mode')
    if S['running'] or S['positions']:
        raise HTTPException(400, 'BOT OFF and no open positions required')
    S['mode'] = m
    S['bot'] = 0.0
    S['free'] = 0.0
    S['error'] = None
    if m == 'PAPER':
        S['account'] = START
        S['reserve'] = START
    else:
        S['account'] = 0.0
        S['reserve'] = 0.0
        try:
            await B.ping()
            a = await B.account()
            u = next((float(x['free']) for x in a.get('balances', []) if x.get('asset') == 'USDT'), 0.0)
            S['account'] = u
            S['reserve'] = u
        except Exception as e:
            S['error'] = f'Binance TEST: {e}'
    return await legacy.state()

for r in app.router.routes:
    if getattr(r, 'path', None) == '/api/mode' and getattr(r, 'methods', None):
        r.endpoint = mode_fixed
        if hasattr(r, 'dependant'):
            r.dependant.call = mode_fixed

@app.post('/api/radar')
async def radar_endpoint():
    await legacy.radar(True)
    return await legacy.state()

@app.post('/api/withdraw')
async def withdraw_endpoint(b: dict):
    if S['running'] or S['positions']:
        raise HTTPException(400, 'BOT OFF and no open positions required')
    try:
        amount = float(b.get('amount', 0))
    except Exception:
        raise HTTPException(400, 'Enter withdrawal amount')
    if amount <= 0:
        raise HTTPException(400, 'Enter withdrawal amount')
    bot = float(S.get('bot', 0.0) or 0.0)
    available = max(0.0, bot)
    if amount > available + 1e-9:
        raise HTTPException(400, f'Withdraw amount exceeds Bot Balance ({available:.4f} USDT)')
    S['bot'] = max(0.0, bot - amount)
    S['free'] = S['bot']
    S['reserve'] = max(0.0, float(S.get('account', 0.0) or 0.0) - S['bot'])
    S['error'] = None
    return await legacy.state()

legacy.HTML = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Cache-Control" content="no-cache,no-store,must-revalidate"><meta http-equiv="Pragma" content="no-cache"><meta http-equiv="Expires" content="0"><title>Fast Scalper Beta</title><style>*{box-sizing:border-box}body{margin:0;background:#080e1b;color:#eef3ff;font-family:system-ui}.w{max-width:900px;margin:auto;padding:14px}.title{font-size:30px;font-weight:900}.muted{color:#8b97ae}.card{background:#121a2c;border:1px solid #293650;border-radius:16px;padding:14px;margin:10px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.stat{background:#0d1425;border-radius:10px;padding:10px}.v{font-size:19px;font-weight:850}.row{display:flex;gap:8px;flex-wrap:wrap}.input,.select,.slot{background:#0b1322;color:#fff;border:1px solid #30405f;border-radius:9px;padding:10px;flex:1;min-width:120px}.amount{flex:0 0 150px;max-width:150px}.btn{border:0;border-radius:10px;padding:11px 15px;color:#fff;font-weight:850;background:#273650;cursor:pointer}.on{background:#078b53}.stop{background:#a72e3f}.test{background:#183b66}#allocBtn,#withdrawBtn{font-size:14px;padding:10px 12px}.grid6{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.rank{display:grid;grid-template-columns:22px 1fr 65px 50px;gap:5px;padding:5px;border-bottom:1px solid #24314a;font-size:9px}.line{font-size:12px;padding:4px 0;border-bottom:1px solid #24314a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}@media(max-width:650px){.stats{grid-template-columns:repeat(2,1fr)}.grid6{grid-template-columns:repeat(2,1fr)}.amount{flex:0 0 150px;max-width:150px}}</style></head><body><div class="w"><div class="title">⚡ Fast Scalper Beta</div><div class="muted">Version 0.01 REPAIR PAPER · Trading TF: 3m</div><div class="card"><div class="stats"><div class="stat">Account Balance<div class="v" id="account">—</div></div><div class="stat">Bot Balance<div class="v" id="bot">—</div></div><div class="stat">Reserve<div class="v" id="reserve">—</div></div><div class="stat">Session PnL<div class="v" id="sp">—</div></div></div><div class="row" style="margin-top:10px"><select id="modeSel" class="select"><option value="PAPER">PAPER</option><option value="BINANCE_TEST">BINANCE_TEST</option></select><button type="button" class="btn test" id="modeBtn">SET MODE</button><button type="button" class="btn test" id="testBtn">TEST BINANCE</button></div><div id="msg" class="muted" style="margin-top:8px"></div></div><div class="card"><div class="row"><input id="allocation" class="input amount" type="number" step="0.01" min="0" placeholder="Amount"><button type="button" class="btn test" id="allocBtn">SET BOT BALANCE</button><button type="button" class="btn stop" id="withdrawBtn">WITHDRAW</button><input id="profit" class="input" type="number" step="0.01" value="0.41"><label style="padding:10px"><input id="reinvest" type="checkbox" checked> Reinvest</label></div><div class="row" style="margin-top:8px"><button type="button" class="btn on" id="onBtn">BOT ON · ACTIVE</button><button type="button" class="btn stop" id="emBtn">EMERGENCY</button><button type="button" class="btn" id="resetBtn">RESET</button><button type="button" class="btn stop" id="offBtn">BOT OFF</button><span class="muted" id="tim">SESSION 00:00 · 24H 00:00</span></div></div><div class="card"><h2>Slots · TOP-6</h2><div class="grid6" id="slots"></div><div class="row" style="margin-top:10px"><button type="button" class="btn on" id="pairsBtn">SET PAIRS</button><button type="button" class="btn" id="addBtn">＋ ADD PAIR</button><button type="button" class="btn" id="topBtn">AUTO TOP-6</button></div></div><div class="card"><details open><summary>Radar · TOP-15 · recommended pairs</summary><div id="radar"></div></details></div><div class="card"><h2>Open Positions</h2><div id="pos" class="muted">No open positions</div></div><div class="card"><h2>Closed Trades — latest 5</h2><div id="closed" class="muted">No closed trades</div></div></div><script>
let state={};let slotsDrawn=false;const $=id=>document.getElementById(id);const profit=()=>Number($('profit').value)||0;const reinvest=()=>$('reinvest').checked;
async function request(path,method='GET',body){const r=await fetch(path,{method,cache:'no-store',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});let j={};try{j=await r.json()}catch(_){throw Error('Server returned invalid response')};if(!r.ok)throw Error(j.detail||JSON.stringify(j));return j}
function num(x){return Number(x||0).toFixed(4)}
function clock(x){x=Math.floor(x||0);return String(Math.floor(x/60)).padStart(2,'0')+':'+String(x%60).padStart(2,'0')}
function drawSlots(){const a=state.slots||[];$('slots').innerHTML=Array.from({length:6},(_,i)=>`<input type="text" class="slot" id="pair${i}" placeholder="USDT pair" value="${a[i]||''}">`).join('');slotsDrawn=true}
function syncSlots(){for(let i=0;i<6;i++){const e=$('pair'+i);if(e)e.value=(state.slots||[])[i]||''}}
function render(){ $('modeSel').value=state.mode||'PAPER';$('account').textContent=num(state.account);$('bot').textContent=num(state.bot_balance);$('reserve').textContent=num(state.reserve);$('sp').textContent=num(state.session_realized);$('tim').textContent='SESSION '+clock(state.session_age)+' · 24H '+clock(state.day_age);const p=state.positions||[];$('pos').innerHTML=p.length?p.map(x=>`<div class="line">${x.symbol} · ${num(x.stake)} USDT · ${num(x.current)}</div>`).join(''):'No open positions';$('closed').innerHTML=(state.closed||[]).slice(0,5).map(x=>`<div class="line">${x.symbol} · ${x.reason} · ${num(x.pnl)} USDT · ${num(x.exit)}</div>`).join('')||'No closed trades';$('radar').innerHTML=(state.ranking||[]).map((x,i)=>`<div class="rank"><b>${i+1}</b><b>${x.symbol}</b><span>${num(x.price)}</span><span>${num(x.score)}</span></div>`).join('')||'Radar waiting for data';}
async function load(){try{const old=state.mode;state=await request('/api/state');if(!slotsDrawn||old!==state.mode)drawSlots();render()}catch(e){$('msg').textContent=e.message}}
async function setModeClick(){try{state=await request('/api/mode','POST',{mode:$('modeSel').value});$('msg').textContent='';render();syncSlots()}catch(e){$('msg').textContent=e.message}}
async function testBinanceClick(){try{const x=await request('/api/binance/test','POST');const u=(x.balances||[]).find(v=>v.asset==='USDT');$('msg').textContent=x.account_checked?'Binance TEST signed account check OK':'Binance public ping OK';if(u)$('account').textContent=num(u.free);await load()}catch(e){$('msg').textContent=e.message}}
async function setAllocationClick(){try{const a=Number($('allocation').value);if(!Number.isFinite(a)||a<0)throw Error('Enter Bot Allocation');state=await request('/api/allocation','POST',{amount:a});$('msg').textContent='Bot balance set: '+num(state.bot_balance)+' USDT';render()}catch(e){$('msg').textContent=e.message}}
async function withdrawClick(){try{const a=Number($('allocation').value);if(!Number.isFinite(a)||a<=0)throw Error('Enter withdrawal amount');state=await request('/api/withdraw','POST',{amount:a});$('msg').textContent='Withdrawn to Reserve: '+num(a)+' USDT';$('allocation').value='';render()}catch(e){$('msg').textContent=e.message}}
async function startClick(){try{state=await request('/api/paper/start','POST',{profit_pct:profit(),reinvest:reinvest()});render()}catch(e){$('msg').textContent=e.message}}
async function offClick(){try{state=await request('/api/paper/stop','POST');$('msg').textContent='';render()}catch(e){$('msg').textContent=e.message}}
async function emergencyClick(){try{state=await request('/api/paper/emergency','POST');render()}catch(e){$('msg').textContent=e.message}}
async function resetClick(){try{state=await request('/api/reset','POST');drawSlots();render();syncSlots()}catch(e){$('msg').textContent=e.message}}
async function setPairsClick(){try{const a=Array.from({length:6},(_,i)=>$('pair'+i).value.trim()).filter(Boolean);state=await request('/api/slots','POST',{slots:a,profit_pct:profit(),reinvest:reinvest()});render();syncSlots()}catch(e){$('msg').textContent=e.message}}
function addPairClick(){for(let i=0;i<6;i++){const e=$('pair'+i);if(e&&!e.value.trim()){e.focus();return}}$('msg').textContent='Maximum 6 pairs'}
async function autoTop6Click(){try{state=await request('/api/slots/auto-top6','POST',{slots:[],profit_pct:profit(),reinvest:reinvest()});syncSlots();render()}catch(e){$('msg').textContent=e.message}}
async function refreshRadar(){try{state=await request('/api/radar','POST');render();syncSlots()}catch(e){$('msg').textContent=e.message}}
$('modeBtn').addEventListener('click',setModeClick);$('testBtn').addEventListener('click',testBinanceClick);$('allocBtn').addEventListener('click',setAllocationClick);$('withdrawBtn').addEventListener('click',withdrawClick);$('onBtn').addEventListener('click',startClick);$('offBtn').addEventListener('click',offClick);$('emBtn').addEventListener('click',emergencyClick);$('resetBtn').addEventListener('click',resetClick);$('pairsBtn').addEventListener('click',setPairsClick);$('addBtn').addEventListener('click',addPairClick);$('topBtn').addEventListener('click',autoTop6Click);drawSlots();load();setInterval(load,1000);setInterval(()=>{if(!state.ranking||!state.ranking.length)refreshRadar()},5000);
</script></body></html>'''
