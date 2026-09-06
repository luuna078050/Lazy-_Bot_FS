from __future__ import annotations
import asyncio, random, time
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app=FastAPI(title='Fast Scalper v0.4.1 Repair')
BASE='https://data-api.binance.vision'
UNIVERSE=['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','TRXUSDT','LINKUSDT','SUIUSDT','AVAXUSDT','TONUSDT','LTCUSDT','DOTUSDT','ATOMUSDT','NEARUSDT','APTUSDT','ARBUSDT','OPUSDT','FILUSDT']
TFS=['1m','3m','5m','15m','30m']; TRADING_TF='3m'; MAX_SLOTS=6
ROTATE_SECONDS=60; MAX_POSITION_SECONDS=420; RADAR_INTERVAL=20
START_ACCOUNT=1850.0; START_BOT=0.0
S:dict[str,Any]={'running':False,'account':START_ACCOUNT,'bot':START_BOT,'free':START_BOT,'realized':0.0,'session_realized':0.0,'session_trades':0,'session_started':None,'positions':[],'closed':[],'orders':[],'slots':[None]*MAX_SLOTS,'profit':0.0,'reinvest':False,'cycle':0,'started':None,'last_radar':0.0,'error':None,'source':None}

class Start(BaseModel): profit_pct:float=Field(0,ge=0,le=80); reinvest:bool=False
class Slots(BaseModel): slots:list[str]=Field(default_factory=list,max_length=MAX_SLOTS); profit_pct:float=Field(0,ge=0,le=80); reinvest:bool=False
class Amount(BaseModel): amount:float=Field(gt=0,le=1_000_000)


def now(): return datetime.now(timezone.utc).isoformat()
async def get_json(path,params=None):
    async with httpx.AsyncClient(timeout=6) as c:
        r=await c.get(BASE+path,params=params); r.raise_for_status(); S['source']=BASE; return r.json()

def ema(v,n):
    k=2/(n+1); x=v[0]
    for z in v[1:]: x=z*k+x*(1-k)
    return x

async def analyse(sym,tf):
    rows=await get_json('/api/v3/klines',{'symbol':sym,'interval':tf,'limit':40}); c=[float(x[4]) for x in rows]
    e9,e20=ema(c,9),ema(c,20); mom=(c[-1]/c[-6]-1)*100; trend=(e9/e20-1)*100
    score=max(0,min(100,50+trend*18+mom*7)); sig='BUY' if e9>e20 and mom>0 else ('SELL' if e9<e20 and mom<0 else 'WAIT')
    return {'price':c[-1],'momentum':mom,'trend':trend,'score':score,'signal':sig}

async def build_ranking():
    tickers=await get_json('/api/v3/ticker/24hr'); by={x['symbol']:x for x in tickers if isinstance(x,dict) and 'symbol' in x}
    out=[]
    for sym in UNIVERSE:
        rs=await asyncio.gather(*(analyse(sym,tf) for tf in TFS),return_exceptions=True); good=[x for x in rs if isinstance(x,dict)]
        if not good: continue
        score=sum(x['score'] for x in good)/len(good); mom=sum(x['momentum'] for x in good)/len(good)
        sig='BUY' if score>=55 and mom>0 else ('SELL' if score<=45 and mom<0 else 'WAIT')
        t=by.get(sym,{})
        out.append({'symbol':sym,'price':float(t.get('lastPrice') or good[-1]['price']),'change':float(t.get('priceChangePercent') or 0),'volume':float(t.get('quoteVolume') or 0),'score':round(score,2),'signal':sig,'tf':TRADING_TF})
    out.sort(key=lambda x:(x['score'],x['volume']),reverse=True); return out[:15]

async def radar(force=False):
    if not force and S['last_radar'] and time.time()-S['last_radar']<RADAR_INTERVAL:return
    try:S['ranking']=await build_ranking(); S['last_radar']=time.time(); S['error']=None
    except Exception as e:S['error']=f'Radar: {type(e).__name__}: {e}'

def qprice(sym):
    q=next((x for x in S['ranking'] if x['symbol']==sym),None); return float(q['price']) if q else 0.0

def close_position(p,reason):
    ep=p['entry']; base=qprice(p['symbol']) or ep; xp=base*(1+random.uniform(-.0012,.0025)); pnl=(xp/ep-1)*p['stake']
    S['free']+=p['stake']
    if S['reinvest']:
        S['free']+=pnl; S['bot']+=pnl
    else:S['account']+=pnl
    S['realized']+=pnl; S['session_realized']+=pnl; S['session_trades']+=1
    z=dict(p,exit=xp,pnl=pnl,reason=reason,closed_at=now()); S['closed'].insert(0,z); S['closed']=S['closed'][:100]
    S['orders'].insert(0,{'time':now(),'symbol':p['symbol'],'side':'SELL','price':xp,'pnl':pnl,'reason':reason,'slot':p['slot']}); S['positions'].remove(p)

def open_position(slot,sym):
    if not sym or S['free']<=0:return
    ep=qprice(sym)
    if ep<=0:return
    stake=min(S['free'],max(1.0,S['bot']/MAX_SLOTS)); score=next((x['score'] for x in S['ranking'] if x['symbol']==sym),0); S['free']-=stake
    p={'id':f'P{int(time.time()*1000)}','slot':slot,'symbol':sym,'tf':TRADING_TF,'entry':ep,'current':ep,'stake':stake,'score':score,'opened':time.time(),'opened_at':now()}; S['positions'].append(p)
    S['orders'].insert(0,{'time':now(),'symbol':sym,'side':'BUY','price':ep,'slot':slot,'score':score})

async def manage_positions():
    # Management is deliberately independent of running/radar: STOP cannot freeze an open position.
    for p in list(S['positions']):
        q=next((x for x in S['ranking'] if x['symbol']==p['symbol']),None)
        if q:p['current']=q['price']
        age=time.time()-p['opened']; live=(p['current']/p['entry']-1)*p['stake']; target=p['stake']*S['profit']/100
        if S['profit']>0 and live>=target: close_position(p,'PROFIT_TARGET')
        elif age>=MAX_POSITION_SECONDS: close_position(p,'TIMEOUT')
        elif age>=ROTATE_SECONDS: close_position(p,'ROTATION')

async def engine():
    while True:
        try:
            # Always manage existing positions, even after PAPER OFF.
            if S['positions']: await manage_positions()
            if S['running']:
                S['cycle']+=1; await radar()
                # Re-check after fresh radar.
                await manage_positions()
                for i,cfg in enumerate(S['slots']):
                    if cfg and not any(p['slot']==i for p in S['positions']): open_position(i,cfg['symbol'])
            await asyncio.sleep(1)
        except Exception as e:S['error']=f'Engine: {type(e).__name__}: {e}'; await asyncio.sleep(1)

@app.on_event('startup')
async def startup(): asyncio.create_task(engine()); asyncio.create_task(radar(True))

@app.get('/',response_class=HTMLResponse)
async def home(): return HTML
@app.get('/api/health')
async def health(): return {'ok':True,'running':S['running'],'positions':len(S['positions']),'cycle':S['cycle'],'error':S['error']}
@app.get('/api/state')
async def state():
    unreal=sum((p['current']/p['entry']-1)*p['stake'] for p in S['positions'])
    return {'running':S['running'],'account':S['account'],'account_free':S['account'],'bot_balance':S['bot'],'free':S['free'],'realized':S['realized'],'session_realized':S['session_realized'],'session_trades':S['session_trades'],'unrealized':unreal,'net':S['realized']+unreal,'total_equity':S['account']+S['bot']+unreal,'withdraw_available':S['free'] if not S['running'] and not S['positions'] else 0.0,'positions':S['positions'],'closed':S['closed'][:20],'orders':S['orders'][:20],'ranking':S['ranking'],'slots':S['slots'],'profit_pct':S['profit'],'reinvest':S['reinvest'],'cycle':S['cycle'],'started':S['started'],'session_started':S['session_started'],'radar_age':int(time.time()-S['last_radar']) if S['last_radar'] else 0,'error':S['error']}
@app.post('/api/paper/start')
async def start(b:Start):
    if S['positions']: raise HTTPException(400,'Close current positions before a new session')
    S.update({'profit':b.profit_pct,'reinvest':b.reinvest,'running':True,'started':now(),'session_started':now(),'session_realized':0.0,'session_trades':0,'error':None}); await radar(True); return await state()
@app.post('/api/paper/stop')
async def stop():
    # Graceful stop: no new positions. Existing positions remain under the same profit/rotation/timeout rules.
    S['running']=False; return await state()
@app.post('/api/paper/emergency')
async def emergency():
    for p in list(S['positions']): close_position(p,'EMERGENCY_STOP')
    S['running']=False; S['started']=None; return await state()
@app.post('/api/reset')
async def reset():
    S.update({'running':False,'account':START_ACCOUNT,'bot':START_BOT,'free':START_BOT,'realized':0.0,'session_realized':0.0,'session_trades':0,'session_started':None,'positions':[],'closed':[],'orders':[],'slots':[None]*MAX_SLOTS,'profit':0.0,'reinvest':False,'cycle':0,'started':None,'error':None}); await radar(True); return await state()
@app.post('/api/slots')
async def slots(b:Slots):
    clean=[x.upper().replace('/','') for x in b.slots if x.strip()]
    bad=[x for x in clean if x not in UNIVERSE]
    if len(clean)>MAX_SLOTS or bad: raise HTTPException(400,'Invalid slots')
    S['slots']=[{'symbol':clean[i],'tf':TRADING_TF,'auto':False} if i<len(clean) else None for i in range(MAX_SLOTS)]; S['profit']=b.profit_pct; S['reinvest']=b.reinvest; return await state()
@app.post('/api/strategy/allocate')
async def allocate(b:Amount):
    if S['running'] or S['positions']: raise HTTPException(400,'Allocation only after STOP and all positions closed')
    total=S['account']+S['bot']; amount=float(b.amount)
    if amount>total+1e-9: raise HTTPException(400,'Insufficient capital')
    S['account']=total-amount; S['bot']=amount; S['free']=amount; return await state()
@app.post('/api/strategy/withdraw')
async def withdraw(b:Amount):
    if S['running'] or S['positions']: raise HTTPException(400,'Withdraw only after STOP and all positions closed')
    amount=float(b.amount)
    if amount>S['free']+1e-9: raise HTTPException(400,f'Available: {S["free"]:.4f} USDT')
    S['bot']-=amount; S['free']-=amount; S['account']+=amount; return await state()

HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper v0.4.1 Repair</title><style>body{margin:0;background:#080e1b;color:#eef3ff;font-family:system-ui}.w{max-width:850px;margin:auto;padding:14px}.card{background:#121a2c;border:1px solid #293650;border-radius:16px;padding:14px;margin:10px 0}.title{font-size:28px;font-weight:850}.muted{color:#8b97ae}.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.stat{background:#0d1425;border-radius:10px;padding:10px}.v{font-size:19px;font-weight:800}.row{display:flex;gap:8px;flex-wrap:wrap}.input{background:#0b1322;color:#fff;border:1px solid #30405f;border-radius:9px;padding:10px;flex:1;min-width:130px}.btn{border:0;border-radius:10px;padding:11px 15px;color:white;font-weight:800;background:#273650}.on{background:#078b53}.stop{background:#a72e3f}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.pos,.trade{padding:8px;border-bottom:1px solid #24314a}.good{color:#32d583}.bad{color:#ff6675}</style></head><body><div class=w><div class=title>⚡ Fast Scalper</div><div class=muted>v0.4.1 REPAIR · Multi-TF 1m · 3m · 5m · 15m · 30m · Trading TF: 3m · PAPER</div><div class=card><div class=stats><div class=stat>Account Balance<div class=v id=a>—</div></div><div class=stat>Realized PnL<div class=v id=r>—</div></div><div class=stat>Session PnL<div class=v id=sr>—</div></div><div class=stat>Bot Balance<div class=v id=b>—</div></div></div></div><div class=card><b>Paper controls</b><div class=row><input id=p class=input type=number step=.01 value=3.5 placeholder="Profit %"><button class="btn on" onclick=start()>PAPER ON</button><button class="btn stop" onclick=stop()>PAPER OFF</button><button class="btn stop" onclick=emergency()>EMERGENCY</button><button class=btn onclick=reset()>RESET</button></div><div class=muted>Profit is a target. Rotation: 60s. Timeout: 420s. STOP blocks new entries but never freezes existing positions.</div></div><div class=card><b>Capital</b><div class=row><input id=amt class=input type=number step=.01 placeholder="USDT"><button class=btn onclick=alloc()>SET BOT</button><button class=btn onclick=withdraw()>WITHDRAW</button></div></div><div class=card><b>Open Positions</b><div id=pos>—</div></div><div class=card><b>Closed Trades — latest 8</b><div id=closed>—</div></div><div class=card><b>Status</b><div id=s>—</div></div></div><script>async function api(u,o){let r=await fetch(u,o);let j=await r.json();if(!r.ok)alert(j.detail||'Error');return j}async function refresh(){let j=await api('/api/state');a.textContent=(j.account||0).toFixed(4);r.textContent=(j.realized||0).toFixed(4);sr.textContent=(j.session_realized||0).toFixed(4);b.textContent=(j.bot_balance||0).toFixed(4);s.textContent=(j.running?'ENGINE ON':'ENGINE OFF')+' · cycle '+j.cycle+' · positions '+j.positions.length+' · session '+(j.session_started?'active':'stopped');pos.innerHTML=j.positions.map(x=>'<div class=pos>'+x.symbol+' · stake '+x.stake.toFixed(4)+' · age '+Math.floor((Date.now()/1000-x.opened))+'s · score '+x.score+'</div>').join('')||'<span class=muted>No open positions</span>';closed.innerHTML=j.closed.map(x=>'<div class=trade>'+x.symbol+' · '+x.reason+' · <span class='+(x.pnl>=0?'good':'bad')+'>'+x.pnl.toFixed(4)+' USDT</span></div>').join('')||'<span class=muted>No closed trades</span>'}async function start(){await api('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profit_pct:+p.value,reinvest:true})});refresh()}async function stop(){await api('/api/paper/stop',{method:'POST'});refresh()}async function emergency(){await api('/api/paper/emergency',{method:'POST'});refresh()}async function reset(){await api('/api/reset',{method:'POST'});refresh()}async function alloc(){await api('/api/strategy/allocate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount:+amt.value})});refresh()}async function withdraw(){await api('/api/strategy/withdraw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount:+amt.value})});refresh()}setInterval(refresh,1000);refresh()</script></body></html>'''
