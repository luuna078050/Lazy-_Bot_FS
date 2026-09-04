from __future__ import annotations
import asyncio, random, time
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Fast Scalper")

BASES = [
    "https://data-api.binance.vision",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api.binance.com",
]
UNIVERSE = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT",
    "ADAUSDT","TRXUSDT","LINKUSDT","SUIUSDT","AVAXUSDT","TONUSDT",
    "LTCUSDT","DOTUSDT","ATOMUSDT","NEARUSDT","APTUSDT","ARBUSDT",
    "OPUSDT","FILUSDT"
]
TFS = ["1m","3m","5m","15m","30m"]
TRADING_TF = "3m"
START_ACCOUNT = 150.0
START_BOT = 100.0
RADAR_INTERVAL = 60
ROTATE_SECONDS = 20

S = {
    "running": False, "account": START_ACCOUNT, "bot": START_BOT,
    "free": START_BOT, "realized": 0.0, "positions": [], "closed": [],
    "orders": [], "ranking": [], "slots": [None]*6, "profit": 0.0,
    "reinvest": False, "cycle": 0, "started": None, "last_radar": 0.0,
    "error": None, "source": None
}
LOCK = asyncio.Lock()
SEM = asyncio.Semaphore(6)

def now(): return datetime.now(timezone.utc).isoformat()

async def get_json(path, params=None):
    last = None
    for base in BASES:
        try:
            async with httpx.AsyncClient(timeout=7, headers={"User-Agent":"FastScalper/1.0"}) as c:
                r = await c.get(base + path, params=params)
                if r.status_code in (418, 429, 403):
                    last = RuntimeError(f"HTTP {r.status_code} from {base}")
                    continue
                r.raise_for_status()
                data = r.json()
                S["source"] = base
                return data
        except Exception as e:
            last = e
    raise last or RuntimeError("No Binance market-data endpoint available")

def ema(a, n):
    k = 2/(n+1); x = a[0]
    for v in a[1:]: x = v*k + x*(1-k)
    return x

async def analyse(sym, tf):
    async with SEM:
        rows = await get_json("/api/v3/klines", {"symbol":sym,"interval":tf,"limit":40})
    closes = [float(x[4]) for x in rows]
    if len(closes) < 21: raise RuntimeError("not enough candles")
    e9, e20 = ema(closes,9), ema(closes,20)
    mom = (closes[-1]/closes[-6]-1)*100
    trend = (e9/e20-1)*100
    score = max(0,min(100,50+trend*18+mom*7))
    signal = "BUY" if e9>e20 and mom>0 else ("SELL" if e9<e20 and mom<0 else "WAIT")
    return {"price":closes[-1],"momentum":mom,"trend":trend,"score":score,"signal":signal}

async def build_ranking():
    tickers = await get_json("/api/v3/ticker/24hr")
    by = {x.get("symbol"):x for x in tickers if isinstance(x,dict)}
    candidates = []
    for s in UNIVERSE:
        t = by.get(s,{})
        try: vol=float(t.get("quoteVolume") or 0); ch=float(t.get("priceChangePercent") or 0)
        except Exception: vol=0; ch=0
        candidates.append((s,vol,abs(ch)))
    candidates.sort(key=lambda z:(z[1],z[2]), reverse=True)
    candidates = [x[0] for x in candidates[:12]]

    async def one(s):
        t = by.get(s,{})
        results = await asyncio.gather(*(analyse(s,tf) for tf in TFS), return_exceptions=True)
        good = [x for x in results if isinstance(x,dict)]
        if not good: return None
        score = sum(x["score"] for x in good)/len(good)
        momentum = sum(x["momentum"] for x in good)/len(good)
        signal = "BUY" if score>=55 and momentum>0 else ("SELL" if score<=45 and momentum<0 else "WAIT")
        return {"symbol":s,"price":float(t.get("lastPrice") or good[-1]["price"]),
                "change":float(t.get("priceChangePercent") or 0),"volume":float(t.get("quoteVolume") or 0),
                "score":round(score,2),"signal":signal,"tf":TRADING_TF}

    rows = await asyncio.gather(*(one(s) for s in candidates))
    rows = [x for x in rows if x]
    rows.sort(key=lambda x:(x["score"],x["volume"]), reverse=True)
    seen={x["symbol"] for x in rows}
    for s in UNIVERSE:
        if len(rows)>=15: break
        if s in seen: continue
        t=by.get(s,{})
        try: p=float(t.get("lastPrice") or 0); c=float(t.get("priceChangePercent") or 0); v=float(t.get("quoteVolume") or 0)
        except Exception: p=c=v=0
        if p>0:
            rows.append({"symbol":s,"price":p,"change":c,"volume":v,
                         "score":round(max(0,min(100,50+c*2)),2),"signal":"WAIT","tf":TRADING_TF})
            seen.add(s)
    return rows[:15]

async def radar(force=False):
    if not force and S["last_radar"] and time.time()-S["last_radar"] < RADAR_INTERVAL: return
    try:
        r = await build_ranking()
        async with LOCK:
            S["ranking"] = r; S["last_radar"] = time.time(); S["error"] = None
    except Exception as e:
        async with LOCK: S["error"] = f"Radar unavailable: {type(e).__name__}: {e}"

def price(sym):
    q=next((x for x in S["ranking"] if x["symbol"]==sym),None)
    return float(q["price"]) if q else 0.0

async def open_position(slot, sym):
    if not sym or S["free"] <= 0: return
    p=price(sym)
    if p <= 0: return
    stake=min(S["free"], max(1.0,S["bot"]/6))
    score=next((x["score"] for x in S["ranking"] if x["symbol"]==sym),0)
    S["free"]-=stake
    pos={"id":f"P{int(time.time()*1000)%100000000}","slot":slot,"symbol":sym,"tf":TRADING_TF,
         "entry":p,"current":p,"stake":stake,"score":score,"opened":time.time(),"opened_at":now()}
    S["positions"].append(pos)
    S["orders"].insert(0,{"time":now(),"symbol":sym,"side":"BUY","status":"FILLED","price":p,"slot":slot,"score":score})

def close_position(p, reason):
    ep=price(p["symbol"]) or p["entry"]
    xp=ep*(1+random.uniform(-.0012,.0025))
    pnl=(xp/p["entry"]-1)*p["stake"]
    S["free"] += p["stake"]
    if S["reinvest"]:
        S["free"] += pnl; S["bot"] += pnl
    else: S["account"] += pnl
    S["realized"] += pnl
    z=dict(p,exit=xp,pnl=pnl,reason=reason,closed_at=now())
    S["closed"].insert(0,z); S["closed"]=S["closed"][:100]
    S["orders"].insert(0,{"time":now(),"symbol":p["symbol"],"side":"SELL","status":"FILLED","price":xp,"slot":p["slot"],"pnl":pnl,"reason":reason})
    S["positions"].remove(p)

async def engine():
    while True:
        try:
            if S["running"]:
                await radar(); S["cycle"] += 1
                for p in list(S["positions"]):
                    q=next((x for x in S["ranking"] if x["symbol"]==p["symbol"]),None)
                    if q: p["current"]=q["price"]
                    live=(p["current"]/p["entry"]-1)*p["stake"]; age=time.time()-p["opened"]; target=p["stake"]*S["profit"]/100
                    if (S["profit"]>0 and live>=target) or (S["profit"]==0 and age>=ROTATE_SECONDS) or age>=60:
                        close_position(p,"PROFIT_TARGET" if S["profit"]>0 and live>=target else "ROTATION")
                top=[x["symbol"] for x in S["ranking"][:6]]
                for i,cfg in enumerate(S["slots"]):
                    if not cfg and i<len(top):
                        cfg={"symbol":top[i],"tf":TRADING_TF,"auto":True}; S["slots"][i]=cfg
                    if cfg and not any(p["slot"]==i for p in S["positions"]): await open_position(i,cfg["symbol"])
            await asyncio.sleep(2)
        except Exception as e:
            S["error"]=f"Engine: {type(e).__name__}: {e}"; await asyncio.sleep(3)

@app.on_event("startup")
async def startup():
    asyncio.create_task(engine()); asyncio.create_task(radar(True))

class Start(BaseModel):
    profit_pct: float=Field(0,ge=0,le=80); reinvest: bool=False
class Slots(BaseModel):
    slots: list[str]=Field(default_factory=list,max_length=6); profit_pct: float=Field(0,ge=0,le=80); reinvest: bool=False

@app.get("/api/health")
async def health():
    return {"ok":True,"worker":"alive","running":S["running"],"cycle":S["cycle"],"time":now(),"radar_ok":bool(S["ranking"]),"source":S["source"],"error":S["error"]}

@app.get("/api/state")
async def state():
    unreal=sum((p["current"]/p["entry"]-1)*p["stake"] for p in S["positions"])
    return {"running":S["running"],"account":S["account"],"bot_balance":S["bot"],"free":S["free"],"realized":S["realized"],"unrealized":unreal,"net":S["realized"]+unreal,"positions":[dict(p) for p in S["positions"]],"closed":S["closed"][:50],"orders":S["orders"][:50],"ranking":S["ranking"],"slots":S["slots"],"profit_pct":S["profit"],"reinvest":S["reinvest"],"cycle":S["cycle"],"started":S["started"],"radar_age":int(time.time()-S["last_radar"]) if S["last_radar"] else 0,"error":S["error"],"source":S["source"]}

@app.post("/api/paper/start")
async def start(b:Start):
    S["profit"]=b.profit_pct; S["reinvest"]=b.reinvest; S["running"]=True; S["started"]=now(); S["error"]=None
    await radar(True); return await state()
@app.post("/api/paper/stop")
async def stop(): S["running"]=False; return await state()
@app.post("/api/paper/emergency")
async def emergency():
    for p in list(S["positions"]): close_position(p,"EMERGENCY_STOP")
    S["running"]=False; return await state()
@app.post("/api/reset")
async def reset():
    S.update({"running":False,"account":START_ACCOUNT,"bot":START_BOT,"free":START_BOT,"realized":0.0,"positions":[],"closed":[],"orders":[],"slots":[None]*6,"profit":0.0,"reinvest":False,"cycle":0,"started":None,"error":None})
    await radar(True); return await state()
@app.post("/api/slots")
async def slots(b:Slots):
    clean=[x.upper().replace("/","") for x in b.slots if x.strip()]
    bad=[x for x in clean if x not in UNIVERSE]
    if len(clean)>6: raise HTTPException(400,"Maximum 6 slots")
    if bad: raise HTTPException(400,"Unsupported pair: "+bad[0])
    S["slots"]=[{"symbol":clean[i],"tf":TRADING_TF,"auto":False} if i<len(clean) else None for i in range(6)]
    S["profit"]=b.profit_pct; S["reinvest"]=b.reinvest; return await state()

HTML="""<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>Fast Scalper</title><style>
*{box-sizing:border-box}body{margin:0;background:#080e1b;color:#eef3ff;font-family:system-ui}.w{max-width:900px;margin:auto;padding:14px}.title{font-size:28px;font-weight:850}.sub,.m{color:#8995ad;font-size:12px}.card{background:#121a2c;border:1px solid #293650;border-radius:14px;padding:12px;margin:9px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.stat{background:#0d1425;border-radius:9px;padding:8px}.v{font-size:17px;font-weight:800}.controls,.slots{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.btn{border:0;border-radius:10px;padding:11px;color:#fff;font-weight:800;background:#273650}.on{background:#078b53}.stop{background:#a72e3f}.input{background:#0b1322;color:#fff;border:1px solid #30405f;border-radius:8px;padding:9px;width:100%}.slot{background:#0d1425;border:1px solid #2a3855;border-radius:9px;padding:8px;position:relative}.x{position:absolute;right:5px;top:5px;background:#273650;color:#fff;border:0;border-radius:6px}.rank{display:grid;grid-template-columns:25px 1fr 65px 55px 38px;gap:6px;align-items:center;padding:8px;border-bottom:1px solid #24314a}.badge{background:#08764e;border-radius:7px;padding:3px;text-align:center}.grid15{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.pick{background:#0d1425;border:1px solid #293753;border-radius:8px;padding:7px}.good{color:#40df8b}.bad{color:#ff6576}@media(max-width:650px){.stats{grid-template-columns:repeat(2,1fr)}.grid15{grid-template-columns:repeat(2,1fr)}}details summary{cursor:pointer;font-weight:800}</style></head><body><div class=w><div class=title>⚡ Fast Scalper</div><div class=sub>Multi-TF analysis 1m · 3m · 5m · 15m · 30m • Trading TF: 3m • PAPER</div>
<div class=card><div class=stats><div class=stat><div class=m>Account Balance</div><div class=v id=account>150.0000 USDT</div></div><div class=stat><div class=m>Realized PnL</div><div class=v id=real>0.0000 USDT</div></div><div class=stat><div class=m>Unrealized PnL</div><div class=v id=unreal>0.0000 USDT</div></div><div class=stat><div class=m>Net PnL</div><div class=v id=net>0.0000 USDT</div></div></div><div style='display:flex;gap:8px;align-items:center;margin-top:7px'><div class=stat style='flex:1'><div class=m>Free / Bot Balance</div><div class=v id=free>100.0000 / 100.0000 USDT</div></div><label><input id=reinvest type=checkbox> Reinvest</label></div></div>
<div class=card><div class=controls><button class='btn on' onclick=toggle() id=power>PAPER ON</button><button class='btn stop' onclick=emergency()>EMERGENCY STOP</button><button class=btn onclick=resetAll()>RESET</button></div><div class=m id=status>Engine OFF</div><div class=m id=timer>Session: 00:00:00</div></div>
<div class=card><b>Open Positions</b><div id=positions class=m style='margin-top:7px'>No open positions</div></div><div class=card><b>Session Result</b><div id=session class=m style='margin-top:7px'>Trades: 0 • Open: 0 • Cycle: 0</div></div>
<div class=card><b>6 Active Slots</b><div class=m>3×2. Только выбранные слоты участвуют в торговле.</div><div id=slots class=slots style='margin-top:7px'></div><div style='display:flex;gap:8px;align-items:center;margin-top:8px'><label class=m>Profit / Trade %</label><input class=input style='max-width:140px' id=profit type=number min=0 max=80 step=.01 value=0></div></div>
<div class=card><details open><summary>Top Pairs — Signal Rating</summary><div class=m style='margin:6px 0'>TOP-6: 3×2. «+» назначает пару в следующий свободный слот.</div><div id=top></div><details><summary style='margin-top:8px'>▶ Show full TOP-15</summary><div class=grid15 id=full style='margin-top:7px'></div></details></details></div>
<div class=card><b>Closed Trades — latest 5</b><div id=closed class=m style='margin-top:7px'>No closed trades</div></div><div class=card><div class=m id=radar>Radar: connecting…</div><div class=bad id=err></div></div></div>
<script>let D={slots:[]};const $=id=>document.getElementById(id);async function api(u,o){let r=await fetch(u,o),d=await r.json();if(!r.ok)throw Error(d.detail||'API error');return d}const money=x=>Number(x||0).toFixed(4);function st(t){if(!t)return'00:00:00';let s=Math.max(0,Math.floor((Date.now()-new Date(t).getTime())/1000));return[Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(x=>String(x).padStart(2,'0')).join(':')}function render(d){D=d;$('account').textContent=money(d.account)+' USDT';$('real').textContent=money(d.realized)+' USDT';$('unreal').textContent=money(d.unrealized)+' USDT';$('net').textContent=money(d.net)+' USDT';$('free').textContent=money(d.free)+' / '+money(d.bot_balance)+' USDT';$('status').textContent=d.running?'Engine RUNNING':'Engine OFF';$('timer').textContent='Session: '+st(d.started);$('session').textContent='Trades: '+d.closed.length+' • Open: '+d.positions.length+' • Cycle: '+d.cycle;$('radar').textContent='Radar: '+(d.ranking.length?'OK':'WAIT')+' • '+(d.radar_age||0)+'s • '+(d.source||'no source');$('err').textContent=d.error||'';$('positions').innerHTML=d.positions.length?d.positions.map(p=>'<div>'+p.slot+'. '+p.symbol+' · entry '+money(p.entry)+' · now '+money(p.current)+'</div>').join(''):'No open positions';$('slots').innerHTML=d.slots.map((x,i)=>'<div class=slot><b>Slot '+(i+1)+'</b><br>'+ (x?x.symbol:'EMPTY')+(x?'<button class=x onclick="clearSlot('+i+')">×</button>':'')+'</div>').join('');let top=d.ranking.slice(0,6);$('top').innerHTML=top.map((x,i)=>'<div class=rank><span>'+(i+1)+'</span><b>'+x.symbol+'</b><span>'+money(x.price)+'</span><span class=badge>'+x.score+'</span><button class=btn onclick="add(\''+x.symbol+'\')">+</button></div>').join('');$('full').innerHTML=d.ranking.map((x,i)=>'<div class=pick><b>'+(i+1)+'. '+x.symbol+'</b><br><span class=good>'+x.signal+'</span> · '+x.score+'<br><span class=m>'+money(x.price)+'</span></div>').join('');$('closed').innerHTML=d.closed.slice(0,5).map(x=>'<div>'+x.symbol+' · '+(x.pnl>=0?'+':'')+money(x.pnl)+' USDT · '+x.reason+'</div>').join('')||'No closed trades';$('profit').value=d.profit_pct||0;$('reinvest').checked=!!d.reinvest;$('power').textContent=d.running?'PAPER OFF':'PAPER ON'}async function refresh(){try{render(await api('/api/state'))}catch(e){$('err').textContent=e.message}}async function toggle(){try{if(D.running)await api('/api/paper/stop',{method:'POST'});else await api('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profit_pct:Number($('profit').value||0),reinvest:$('reinvest').checked})});await refresh()}catch(e){$('err').textContent=e.message}}async function emergency(){try{await api('/api/paper/emergency',{method:'POST'});await refresh()}catch(e){$('err').textContent=e.message}}async function resetAll(){try{await api('/api/reset',{method:'POST'});await refresh()}catch(e){$('err').textContent=e.message}}async function add(s){let a=(D.slots||[]).filter(Boolean).map(x=>x.symbol);if(a.length>=6)return;a.push(s);try{await api('/api/slots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slots:a,profit_pct:Number($('profit').value||0),reinvest:$('reinvest').checked})});await refresh()}catch(e){$('err').textContent=e.message}}async function clearSlot(i){let a=(D.slots||[]).map(x=>x?x.symbol:'').filter(Boolean);a.splice(i,1);try{await api('/api/slots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slots:a,profit_pct:Number($('profit').value||0),reinvest:$('reinvest').checked})});await refresh()}catch(e){$('err').textContent=e.message}}setInterval(refresh,3000);setInterval(()=>{if(D.started)$('timer').textContent='Session: '+st(D.started)},1000);refresh();</script></body></html>"""

@app.get("/", response_class=HTMLResponse)
async def home(): return HTML
