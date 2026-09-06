from __future__ import annotations
import asyncio, random, time
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Fast Scalper v0.4 Test")

BASES = ["https://data-api.binance.vision","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com","https://api.binance.com"]
UNIVERSE = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","TRXUSDT","LINKUSDT","SUIUSDT","AVAXUSDT","TONUSDT","LTCUSDT","DOTUSDT","ATOMUSDT","NEARUSDT","APTUSDT","ARBUSDT","OPUSDT","FILUSDT"]
ANALYSIS_TFS = ["1m","3m","5m","15m","30m"]
TRADING_TF = "3m"
START_ACCOUNT = 1850.0
START_BOT = 0.0
RADAR_INTERVAL = 20
ROTATE_SECONDS = 60
MAX_POSITION_SECONDS = 420
MAX_SLOTS = 6

S: dict[str, Any] = {"running":False,"account":START_ACCOUNT,"bot":START_BOT,"free":START_BOT,"realized":0.0,"session_realized":0.0,"session_trades":0,"session_started":None,"positions":[],"closed":[],"orders":[],"ranking":[],"slots":[None]*MAX_SLOTS,"profit":0.0,"reinvest":False,"cycle":0,"started":None,"last_radar":0.0,"error":None,"source":None}
LOCK = asyncio.Lock(); SEM = asyncio.Semaphore(8)

def now(): return datetime.now(timezone.utc).isoformat()

async def get_json(path: str, params: dict | None = None):
    last = None
    for base in BASES:
        try:
            async with httpx.AsyncClient(timeout=7, headers={"User-Agent":"FastScalper/0.4"}) as c:
                r = await c.get(base + path, params=params)
                if r.status_code in (403,418,429): last = RuntimeError(f"HTTP {r.status_code} from {base}"); continue
                r.raise_for_status(); data = r.json(); S["source"] = base; return data
        except Exception as exc: last = exc
    raise last or RuntimeError("No Binance market-data endpoint available")

def ema(values, n):
    k=2/(n+1); x=values[0]
    for v in values[1:]: x=v*k+x*(1-k)
    return x

async def analyse(symbol, tf):
    async with SEM: rows=await get_json("/api/v3/klines",{"symbol":symbol,"interval":tf,"limit":40})
    closes=[float(x[4]) for x in rows]
    if len(closes)<21: raise RuntimeError("not enough candles")
    e9,e20=ema(closes,9),ema(closes,20); momentum=(closes[-1]/closes[-6]-1)*100; trend=(e9/e20-1)*100
    score=max(0,min(100,50+trend*18+momentum*7)); signal="BUY" if e9>e20 and momentum>0 else ("SELL" if e9<e20 and momentum<0 else "WAIT")
    return {"price":closes[-1],"momentum":momentum,"trend":trend,"score":score,"signal":signal}

async def build_ranking():
    tickers=await get_json("/api/v3/ticker/24hr"); by={x.get("symbol"):x for x in tickers if isinstance(x,dict)}
    async def one(symbol):
        t=by.get(symbol,{})
        results=await asyncio.gather(*(analyse(symbol,tf) for tf in ANALYSIS_TFS),return_exceptions=True); good=[x for x in results if isinstance(x,dict)]
        if not good:return None
        score=sum(x["score"] for x in good)/len(good); momentum=sum(x["momentum"] for x in good)/len(good)
        signal="BUY" if score>=55 and momentum>0 else ("SELL" if score<=45 and momentum<0 else "WAIT")
        return {"symbol":symbol,"price":float(t.get("lastPrice") or good[-1]["price"]),"change":float(t.get("priceChangePercent") or 0),"volume":float(t.get("quoteVolume") or 0),"score":round(score,2),"signal":signal,"tf":TRADING_TF}
    rows=await asyncio.gather(*(one(s) for s in UNIVERSE)); rows=[x for x in rows if x]; rows.sort(key=lambda x:(x["score"],x["volume"]),reverse=True); return rows[:15]

async def radar(force=False):
    if not force and S["last_radar"] and time.time()-S["last_radar"]<RADAR_INTERVAL:return
    try:
        r=await build_ranking()
        async with LOCK:S["ranking"]=r; S["last_radar"]=time.time(); S["error"]=None
    except Exception as exc:
        async with LOCK:S["error"]=f"Radar unavailable: {type(exc).__name__}: {exc}"

def price(symbol):
    q=next((x for x in S["ranking"] if x["symbol"]==symbol),None); return float(q["price"]) if q else 0.0

async def open_position(slot,symbol):
    if not symbol or S["free"]<=0:return
    p=price(symbol)
    if p<=0:return
    stake=min(float(S["free"]),max(1.0,float(S["bot"])/MAX_SLOTS)); score=next((x["score"] for x in S["ranking"] if x["symbol"]==symbol),0); S["free"]-=stake
    pos={"id":f"P{int(time.time()*1000)%100000000}","slot":slot,"symbol":symbol,"tf":TRADING_TF,"entry":p,"current":p,"stake":stake,"score":score,"opened":time.time(),"opened_at":now()}; S["positions"].append(pos)
    S["orders"].insert(0,{"time":now(),"symbol":symbol,"side":"BUY","status":"FILLED","price":p,"slot":slot,"score":score})

def close_position(position,reason):
    ep=price(position["symbol"]) or position["entry"]; xp=ep*(1+random.uniform(-0.0012,0.0025)); pnl=(xp/position["entry"]-1)*position["stake"]
    S["free"]+=position["stake"]
    if S["reinvest"]: S["free"]+=pnl; S["bot"]+=pnl
    else: S["account"]+=pnl
    S["realized"]+=pnl; S["session_realized"]+=pnl; S["session_trades"]+=1
    z=dict(position,exit=xp,pnl=pnl,reason=reason,closed_at=now()); S["closed"].insert(0,z); S["closed"]=S["closed"][:100]
    S["orders"].insert(0,{"time":now(),"symbol":position["symbol"],"side":"SELL","status":"FILLED","price":xp,"slot":position["slot"],"pnl":pnl,"reason":reason}); S["positions"].remove(position)

async def manage_positions():
    for position in list(S["positions"]):
        q=next((x for x in S["ranking"] if x["symbol"]==position["symbol"]),None)
        if q: position["current"]=q["price"]
        live=(position["current"]/position["entry"]-1)*position["stake"]; age=time.time()-position["opened"]; target=position["stake"]*S["profit"]/100
        if S["profit"]>0 and live>=target: close_position(position,"PROFIT_TARGET")
        elif age>=MAX_POSITION_SECONDS: close_position(position,"TIMEOUT")
        elif age>=ROTATE_SECONDS: close_position(position,"ROTATION")

async def engine():
    while True:
        try:
            # STOP is graceful: it blocks new entries but lets already-open positions finish normally.
            if S["running"] or S["positions"]:
                await radar()
                if S["running"]: S["cycle"]+=1
                await manage_positions()
                if S["running"]:
                    for i,cfg in enumerate(S["slots"]):
                        if cfg and not any(p["slot"]==i for p in S["positions"]): await open_position(i,cfg["symbol"])
            await asyncio.sleep(1)
        except Exception as exc:
            S["error"]=f"Engine: {type(exc).__name__}: {exc}"; await asyncio.sleep(2)

@app.on_event("startup")
async def startup(): asyncio.create_task(engine()); asyncio.create_task(radar(True))

class Start(BaseModel): profit_pct:float=Field(0,ge=0,le=80); reinvest:bool=False
class Slots(BaseModel): slots:list[str]=Field(default_factory=list,max_length=MAX_SLOTS); profit_pct:float=Field(0,ge=0,le=80); reinvest:bool=False
class Allocation(BaseModel): amount:float=Field(ge=0,le=1_000_000)
class Withdraw(BaseModel): amount:float=Field(gt=0,le=1_000_000)

@app.get("/api/health")
async def health(): return {"ok":True,"worker":"alive","running":S["running"],"cycle":S["cycle"],"time":now(),"error":S["error"]}

@app.get("/api/state")
async def state():
    unrealized=sum((p["current"]/p["entry"]-1)*p["stake"] for p in S["positions"])
    return {"running":S["running"],"account":float(S["account"]),"account_free":float(S["account"]),"bot_balance":float(S["bot"]),"free":float(S["free"]),"realized":float(S["realized"]),"session_realized":float(S["session_realized"]),"session_trades":int(S["session_trades"]),"unrealized":float(unrealized),"net":float(S["realized"]+unrealized),"total_equity":float(S["account"]+S["bot"]+unrealized),"withdraw_available":float(S["free"]) if (not S["running"] and not S["positions"]) else 0.0,"positions":[dict(p) for p in S["positions"]],"closed":S["closed"][:50],"orders":S["orders"][:50],"ranking":S["ranking"],"slots":S["slots"],"profit_pct":S["profit"],"reinvest":S["reinvest"],"cycle":S["cycle"],"started":S["started"],"session_started":S["session_started"],"radar_age":int(time.time()-S["last_radar"]) if S["last_radar"] else 0,"error":S["error"],"source":S["source"]}

@app.post("/api/paper/start")
async def start(body:Start):
    S["profit"]=body.profit_pct; S["reinvest"]=body.reinvest; S["running"]=True; S["started"]=now(); S["session_started"]=S["started"]; S["session_realized"]=0.0; S["session_trades"]=0; S["error"]=None; await radar(True); return await state()

@app.post("/api/paper/stop")
async def stop(): S["running"]=False; return await state()

@app.post("/api/paper/emergency")
async def emergency():
    for p in list(S["positions"]): close_position(p,"EMERGENCY_STOP")
    S["running"]=False; S["started"]=None; return await state()

@app.post("/api/reset")
async def reset():
    S.update({"running":False,"account":START_ACCOUNT,"bot":START_BOT,"free":START_BOT,"realized":0.0,"session_realized":0.0,"session_trades":0,"session_started":None,"positions":[],"closed":[],"orders":[],"slots":[None]*MAX_SLOTS,"profit":0.0,"reinvest":False,"cycle":0,"started":None,"error":None}); await radar(True); return await state()

@app.post("/api/slots")
async def slots(body:Slots):
    clean=[x.upper().replace('/','') for x in body.slots if x.strip()]; bad=[x for x in clean if x not in UNIVERSE]
    if len(clean)>MAX_SLOTS: raise HTTPException(400,"Maximum 6 slots")
    if bad: raise HTTPException(400,"Unsupported pair: "+bad[0])
    S["slots"]=[{"symbol":clean[i],"tf":TRADING_TF,"auto":False} if i<len(clean) else None for i in range(MAX_SLOTS)]; S["profit"]=body.profit_pct; S["reinvest"]=body.reinvest; return await state()

@app.post("/api/strategy/allocate")
async def allocate(body:Allocation):
    if S["running"] or S["positions"]: raise HTTPException(400,"Bot allocation is available only after STOP and all open cycles are closed")
    amount=float(body.amount); current=float(S["bot"]); total=float(S["account"]+current)
    if amount>total+1e-9: raise HTTPException(400,f"Maximum allocation is total available capital: {total:.4f} USDT")
    # Move the delta between the two paper wallets; never create/destroy capital.
    S["account"] = total-amount; S["bot"]=amount; S["free"]=amount; return await state()

@app.post("/api/strategy/withdraw")
async def withdraw(body:Withdraw):
    if S["running"] or S["positions"]: raise HTTPException(400,"Withdraw is available only after STOP and all open cycles are closed")
    amount=float(body.amount); available=float(S["free"])
    if amount>available+1e-9: raise HTTPException(400,f"Maximum available for withdraw: {available:.4f} USDT")
    S["bot"]-=amount; S["free"]-=amount; S["account"]+=amount; return await state()

HTML=r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper v0.4</title><style>*{box-sizing:border-box}body{margin:0;background:#080e1b;color:#eef3ff;font-family:system-ui}.w{max-width:900px;margin:auto;padding:14px}.title{font-size:28px;font-weight:850}.sub,.m{color:#8995ad;font-size:12px}.card{background:#121a2c;border:1px solid #293650;border-radius:14px;padding:12px;margin:9px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.stat{background:#0d1425;border-radius:9px;padding:8px}.v{font-size:17px;font-weight:800}.controls,.slots{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.btn{border:0;border-radius:10px;padding:11px;color:#fff;font-weight:800;background:#273650}.on{background:#078b53}.stop{background:#a72e3f}.input{background:#0b1322;color:#fff;border:1px solid #30405f;border-radius:8px;padding:9px;width:100%}.slot{background:#0d1425;border:1px solid #2a3855;border-radius:9px;padding:8px;position:relative}.x{position:absolute;right:5px;top:5px;background:#273650;color:#fff;border:0;border-radius:6px}.rank{display:grid;grid-template-columns:25px 1fr 60px 38px;gap:6px;align-items:center;padding:8px;border-bottom:1px solid #24314a}.badge{background:#08764e;border-radius:7px;padding:3px;text-align:center}.grid15{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.pick{background:#0d1425;border:1px solid #293753;border-radius:8px;padding:7px}.good{color:#40df8b}.bad{color:#ff6576}@media(max-width:650px){.stats{grid-template-columns:repeat(2,1fr)}.grid15{grid-template-columns:repeat(2,1fr)}}details summary{cursor:pointer;font-weight:800}</style></head><body><div class="w"><div class="title">⚡ Fast Scalper <span class="m">v0.4 TEST</span></div><div class="sub">Multi-TF analysis 1m · 3m · 5m · 15m · 30m • Trading TF: 3m • PAPER</div><div class="card"><div class="stats"><div class="stat"><div class="m">Account Balance</div><div class="v" id="account">1850.0000 USDT</div></div><div class="stat"><div class="m">Realized PnL</div><div class="v" id="real">0.0000 USDT</div></div><div class="stat"><div class="m">Unrealized PnL</div><div class="v" id="unreal">0.0000 USDT</div></div><div class="stat"><div class="m">Net PnL</div><div class="v" id="net">0.0000 USDT</div></div></div><div style="display:flex;gap:8px;align-items:center;margin-top:7px"><div class="stat" style="flex:1"><div class="m">Account Free / Bot Balance</div><div class="v" id="free">1850.0000 / 0.0000 USDT</div><div class="m" style="margin-top:5px">Paper transfer: Account ↔ Bot. Total capital is conserved.</div><div style="display:flex;gap:6px;margin-top:7px"><input class="input" id="botAllocation" type="number" min="0" step="0.0001" placeholder="Bot balance USDT"><button class="btn" onclick="setBot()">SET BOT</button></div><div style="display:flex;gap:6px;margin-top:7px"><input class="input" id="withdrawAmount" type="number" min="0" step="0.0001" placeholder="Withdraw USDT"><button class="btn" onclick="withdrawBot()">WITHDRAW</button></div><div class="m" id="withdrawInfo" style="margin-top:5px"></div></div><label><input id="reinvest" type="checkbox"> Reinvest</label></div></div><div class="card"><div class="controls"><button class="btn on" id="power" onclick="toggle()">PAPER ON</button><button class="btn stop" onclick="emergency()">EMERGENCY STOP</button><button class="btn" onclick="resetAll()">RESET</button></div><div class="m" id="status">Engine OFF</div><div class="m" id="timer">Session: 00:00:00</div></div><div class="card"><b>Session Result</b><div id="session" class="m" style="margin-top:7px">Trades: 0 • Session PnL: 0.0000 USDT • Open: 0 • Cycle: 0</div></div><div class="card"><b>Closed Trades — latest 5</b><div id="closed" class="m" style="margin-top:7px">No closed trades</div></div><div class="card"><b>Open Positions</b><div id="positions" class="m" style="margin-top:7px">No open positions</div></div><div class="card"><b>6 Active Slots</b><div class="m">3×2. Только выбранные слоты участвуют в торговле. Одна пара может занимать несколько слотов.</div><div class="slots" id="slots" style="margin-top:7px"></div><div style="display:flex;gap:8px;align-items:center;margin-top:8px"><label class="m">Profit / Trade %</label><input class="input" style="max-width:140px" id="profit" type="number" min="0" max="80" step="0.01" value="0"></div></div><div class="card"><details open><summary>Top Pairs — Signal Rating</summary><div class="m" style="margin:6px 0">TOP-6: 3×2. «+» назначает пару в следующий свободный слот.</div><div id="top"></div><details><summary style="margin-top:8px">▶ Show full TOP-15</summary><div class="grid15" id="full" style="margin-top:7px"></div></details></details></div><div class="card"><div class="m" id="radar">Radar: —</div><div class="bad" id="err"></div></div></div><script>let D={slots:[]},dirty=false;const $=id=>document.getElementById(id);async function api(u,o){let r=await fetch(u,o),d=await r.json();if(!r.ok)throw Error(d.detail||'API error');return d}const money=x=>Number(x||0).toFixed(4);function st(t){if(!t)return'00:00:00';let s=Math.max(0,Math.floor((Date.now()-new Date(t).getTime())/1000));return[Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(x=>String(x).padStart(2,'0')).join(':')}function render(d){D=d;$('account').textContent=money(d.account)+' USDT';$('real').textContent=money(d.realized)+' USDT';$('unreal').textContent=money(d.unrealized)+' USDT';$('net').textContent=money(d.net)+' USDT';$('free').textContent=money(d.account_free)+' / '+money(d.bot_balance)+' USDT';$('reinvest').checked=d.reinvest;if(!dirty||document.activeElement!==$('profit'))$('profit').value=d.profit_pct;$('status').textContent=d.running?'PAPER ENGINE ON • Cycle '+d.cycle:(d.positions.length?'PAPER OFF • Closing open cycles':'Engine OFF');$('power').textContent=d.running?'PAPER OFF':'PAPER ON';$('power').className=d.running?'btn stop':'btn on';$('timer').textContent='Session: '+st(d.session_started);$('session').textContent='Trades: '+d.session_trades+' • Session PnL: '+money(d.session_realized)+' USDT • Open: '+d.positions.length+' • Cycle: '+d.cycle;$('radar').textContent='Radar updated '+(d.radar_age||0)+'s ago • Trading TF 3m • Analysis 1m/3m/5m/15m/30m';$('err').textContent=d.error||'';$('positions').innerHTML=d.positions.length?d.positions.map(p=>p.symbol+' • '+money(p.stake)+' USDT • entry '+p.entry+' • current '+p.current+' • slot '+(p.slot+1)+' • score '+p.score).join('<br>'):'No open positions';$('closed').innerHTML=d.closed.slice(0,5).map(x=>x.symbol+' • '+x.reason+' • <span class="'+(x.pnl>=0?'good':'bad')+'">'+(x.pnl>=0?'+':'')+money(x.pnl)+' USDT</span>').join('<br>')||'No closed trades';$('slots').innerHTML=d.slots.map((x,i)=>'<div class="slot"><div class="m">SLOT '+(i+1)+'</div><b>'+(x?x.symbol:'EMPTY')+'</b><div class="m">3m</div>'+(x?'<button class="x" onclick="clearSlot('+i+')">×</button>':'')+'</div>').join('');let top=d.ranking.slice(0,6);$('top').innerHTML=top.map((x,i)=>'<div class="rank"><b>'+(i+1)+'</b><span><b>'+x.symbol+'</b> '+x.signal+'</span><span class="badge">'+x.score+'</span><button class="btn" onclick="add(\''+x.symbol+'\')">+</button></div>').join('');$('full').innerHTML=d.ranking.slice(0,15).map((x,i)=>'<div class="pick"><b>#'+(i+1)+' '+x.symbol+'</b><br><small>'+x.score+' • '+x.signal+'</small><button class="btn" onclick="add(\''+x.symbol+'\')">+</button></div>').join('');$('withdrawInfo').textContent='Withdraw available after STOP + closed cycles: '+money(d.withdraw_available)+' USDT'}async function load(){try{render(await api('/api/state'))}catch(e){$('err').textContent=e.message}}async function toggle(){try{let p=Number($('profit').value||0),r=$('reinvest').checked;if(D.running)await api('/api/paper/stop',{method:'POST'});else await api('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profit_pct:p,reinvest:r})});dirty=false;await load()}catch(e){$('err').textContent=e.message}}async function emergency(){try{await api('/api/paper/emergency',{method:'POST'});dirty=false;await load()}catch(e){$('err').textContent=e.message}}async function resetAll(){try{await api('/api/reset',{method:'POST'});dirty=false;await load()}catch(e){$('err').textContent=e.message}}async function setBot(){try{let a=Number($('botAllocation').value||0);await api('/api/strategy/allocate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount:a})});$('botAllocation').value='';await load()}catch(e){$('err').textContent=e.message}}async function withdrawBot(){try{let a=Number($('withdrawAmount').value||0);await api('/api/strategy/withdraw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount:a})});$('withdrawAmount').value='';await load()}catch(e){$('err').textContent=e.message}}async function saveSlots(a){await api('/api/slots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slots:a,profit_pct:Number($('profit').value||0),reinvest:$('reinvest').checked})});dirty=false;await load()}async function add(s){try{let a=D.slots.map(x=>x&&x.symbol).filter(Boolean);if(a.length>=6){alert('Все 6 слотов заняты.');return}a.push(s);await saveSlots(a)}catch(e){$('err').textContent=e.message}}async function clearSlot(i){let a=D.slots.map(x=>x&&x.symbol).filter(Boolean);a.splice(i,1);await saveSlots(a)}$('profit').addEventListener('input',()=>dirty=true);$('reinvest').addEventListener('change',async()=>{let a=D.slots.map(x=>x&&x.symbol).filter(Boolean);try{await saveSlots(a)}catch(e){$('err').textContent=e.message}});load();setInterval(load,1000);setInterval(()=>{if(D.session_started)$('timer').textContent='Session: '+st(D.session_started)},250);</script></body></html>'''

@app.get('/',response_class=HTMLResponse)
async def home(): return HTML
