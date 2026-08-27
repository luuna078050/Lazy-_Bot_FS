from __future__ import annotations
import asyncio, time, uuid
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app=FastAPI(title='Fast Scalper — New Start')
BINANCE='https://api.binance.com'; MAX_SLOTS=10; DEFAULT_BALANCE=1000.0
state={'running':False,'mode':'PAPER','balance':DEFAULT_BALANCE,'free_balance':DEFAULT_BALANCE,'realized':0.0,'trades':[],'positions':{},'orders':{},'pairs':[None]*MAX_SLOTS,'last_error':None,'started_at':None,'last_cycle':None,'cycle_count':0}
lock=asyncio.Lock()
def now(): return datetime.now(timezone.utc).isoformat()
async def bj(path,params=None):
    async with httpx.AsyncClient(timeout=8) as c:
        r=await c.get(BINANCE+path,params=params); r.raise_for_status(); return r.json()
async def kl(symbol,tf='1m',limit=30): return await bj('/api/v3/klines',{'symbol':symbol,'interval':tf,'limit':limit})
def ema(v,n):
    k=2/(n+1); x=v[0]
    for z in v[1:]: x=z*k+x*(1-k)
    return x
async def analyse(symbol,tf):
    rows=await kl(symbol,tf,30); c=[float(x[4]) for x in rows]
    if len(c)<20:return None
    e9,e20=ema(c,9),ema(c,20); mom=(c[-1]/c[-6]-1)*100; trend=(e9/e20-1)*100
    score=max(0,min(100,50+trend*20+mom*8)); return {'price':c[-1],'momentum':mom,'trend':trend,'score':score,'signal':'BUY' if e9>e20 and mom>0 else 'WAIT'}
def snap():
    pos=[]; unreal=0
    for p in state['positions'].values():
        pnl=(p['current_price']/p['entry_price']-1)*p['stake']; unreal+=pnl; q=dict(p); q['unrealized_pnl']=pnl; pos.append(q)
    return {'running':state['running'],'mode':state['mode'],'balance':state['balance'],'free_balance':state['free_balance'],'allocated':state['balance']-state['free_balance'],'realized_pnl':state['realized'],'unrealized_pnl':unreal,'net_pnl':state['realized']+unreal,'positions':pos,'orders':list(state['orders'].values()),'trades':state['trades'][:50],'pairs':state['pairs'],'last_error':state['last_error'],'last_cycle':state['last_cycle'],'cycle_count':state['cycle_count'],'started_at':state['started_at']}
async def open_trade(symbol,tf,price,stake,score):
    state['free_balance']-=stake; state['positions'][symbol]={'id':str(uuid.uuid4())[:8],'symbol':symbol,'timeframe':tf,'entry_price':price,'current_price':price,'stake':stake,'opened_at':now(),'score':score}; state['orders'][symbol]={'symbol':symbol,'side':'BUY','status':'FILLED','price':price,'time':now()}
async def close_trade(symbol,price,reason):
    p=state['positions'].pop(symbol); pnl=(price/p['entry_price']-1)*p['stake']; state['free_balance']+=p['stake']+pnl; state['realized']+=pnl; state['balance']+=pnl; state['orders'][symbol]={'symbol':symbol,'side':'SELL','status':'FILLED','price':price,'time':now()}; state['trades'].insert(0,{'id':p['id'],'symbol':symbol,'timeframe':p['timeframe'],'entry':p['entry_price'],'exit':price,'stake':p['stake'],'pnl':pnl,'reason':reason,'opened_at':p['opened_at'],'closed_at':now()}); state['trades']=state['trades'][:100]
async def cycle():
    if not state['running']: return
    async with lock:
        state['cycle_count']+=1; state['last_cycle']=now(); selected=[x for x in state['pairs'] if x]; state['last_error']=None
    for item in selected:
        try:
            a=await analyse(item['symbol'],item['timeframe'])
            if not a: continue
            async with lock:
                sym,tf=item['symbol'],item['timeframe']; p=state['positions'].get(sym)
                if p:
                    p['current_price']=a['price']; pnl=(a['price']/p['entry_price']-1)*p['stake']; age=time.time()-datetime.fromisoformat(p['opened_at']).timestamp()
                    if pnl>=p['stake']*.002 or age>={'1m':90,'3m':210,'5m':330}.get(tf,210) or (a['trend']<-.03 and pnl>0): await close_trade(sym,a['price'],'TP/TIME/TREND')
                elif state['free_balance']>=20 and a['signal']=='BUY' and a['score']>=50: await open_trade(sym,tf,a['price'],min(50,state['free_balance']),a['score'])
        except Exception as e:
            async with lock: state['last_error']=f"{item['symbol']}: {type(e).__name__}: {e}"
async def worker():
    while True:
        try: await cycle()
        except Exception as e: state['last_error']=f'engine: {e}'
        await asyncio.sleep(5)
async def keepalive():
    while True: await asyncio.sleep(30)
@app.on_event('startup')
async def startup(): asyncio.create_task(worker()); asyncio.create_task(keepalive())
class Pair(BaseModel): symbol:str=Field(pattern=r'^[A-Z0-9]+USDT$'); timeframe:str=Field(pattern=r'^(1m|3m|5m)$')
class PairSet(BaseModel): pairs:list[Pair]=Field(default_factory=list,max_length=10)
@app.get('/api/health')
async def health(): return {'ok':True,'running':state['running'],'cycle_count':state['cycle_count'],'time':now()}
@app.get('/api/state')
async def api_state():
    async with lock:return snap()
@app.post('/api/pairs')
async def pairs(body:PairSet):
    seen=set()
    for p in body.pairs:
        k=(p.symbol,p.timeframe)
        if k in seen: raise HTTPException(400,'Duplicate pair + timeframe')
        seen.add(k)
    async with lock:
        state['pairs']=[None]*MAX_SLOTS
        for i,p in enumerate(body.pairs): state['pairs'][i]=p.model_dump()
    return snap()
@app.post('/api/paper/start')
async def start():
    async with lock: state['mode']='PAPER'; state['running']=True; state['started_at']=state['started_at'] or now(); state['last_error']=None
    return snap()
@app.post('/api/paper/stop')
async def stop():
    async with lock: state['running']=False
    return snap()
@app.post('/api/reset')
async def reset():
    async with lock: state.update({'running':False,'balance':DEFAULT_BALANCE,'free_balance':DEFAULT_BALANCE,'realized':0.0,'trades':[],'positions':{},'orders':{},'pairs':[None]*MAX_SLOTS,'last_error':None,'started_at':None,'last_cycle':None,'cycle_count':0})
    return snap()
HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper — New Start</title><style>body{font-family:Arial;background:#0b1020;color:#eef2ff;margin:0;padding:14px}.w{max-width:1100px;margin:auto}.top,.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.top{grid-template-columns:repeat(5,1fr)}.c{background:#141b2d;border:1px solid #28334d;border-radius:12px;padding:10px;margin-top:8px}.v{font-size:19px;font-weight:700}.m{color:#8e9ab5;font-size:12px}.controls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}.b{border:0;border-radius:10px;padding:11px;font-weight:bold;background:#26324b;color:#fff}.on{background:#087c4d}.danger{background:#9d2d3d}.slot{display:grid;grid-template-columns:1fr 75px;gap:5px}.slot input,.slot select{background:#0d1424;color:#fff;border:1px solid #2c3852;border-radius:8px;padding:8px;width:100%;box-sizing:border-box}.t{width:100%;border-collapse:collapse}.t td,.t th{padding:7px;border-bottom:1px solid #273149;font-size:12px;text-align:left}.g{color:#42e28a}.r{color:#ff6873}@media(max-width:700px){.top{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}</style></head><body><div class="w"><h2>Fast Scalper — New Start</h2><div class="m">Clean runtime • PAPER first • empty pair selection</div><div class="top"><div class="c"><div class="m">Account Balance</div><div class="v" id="bal">—</div></div><div class="c"><div class="m">Realized PnL</div><div class="v" id="real">—</div></div><div class="c"><div class="m">Unrealized PnL</div><div class="v" id="unreal">—</div></div><div class="c"><div class="m">Net PnL</div><div class="v" id="net">—</div></div><div class="c"><div class="m">Free Balance</div><div class="v" id="free">—</div></div></div><div class="c controls"><button class="b" id="pb" onclick="paper()">PAPER OFF</button><button class="b danger" onclick="stop()">EMERGENCY STOP</button><button class="b" onclick="resetAll()">RESET</button></div><div class="c"><b>Pairs</b><div class="m">Up to 10 • same pair may be used on different timeframes.</div><div class="grid" id="slots"></div><button class="b" style="margin-top:8px" onclick="save()">SAVE PAIRS</button></div><div class="c"><b>Open Positions</b><table class="t"><tbody id="pos"></tbody></table></div><div class="c"><b>Session Result</b><div id="session" class="m">No trades yet.</div></div><div class="c"><b>Closed Trades — latest 5</b><table class="t"><tbody id="trades"></tbody></table></div><div class="c m" id="status">Engine OFF</div></div><script>const $=x=>document.getElementById(x);function build(){slots.innerHTML='';for(let i=0;i<10;i++)slots.innerHTML+=`<div class="slot"><input id="s${i}" placeholder="BTCUSDT"><select id="t${i}"><option>3m</option><option>1m</option><option>5m</option></select></div>`}build();async function j(u,o){let r=await fetch(u,o),d=await r.json();if(!r.ok)throw Error(d.detail||'request failed');return d}function money(x){return Number(x||0).toFixed(2)+' USDT'}async function paper(){render(await j('/api/paper/start',{method:'POST'}))}async function stop(){render(await j('/api/paper/stop',{method:'POST'}))}async function resetAll(){build();render(await j('/api/reset',{method:'POST'}))}async function save(){let p=[];for(let i=0;i<10;i++){let s=$('s'+i).value.trim().toUpperCase();if(s)p.push({symbol:s,timeframe:$('t'+i).value})}render(await j('/api/pairs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pairs:p})}))}function render(d){bal.textContent=money(d.balance);real.textContent=money(d.realized_pnl);unreal.textContent=money(d.unrealized_pnl);net.textContent=money(d.net_pnl);free.textContent=money(d.free_balance);pb.textContent=d.running?'PAPER ON':'PAPER OFF';pb.className='b '+(d.running?'on':'');status.textContent=d.running?`RUNNING • cycle ${d.cycle_count} • ${d.last_cycle||'—'}`:'Engine OFF';if(d.last_error)status.textContent+=' • ERROR: '+d.last_error;pos.innerHTML=d.positions.map(x=>`<tr><td>${x.symbol} ${x.timeframe}</td><td>${x.entry_price}</td><td>${x.current_price}</td><td class="${x.unrealized_pnl>=0?'g':'r'}">${money(x.unrealized_pnl)}</td></tr>`).join('')||'<tr><td>No open positions</td></tr>';trades.innerHTML=d.trades.slice(0,5).map(x=>`<tr><td>${x.symbol}</td><td>${x.timeframe}</td><td>${x.entry}</td><td>${x.exit}</td><td class="${x.pnl>=0?'g':'r'}">${money(x.pnl)}</td></tr>`).join('')||'<tr><td>No closed trades yet</td></tr>';session.textContent=`Trades: ${d.trades.length} • Open: ${d.positions.length} • Realized: ${money(d.realized_pnl)} • Unrealized: ${money(d.unrealized_pnl)}`}async function refresh(){try{render(await j('/api/state'))}catch(e){status.textContent='Connection error: '+e.message}}refresh();setInterval(refresh,2000);setInterval(()=>fetch('/api/health').catch(()=>{}),20000)</script></body></html>'''
@app.get('/',response_class=HTMLResponse)
async def root(): return HTMLResponse(HTML,headers={'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0'})
