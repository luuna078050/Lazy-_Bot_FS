from __future__ import annotations
import asyncio, random, time
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app=FastAPI(title='Fast Scalper v0.4.2 Repair')
BASES=['https://data-api.binance.vision','https://api1.binance.com','https://api2.binance.com','https://api3.binance.com','https://api.binance.com']
UNIVERSE=['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','TRXUSDT','LINKUSDT','SUIUSDT','AVAXUSDT','TONUSDT','LTCUSDT','DOTUSDT','ATOMUSDT','NEARUSDT','APTUSDT','ARBUSDT','OPUSDT','FILUSDT']
TFS=['1m','3m','5m','15m','30m']; TRADING_TF='3m'; MAX_SLOTS=6
RADAR_INTERVAL=20; ROTATE_SECONDS=60; MAX_POSITION_SECONDS=420; START_ACCOUNT=1850.0
S:dict[str,Any]={'running':False,'account':START_ACCOUNT,'bot':0.0,'free':0.0,'realized':0.0,'session_realized':0.0,'session_trades':0,'session_started':None,'positions':[],'closed':[],'orders':[],'ranking':[],'slots':[None]*MAX_SLOTS,'profit':0.0,'reinvest':False,'cycle':0,'started':None,'last_radar':0.0,'error':None,'source':None}
SEM=asyncio.Semaphore(8)
class Start(BaseModel): profit_pct:float=Field(0,ge=0,le=80); reinvest:bool=False
class Slots(BaseModel): slots:list[str]=Field(default_factory=list,max_length=MAX_SLOTS); profit_pct:float=Field(0,ge=0,le=80); reinvest:bool=False
class Amount(BaseModel): amount:float=Field(gt=0,le=1_000_000)
def now(): return datetime.now(timezone.utc).isoformat()
async def get_json(path,params=None):
    last=None
    for base in BASES:
        try:
            async with httpx.AsyncClient(timeout=7,headers={'User-Agent':'FastScalper/1.0'}) as c:
                r=await c.get(base+path,params=params)
                if r.status_code in (403,418,429): last=RuntimeError(f'HTTP {r.status_code}'); continue
                r.raise_for_status(); data=r.json(); S['source']=base; return data
        except Exception as e:last=e
    raise last or RuntimeError('No market-data endpoint available')
def ema(v,n):
    k=2/(n+1); x=v[0]
    for z in v[1:]:x=z*k+x*(1-k)
    return x
async def analyse(sym,tf):
    async with SEM: rows=await get_json('/api/v3/klines',{'symbol':sym,'interval':tf,'limit':40})
    c=[float(x[4]) for x in rows]
    if len(c)<21:raise RuntimeError('not enough candles')
    e9,e20=ema(c,9),ema(c,20); mom=(c[-1]/c[-6]-1)*100; trend=(e9/e20-1)*100
    return {'price':c[-1],'momentum':mom,'trend':trend,'score':max(0,min(100,50+trend*18+mom*7))}
async def build_ranking():
    tickers=await get_json('/api/v3/ticker/24hr'); by={x.get('symbol'):x for x in tickers if isinstance(x,dict)}
    cand=sorted(UNIVERSE,key=lambda s:float(by.get(s,{}).get('quoteVolume') or 0),reverse=True)[:12]
    async def one(sym):
        t=by.get(sym,{})
        rs=await asyncio.gather(*(analyse(sym,tf) for tf in TFS),return_exceptions=True); good=[x for x in rs if isinstance(x,dict)]
        if not good:return None
        score=sum(x['score'] for x in good)/len(good); mom=sum(x['momentum'] for x in good)/len(good)
        sig='BUY' if score>=55 and mom>0 else ('SELL' if score<=45 and mom<0 else 'WAIT')
        return {'symbol':sym,'price':float(t.get('lastPrice') or good[-1]['price']),'change':float(t.get('priceChangePercent') or 0),'volume':float(t.get('quoteVolume') or 0),'score':round(score,2),'signal':sig,'tf':TRADING_TF}
    rows=[x for x in await asyncio.gather(*(one(s) for s in cand)) if x]; rows.sort(key=lambda x:(x['score'],x['volume']),reverse=True); return rows[:15]
async def radar(force=False):
    if not force and S['last_radar'] and time.time()-S['last_radar']<RADAR_INTERVAL:return
    try:S['ranking']=await build_ranking(); S['last_radar']=time.time(); S['error']=None
    except Exception as e:S['error']=f'Radar: {type(e).__name__}: {e}'
def qprice(sym):
    q=next((x for x in S['ranking'] if x['symbol']==sym),None); return float(q['price']) if q else 0.0
def close_position(p,reason):
    ep=p['entry']; xp=(qprice(p['symbol']) or ep)*(1+random.uniform(-.0012,.0025)); pnl=(xp/ep-1)*p['stake']; S['free']+=p['stake']
    if S['reinvest']:S['free']+=pnl; S['bot']+=pnl
    else:S['account']+=pnl
    S['realized']+=pnl; S['session_realized']+=pnl; S['session_trades']+=1; S['closed'].insert(0,dict(p,exit=xp,pnl=pnl,reason=reason,closed_at=now())); S['closed']=S['closed'][:100]; S['orders'].insert(0,{'time':now(),'symbol':p['symbol'],'side':'SELL','status':'FILLED','price':xp,'slot':p['slot'],'pnl':pnl,'reason':reason}); S['positions'].remove(p)
def open_position(slot,sym):
    if not sym or S['free']<=0:return
    ep=qprice(sym)
    if ep<=0:return
    stake=min(S['free'],max(1.0,S['bot']/MAX_SLOTS)); score=next((x['score'] for x in S['ranking'] if x['symbol']==sym),0); S['free']-=stake
    p={'id':f'P{int(time.time()*1000)}','slot':slot,'symbol':sym,'tf':TRADING_TF,'entry':ep,'current':ep,'stake':stake,'score':score,'opened':time.time(),'opened_at':now()}; S['positions'].append(p); S['orders'].insert(0,{'time':now(),'symbol':sym,'side':'BUY','status':'FILLED','price':ep,'slot':slot,'score':score})
async def manage_positions():
    if not S['positions']:return
    try:
        ticks=await get_json('/api/v3/ticker/price'); latest={x.get('symbol'):float(x.get('price')) for x in ticks if isinstance(x,dict) and x.get('symbol')}
    except Exception:latest={}
    for p in list(S['positions']):
        p['current']=latest.get(p['symbol']) or qprice(p['symbol']) or p['current']; age=time.time()-p['opened']; live=(p['current']/p['entry']-1)*p['stake']; target=p['stake']*S['profit']/100
        if S['profit']>0 and live>=target:close_position(p,'PROFIT_TARGET')
        elif age>=MAX_POSITION_SECONDS:close_position(p,'TIMEOUT')
        elif age>=ROTATE_SECONDS:close_position(p,'ROTATION')
async def engine():
    while True:
        try:
            await manage_positions()
            if S['running']:
                S['cycle']+=1; await radar(); await manage_positions()
                for i,cfg in enumerate(S['slots']):
                    if cfg and not any(p['slot']==i for p in S['positions']):open_position(i,cfg['symbol'])
            await asyncio.sleep(1)
        except Exception as e:S['error']=f'Engine: {type(e).__name__}: {e}'; await asyncio.sleep(1)
@app.on_event('startup')
async def startup():asyncio.create_task(engine()); asyncio.create_task(radar(True))
@app.get('/',response_class=HTMLResponse)
async def home():return HTML
@app.get('/api/health')
async def health():return {'ok':True,'worker':'alive','running':S['running'],'cycle':S['cycle'],'positions':len(S['positions']),'radar_ok':bool(S['ranking']),'source':S['source'],'error':S['error']}
@app.get('/api/state')
async def state():
    unreal=sum((p['current']/p['entry']-1)*p['stake'] for p in S['positions']); return {'running':S['running'],'account':S['account'],'account_free':S['account'],'bot_balance':S['bot'],'free':S['free'],'realized':S['realized'],'session_realized':S['session_realized'],'session_trades':S['session_trades'],'unrealized':unreal,'net':S['realized']+unreal,'total_equity':S['account']+S['bot']+unreal,'withdraw_available':S['free'] if not S['running'] and not S['positions'] else 0.0,'positions':[dict(p) for p in S['positions']],'closed':S['closed'][:20],'orders':S['orders'][:20],'ranking':S['ranking'],'slots':S['slots'],'profit_pct':S['profit'],'reinvest':S['reinvest'],'cycle':S['cycle'],'started':S['started'],'session_started':S['session_started'],'radar_age':int(time.time()-S['last_radar']) if S['last_radar'] else 0,'error':S['error'],'source':S['source']}
@app.post('/api/paper/start')
async def start(b:Start):
    if S['positions']:raise HTTPException(400,'Close current positions before a new session')
    await radar(True)
    if not S['ranking']:raise HTTPException(503,'Radar is not ready: '+str(S['error'] or 'no market data'))
    S.update({'profit':b.profit_pct,'reinvest':b.reinvest,'running':True,'started':now(),'session_started':now(),'session_realized':0.0,'session_trades':0,'error':None})
    if not any(S['slots']):
        picks=[x['symbol'] for x in S['ranking'] if x['signal']=='BUY'][:MAX_SLOTS]
        if len(picks)<MAX_SLOTS:picks += [x['symbol'] for x in S['ranking'] if x['symbol'] not in picks][:MAX_SLOTS-len(picks)]
        S['slots']=[{'symbol':picks[i],'tf':TRADING_TF,'auto':True} if i<len(picks) else None for i in range(MAX_SLOTS)]
    return await state()
@app.post('/api/paper/stop')
async def stop():S['running']=False;return await state()
@app.post('/api/paper/emergency')
async def emergency():
    for p in list(S['positions']):close_position(p,'EMERGENCY_STOP')
    S['running']=False;S['started']=None;return await state()
@app.post('/api/reset')
async def reset():
    S.update({'running':False,'account':START_ACCOUNT,'bot':0.0,'free':0.0,'realized':0.0,'session_realized':0.0,'session_trades':0,'session_started':None,'positions':[],'closed':[],'orders':[],'ranking':[],'slots':[None]*MAX_SLOTS,'profit':0.0,'reinvest':False,'cycle':0,'started':None,'last_radar':0.0,'error':None});await radar(True);return await state()
@app.post('/api/slots')
async def slots(b:Slots):
    clean=[x.upper().replace('/','') for x in b.slots if x.strip()]; bad=[x for x in clean if x not in UNIVERSE]
    if len(clean)>MAX_SLOTS or bad:raise HTTPException(400,'Invalid pairs: '+','.join(bad))
    if S['positions']:raise HTTPException(400,'Close current positions before changing slots')
    S['slots']=[{'symbol':clean[i],'tf':TRADING_TF,'auto':False} if i<len(clean) else None for i in range(MAX_SLOTS)];S['profit']=b.profit_pct;S['reinvest']=b.reinvest;return await state()
@app.post('/api/strategy/allocate')
async def allocate(b:Amount):
    if S['running'] or S['positions']:raise HTTPException(400,'Allocation only after STOP and all positions are closed')
    total=S['account']+S['bot'];amount=float(b.amount)
    if amount>total+1e-9:raise HTTPException(400,'Insufficient capital')
    S['account']=total-amount;S['bot']=amount;S['free']=amount;return await state()
@app.post('/api/strategy/withdraw')
async def withdraw(b:Amount):
    if S['running'] or S['positions']:raise HTTPException(400,'Withdraw only after STOP and all positions are closed')
    amount=float(b.amount)
    if amount>S['free']+1e-9:raise HTTPException(400,f'Available: {S["free"]:.4f} USDT')
    S['bot']-=amount;S['free']-=amount;S['account']+=amount;return await state()
HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper</title><style>*{box-sizing:border-box}body{margin:0;background:#080e1b;color:#eef3ff;font-family:system-ui}.w{max-width:900px;margin:auto;padding:14px}.title{font-size:30px;font-weight:900}.muted{color:#8b97ae}.card{background:#121a2c;border:1px solid #293650;border-radius:16px;padding:14px;margin:10px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.stat{background:#0d1425;border-radius:10px;padding:10px}.v{font-size:19px;font-weight:850}.row{display:flex;gap:8px;flex-wrap:wrap}.input{background:#0b1322;color:#fff;border:1px solid #30405f;border-radius:9px;padding:10px;flex:1;min-width:120px}.btn{border:0;border-radius:10px;padding:11px 15px;color:#fff;font-weight:850;background:#273650}.on{background:#078b53}.stop{background:#a72e3f}.grid6{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.slot{background:#0d1425;border:1px solid #293753;border-radius:10px;padding:9px}.rank{display:grid;grid-template-columns:26px 1fr 70px 60px 58px;gap:6px;align-items:center;padding:8px;border-bottom:1px solid #24314a}.badge{border-radius:7px;padding:3px 5px;text-align:center;background:#08764e}.good{color:#40df8b}.bad{color:#ff6576}@media(max-width:650px){.stats{grid-template-columns:repeat(2,1fr)}.grid6{grid-template-columns:repeat(2,1fr)}.rank{grid-template-columns:24px 1fr 62px 54px 52px;font-size:13px}}details summary{cursor:pointer;font-weight:850}</style></head><body><div class="w"><div class="title">⚡ Fast Scalper</div><div class="muted">v0.4.2 REPAIR · Multi-TF 1m · 3m · 5m · 15m · 30m · Trading TF: 3m · PAPER</div><div class="card"><div class="stats"><div class="stat">Account Balance<div class="v" id="a">—</div></div><div class="stat">Realized PnL<div class="v" id="r">—</div></div><div class="stat">Session PnL<div class="v" id="sr">—</div></div><div class="stat">Bot Balance<div class="v" id="b">—</div></div></div></div><div class="card"><h3>Paper controls</h3><div class="row"><input id="p" class="input" type="number" step=".01" value="3.5" placeholder="Profit %"><label class="input" style="flex:0 0 auto;min-width:150px;display:flex;align-items:center;gap:8px"><input id="reinvest" type="checkbox"> Reinvest</label><button class="btn on" onclick="start()">PAPER ON</button><button class="btn stop" onclick="stop()">PAPER OFF</button><button class="btn stop" onclick="emergency()">EMERGENCY</button><button class="btn" onclick="reset()">RESET</button></div><div class="muted">Profit is a target. Rotation: 60s. Timeout: 420s. STOP blocks new entries but never freezes existing positions.</div></div><div class="card"><h3>Capital</h3><div class="row"><input id="amt" class="input" type="number" step=".01" placeholder="USDT"><button class="btn" onclick="alloc()">SET BOT</button><button class="btn" onclick="withdraw()">WITHDRAW</button></div><div class="muted" id="cap">—</div></div><div class="card"><h3>Slots · TOP-6</h3><div class="grid6">${[0,1,2,3,4,5].map(i=>`<input id="slot${i}" class="input" placeholder="#${i+1} pair (e.g. SOLUSDT)">`).join('')}</div><div class="row" style="margin-top:10px"><button class="btn on" onclick="setSlots()">SET PAIRS</button><button class="btn" onclick="autoSlots()">AUTO TOP-6</button></div><div class="muted">Enter up to 6 pairs. PAPER ON will also auto-fill TOP-6 if all slots are empty.</div></div><div class="card"><h3>Radar · TOP-15</h3><div id="radar">—</div></div><div class="card"><h3>Open Positions</h3><div id="pos">—</div></div><div class="card"><h3>Closed Trades — latest 8</h3><div id="closed">—</div></div><div class="card"><details><summary>Status / diagnostics</summary><pre id="diag" class="muted" style="white-space:pre-wrap"></pre></details></div></div><script>async function api(u,o={}){let r=await fetch(u,{headers:{'Content-Type':'application/json'},...o});let j=await r.json();if(!r.ok)throw Error(j.detail||'HTTP '+r.status);return j}function vals(){return [0,1,2,3,4,5].map(i=>document.getElementById('slot'+i).value.trim().toUpperCase()).filter(Boolean)}async function refresh(){try{let j=await api('/api/state');a.textContent=j.account.toFixed(4);r.textContent=j.realized.toFixed(4);sr.textContent=j.session_realized.toFixed(4);b.textContent=j.bot_balance.toFixed(4);cap.textContent=`Account free: ${j.account_free.toFixed(4)} · Bot free: ${j.free.toFixed(4)} · Total equity: ${j.total_equity.toFixed(4)} · Withdraw available: ${j.withdraw_available.toFixed(4)}`;document.getElementById('reinvest').checked=j.reinvest;j.slots.forEach((x,i)=>{document.getElementById('slot'+i).value=x?x.symbol:''});radar.innerHTML=j.ranking.map((x,i)=>`<div class="rank"><b>${i+1}</b><b>${x.symbol}</b><span>${x.price.toFixed(2)}</span><span>${x.score.toFixed(2)}%</span><span class="badge">${x.signal}</span></div>`).join('')||'No radar data';pos.innerHTML=j.positions.map(x=>`<div>${x.symbol} · stake ${x.stake.toFixed(4)} · age ${Math.floor(Date.now()/1000-x.opened)}s · live ${((x.current/x.entry-1)*100).toFixed(3)}%</div>`).join('')||'<span class="muted">No open positions</span>';closed.innerHTML=j.closed.slice(0,8).map(x=>`<div>${x.symbol} · ${x.reason} · <span class="${x.pnl>=0?'good':'bad'}">${x.pnl.toFixed(4)} USDT</span></div>`).join('')||'—';diag.textContent=JSON.stringify({engine:j.running?'ON':'OFF',cycle:j.cycle,positions:j.positions.length,reinvest:j.reinvest,source:j.source,radar_age:j.radar_age,error:j.error},null,2)}catch(e){diag.textContent='UI/API error: '+e.message}}async function start(){try{let j=await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:parseFloat(p.value||0),reinvest:document.getElementById('reinvest').checked})});await refresh()}catch(e){alert(e.message)}}async function stop(){try{await api('/api/paper/stop',{method:'POST'});await refresh()}catch(e){alert(e.message)}}async function emergency(){try{await api('/api/paper/emergency',{method:'POST'});await refresh()}catch(e){alert(e.message)}}async function reset(){try{await api('/api/reset',{method:'POST'});await refresh()}catch(e){alert(e.message)}}async function setSlots(){try{await api('/api/slots',{method:'POST',body:JSON.stringify({slots:vals(),profit_pct:parseFloat(p.value||0),reinvest:document.getElementById('reinvest').checked})});await refresh()}catch(e){alert(e.message)}}async function autoSlots(){try{let j=await api('/api/state');let picks=j.ranking.filter(x=>x.signal==='BUY').slice(0,6).map(x=>x.symbol);if(picks.length<6)j.ranking.forEach(x=>{if(picks.length<6&&!picks.includes(x.symbol))picks.push(x.symbol)});[0,1,2,3,4,5].forEach(i=>document.getElementById('slot'+i).value=picks[i]||'');await setSlots()}catch(e){alert(e.message)}}async function alloc(){try{await api('/api/strategy/allocate',{method:'POST',body:JSON.stringify({amount:parseFloat(amt.value)})});await refresh()}catch(e){alert(e.message)}}async function withdraw(){try{await api('/api/strategy/withdraw',{method:'POST',body:JSON.stringify({amount:parseFloat(amt.value)})});await refresh()}catch(e){alert(e.message)}}document.getElementById('reinvest').addEventListener('change',async()=>{try{await setSlots()}catch(e){alert(e.message)}});refresh();setInterval(refresh,1000)</script></body></html>'''
