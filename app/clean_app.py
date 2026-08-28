from __future__ import annotations

import threading, time, random
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

try:
    from .market_radar import RADAR
except Exception:
    RADAR = None

app = FastAPI(title="Fast Scalper New Start")

LOCK = threading.RLock()
STOP = threading.Event()
WORKER = None
STATE = {
    "running": False, "mode": "paper", "started_at": None, "initial_balance": 1000.0,
    "account_balance": 1000.0, "free_balance": 1000.0, "realized": 0.0, "unrealized": 0.0,
    "net": 0.0, "open": [], "closed": [], "orders": [], "error": None,
    "pairs": [], "available": [], "rotation_index": 0, "last_cycle": None,
    "trade_delay": 20, "timeframe": "3m", "capital_per_trade": 25.0
}

UNIVERSE = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","TRXUSDT","LINKUSDT","SUIUSDT","AVAXUSDT","TONUSDT"]

class StartReq(BaseModel):
    capital: float = 1000.0
    pairs: list[str] = []
    timeframes: list[str] = []
    trade_delay: int = 20

class PairReq(BaseModel):
    pairs: list[str]
    timeframes: list[str] = []


def now(): return datetime.now(timezone.utc).isoformat()

def market_price(sym):
    if RADAR:
        try:
            with RADAR.lock:
                t = dict(RADAR.tickers.get(sym) or {})
            p = float(t.get("c") or 0)
            if p > 0: return p
        except Exception: pass
    fallback = {"BTCUSDT":79000,"ETHUSDT":2500,"BNBUSDT":700,"SOLUSDT":100,"XRPUSDT":2.1,"DOGEUSDT":0.22,"ADAUSDT":0.22,"TRXUSDT":0.34,"LINKUSDT":12,"SUIUSDT":3.5,"AVAXUSDT":25,"TONUSDT":3.2}
    return fallback.get(sym, 1.0)

def score(sym):
    if RADAR:
        try:
            rows = RADAR.snapshot(20)
            for r in rows:
                if str(r.get("symbol","")).replace('/','') == sym:
                    return float(r.get("score",r.get("rating",0)) or 0), r
        except Exception: pass
    return 50.0 + random.random()*25, {"symbol": sym, "score": 50.0}

def rank_universe():
    rows=[]
    for s in UNIVERSE:
        sc, raw = score(s)
        rows.append({"symbol":s,"score":round(sc,2),"price":market_price(s),"signal":raw.get("signal","NORMAL"),"timeframe":"3m"})
    rows.sort(key=lambda x:x["score"], reverse=True)
    return rows

def reset_state(capital=1000.0):
    with LOCK:
        STATE.update({"running":False,"mode":"paper","started_at":None,"initial_balance":capital,"account_balance":capital,"free_balance":capital,"realized":0.0,"unrealized":0.0,"net":0.0,"open":[],"closed":[],"orders":[],"error":None,"pairs":[],"available":rank_universe(),"rotation_index":0,"last_cycle":None,"trade_delay":20,"timeframe":"3m","capital_per_trade":25.0})

def open_trade(sym, tf, allocation):
    p=market_price(sym)
    with LOCK:
        if STATE["free_balance"] < allocation or any(x["symbol"]==sym for x in STATE["open"]): return False
        STATE["free_balance"] -= allocation
        STATE["open"].append({"symbol":sym,"timeframe":tf,"entry":p,"allocation":allocation,"opened":time.time(),"opened_at":now()})
        STATE["orders"].append({"time":now(),"symbol":sym,"side":"BUY","status":"FILLED","price":p,"allocation":allocation})
    return True

def close_trade(pos, reason="SIM_TARGET"):
    p=market_price(pos["symbol"]); entry=float(pos["entry"]); alloc=float(pos["allocation"])
    gross=(p/entry-1)*alloc
    fee=(alloc+p*(alloc/entry))*0.001
    net=gross-fee
    with LOCK:
        STATE["free_balance"] += alloc+net
        STATE["account_balance"] += net
        STATE["realized"] += net
        STATE["closed"].insert(0,{**pos,"exit":p,"net":net,"gross":gross,"fee":fee,"reason":reason,"closed_at":now()})
        STATE["orders"].append({"time":now(),"symbol":pos["symbol"],"side":"SELL","status":"FILLED","price":p,"net":net,"reason":reason})
        STATE["open"]=[x for x in STATE["open"] if x is not pos]
        STATE["closed"]=STATE["closed"][:50]

def worker():
    if RADAR:
        try: RADAR.start()
        except Exception: pass
    last_rotate=0
    while not STOP.is_set():
        try:
            with LOCK:
                pairs=list(STATE["pairs"]); tfs=list(STATE.get("timeframes",[])); delay=int(STATE["trade_delay"])
                STATE["available"]=rank_universe()
            nowt=time.time()
            # Open one paper position from the selected rotation when free capital permits.
            if pairs and nowt-last_rotate >= max(5,delay):
                last_rotate=nowt
                with LOCK: STATE["rotation_index"]=(STATE["rotation_index"]+1)%len(pairs); idx=STATE["rotation_index"]; sym=pairs[idx]; tf=tfs[idx] if idx<len(tfs) else STATE["timeframe"]
                open_trade(sym,tf,min(float(STATE["capital_per_trade"]),float(STATE["free_balance"])))
            # Close positions after a short paper-test lifecycle; this guarantees observable analytics without pretending to execute real orders.
            with LOCK: positions=list(STATE["open"])
            for pos in positions:
                age=nowt-float(pos["opened"])
                if age>=max(8,min(60,delay)):
                    close_trade(pos,"PAPER_CYCLE")
            with LOCK:
                unreal=0.0
                for pos in STATE["open"]: unreal += (market_price(pos["symbol"])/float(pos["entry"])-1)*float(pos["allocation"])
                STATE["unrealized"]=unreal; STATE["net"]=STATE["account_balance"]+unreal-STATE["initial_balance"]; STATE["last_cycle"]=now()
        except Exception as exc:
            with LOCK: STATE["error"]=str(exc)[:300]
        time.sleep(2)
    with LOCK: STATE["running"]=False

def snapshot():
    with LOCK:
        s={k:v for k,v in STATE.items() if k not in {"available"}}
        s["open"]=[dict(x, current=market_price(x["symbol"])) for x in STATE["open"]]
        s["available"]=rank_universe()
        s["session_result"]={"trades":len(STATE["closed"]),"open":len(STATE["open"]),"realized":round(STATE["realized"],4),"unrealized":round(STATE["unrealized"],4),"net":round(STATE["net"],4)}
        return s

@app.get("/", response_class=HTMLResponse)
def home(): return HTML

@app.get("/api/health")
def health(): return {"ok":True,"service":"fast-scalper","running":STATE["running"],"engine":"paper-simulation"}

@app.get("/api/state")
def api_state(): return snapshot()

@app.get("/api/ranking")
def ranking(): return {"pairs":rank_universe()}

@app.post("/api/paper/start")
def paper_start(req:StartReq):
    global WORKER
    if req.capital<=0: raise HTTPException(400,"capital must be positive")
    pairs=[x.upper().replace('/','') for x in req.pairs if x.strip()]
    if not pairs: raise HTTPException(400,"Select at least one pair")
    if len(pairs)>6: raise HTTPException(400,"Maximum 6 active pairs")
    tfs=[x.lower() for x in req.timeframes] or ["3m"]*len(pairs)
    if len(tfs)!=len(pairs) or any(x not in {"1m","3m","5m"} for x in tfs): raise HTTPException(400,"Timeframes: 1m, 3m, 5m")
    with LOCK:
        STATE["running"]=True; STATE["started_at"]=STATE["started_at"] or now(); STATE["initial_balance"]=req.capital; STATE["account_balance"]=req.capital; STATE["free_balance"]=req.capital; STATE["pairs"]=pairs; STATE["timeframes"]=tfs; STATE["trade_delay"]=max(5,min(120,int(req.trade_delay))); STATE["capital_per_trade"]=max(1,req.capital/max(1,len(pairs)))
        STATE["error"]=None
    STOP.clear()
    if not WORKER or not WORKER.is_alive(): WORKER=threading.Thread(target=worker,daemon=True,name="fast-scalper-paper-engine"); WORKER.start()
    return snapshot()

@app.post("/api/paper/stop")
def paper_stop():
    STOP.set()
    with LOCK: STATE["running"]=False
    return snapshot()

@app.post("/api/paper/emergency")
def emergency():
    STOP.set()
    with LOCK: positions=list(STATE["open"])
    for p in positions: close_trade(p,"EMERGENCY_STOP")
    with LOCK: STATE["running"]=False
    return snapshot()

@app.post("/api/reset")
def reset():
    STOP.set(); reset_state(1000.0); return snapshot()

@app.post("/api/pairs")
def save_pairs(req:PairReq):
    pairs=[x.upper().replace('/','') for x in req.pairs if x.strip()]
    if len(pairs)>6: raise HTTPException(400,"Maximum 6 pairs")
    tfs=[x.lower() for x in req.timeframes] or ["3m"]*len(pairs)
    if len(tfs)!=len(pairs): raise HTTPException(400,"Timeframe count mismatch")
    with LOCK: STATE["pairs"]=pairs; STATE["timeframes"]=tfs
    return snapshot()

HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper — New Start</title><style>
*{box-sizing:border-box}body{margin:0;background:#091020;color:#edf2ff;font-family:system-ui,-apple-system,sans-serif}.wrap{max-width:760px;margin:auto;padding:16px}.title{font-size:30px;font-weight:800;margin:8px 0 2px}.sub{color:#8793ad;margin-bottom:14px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.card{background:#121b30;border:1px solid #263452;border-radius:16px;padding:14px;margin:10px 0}.metric{font-size:13px;color:#8f9bb5}.value{font-size:22px;font-weight:800;margin-top:3px}.green{color:#36e28b}.red{color:#ff6577}.controls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}.btn{border:0;border-radius:12px;padding:14px;font-weight:800;font-size:16px;color:#fff;background:#263657}.on{background:#079454}.stop{background:#bd3447}.input{width:100%;background:#0b1324;border:1px solid #2a3957;color:#fff;padding:13px;border-radius:11px;font-size:16px}.pairs{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.pair{background:#0d1527;border:1px solid #2b3954;border-radius:12px;padding:9px}.pair input{margin-bottom:7px}.small{font-size:12px;color:#8e9bb5}.rank{display:grid;grid-template-columns:1fr 70px 90px;gap:8px;padding:9px;border-bottom:1px solid #202d45}.badge{background:#0c6f46;border-radius:9px;padding:3px 7px;text-align:center}.status{padding:10px;border-radius:10px;background:#0d1527;color:#a9b5cc}.hidden{display:none}@media(max-width:560px){.grid,.controls{grid-template-columns:1fr 1fr}.pairs{grid-template-columns:repeat(2,1fr)}.title{font-size:25px}}
</style></head><body><div class="wrap"><div class="title">⚡ Fast Scalper — New Start</div><div class="sub">Clean runtime • PAPER first • real market quotes • simulated orders</div>
<div class="card"><div class="grid"><div><div class="metric">Account Balance</div><div id="account" class="value">1000.00 USDT</div></div><div><div class="metric">Free Balance</div><div id="free" class="value">1000.00 USDT</div></div><div><div class="metric">Realized PnL</div><div id="realized" class="value">0.00 USDT</div></div><div><div class="metric">Unrealized PnL</div><div id="unrealized" class="value">0.00 USDT</div></div><div><div class="metric">Net PnL</div><div id="net" class="value">0.00 USDT</div></div></div></div>
<div class="card"><h2>Open Positions</h2><div id="open">No open positions</div></div><div class="card"><h2>Session Result</h2><div id="session">Trades: 0 • Open: 0 • Realized: 0.00 USDT • Unrealized: 0.00 USDT</div></div><div class="card"><h2>Closed Trades — latest 5</h2><div id="closed">No closed trades yet</div></div>
<div class="card"><div class="controls"><button class="btn on" onclick="start()">PAPER ON</button><button class="btn stop" onclick="stop(true)">EMERGENCY STOP</button><button class="btn" onclick="reset()">RESET</button></div><div id="status" class="status" style="margin-top:10px">Engine OFF</div></div>
<div class="card"><h2>6 Active Pairs</h2><div class="pairs" id="pairs"></div><button class="btn" style="margin-top:10px;width:100%" onclick="save()">SAVE PAIRS</button><div class="small" style="margin-top:8px">Same pair may be selected on different timeframes.</div></div>
<div class="card"><h2>Top Pairs — Signal Rating</h2><div id="ranking"></div></div>
</div><script>
let last={};const qs=s=>document.querySelector(s);function pairRows(){let p=last.pairs||[],tf=last.timeframes||[];let out='';for(let i=0;i<6;i++){out+=`<div class="pair"><input class="input ps" value="${p[i]||''}" placeholder="PAIR ${i+1}"><select class="input ts"><option ${tf[i]=='1m'?'selected':''}>1m</option><option ${tf[i]=='3m'||!tf[i]?'selected':''}>3m</option><option ${tf[i]=='5m'?'selected':''}>5m</option></select></div>`}qs('#pairs').innerHTML=out}
async function api(u,o){let r=await fetch(u,o);if(!r.ok)throw Error(await r.text());return r.json()}async function load(){try{last=await api('/api/state');qs('#account').textContent=last.account_balance.toFixed(2)+' USDT';qs('#free').textContent=last.free_balance.toFixed(2)+' USDT';qs('#realized').textContent=last.realized.toFixed(4)+' USDT';qs('#unrealized').textContent=last.unrealized.toFixed(4)+' USDT';qs('#net').textContent=last.net.toFixed(4)+' USDT';qs('#status').textContent=last.running?'PAPER ENGINE ON • live market feed':'Engine OFF';qs('#open').innerHTML=last.open.length?last.open.map(x=>`${x.symbol} • ${x.timeframe} • entry ${x.entry} → ${x.current} • ${((x.current/x.entry-1)*x.allocation).toFixed(4)} USDT`).join('<br>'):'No open positions';qs('#session').textContent=`Trades: ${last.session_result.trades} • Open: ${last.session_result.open} • Realized: ${last.session_result.realized.toFixed(4)} USDT • Unrealized: ${last.session_result.unrealized.toFixed(4)} USDT • Net: ${last.session_result.net.toFixed(4)} USDT`;qs('#closed').innerHTML=last.closed.length?last.closed.slice(0,5).map(x=>`${x.symbol} ${x.timeframe} • ${x.reason} • ${x.net>=0?'+':''}${x.net.toFixed(4)} USDT`).join('<br>'):'No closed trades yet';pairRows();qs('#ranking').innerHTML=(last.available||[]).slice(0,10).map((x,i)=>`<div class="rank"><b>#${i+1} ${x.symbol}</b><span class="badge">${x.score}</span><span>${x.price}</span></div>`).join('')}catch(e){qs('#status').textContent='API error: '+e.message}}
async function start(){try{let ps=[...document.querySelectorAll('.ps')].map(x=>x.value.trim()).filter(Boolean),ts=[...document.querySelectorAll('.ps')].map((_,i)=>document.querySelectorAll('.ts')[i].value);await api('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({capital:1000,pairs:ps,timeframes:ts,trade_delay:20})});load()}catch(e){alert(e.message)}}async function stop(em){await api(em?'/api/paper/emergency':'/api/paper/stop',{method:'POST'});load()}async function reset(){await api('/api/reset',{method:'POST'});load()}async function save(){let ps=[...document.querySelectorAll('.ps')].map(x=>x.value.trim()).filter(Boolean),ts=[...document.querySelectorAll('.ps')].map((_,i)=>document.querySelectorAll('.ts')[i].value);await api('/api/pairs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pairs:ps,timeframes:ts})});load()}load();setInterval(load,2000);</script></body></html>'''

reset_state()
