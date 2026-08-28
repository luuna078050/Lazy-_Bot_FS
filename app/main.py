from __future__ import annotations
import asyncio,time,uuid
from datetime import datetime,timezone
from typing import Any
import httpx
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field
app=FastAPI(title='Fast Scalper — New Start')
BINANCE='https://api.binance.com';BAL=1000.0;N=6;R=10
S={'running':False,'balance':BAL,'free':BAL,'real':0.0,'positions':{},'trades':[],'orders':[],'pairs':[],'radar':[],'err':None,'started':None,'cycle':0,'rotation':None,'rotsec':20}
lock=asyncio.Lock()
def now():return datetime.now(timezone.utc).isoformat()
async def api(path,params=None):
 async with httpx.AsyncClient(timeout=8) as c:
  r=await c.get(BINANCE+path,params=params);r.raise_for_status();return r.json()
def ema(a,n):
 k=2/(n+1);x=a[0]
 for v in a[1:]:x=v*k+x*(1-k)
 return x
async def analyse(sym,tf):
 rows=await api('/api/v3/klines',{'symbol':sym,'interval':tf,'limit':40});c=[float(x[4]) for x in rows]
 if len(c)<21:return None
 e9,e20=ema(c,9),ema(c,20);mom=(c[-1]/c[-6]-1)*100;trend=(e9/e20-1)*100;score=max(0,min(100,50+trend*18+mom*7));return {'price':c[-1],'momentum':mom,'trend':trend,'score':score,'signal':'BUY' if e9>e20 and mom>0 else 'WAIT'}
async def make_radar():
 t=await api('/api/v3/ticker/24hr');a=[]
 for x in t:
  sym=x.get('symbol','')
  if not sym.endswith('USDT') or sym.endswith(('UPUSDT','DOWNUSDT','BULLUSDT','BEARUSDT')):continue
  try:v=float(x['quoteVolume']);chg=float(x['priceChangePercent']);price=float(x['lastPrice'])
  except:continue
  if v<5e6 or price<=0:continue
  rating=max(0,min(100,50+chg*2+min(v/1e8,20)));a.append({'symbol':sym,'price':price,'change':chg,'volume':v,'rating':round(rating,1)})
 a.sort(key=lambda x:(x['rating'],x['volume']),reverse=True);return a[:R]
def snap():
 pos=[];un=0
 for p in S['positions'].values():
  pnl=(p['current']/p['entry']-1)*p['stake'];un+=pnl;q=dict(p);q['pnl']=pnl;pos.append(q)
 left=0
 if S['running'] and S['rotation']:left=max(0,S['rotsec']-int(time.time()-S['rotation']))
 return {'running':S['running'],'balance':S['balance'],'free':S['free'],'real':S['real'],'unreal':un,'net':S['real']+un,'positions':pos,'trades':S['trades'][:50],'orders':S['orders'][:20],'pairs':S['pairs'],'radar':S['radar'],'err':S['err'],'cycle':S['cycle'],'last_cycle':S.get('last_cycle'),'started':S['started'],'left':left}
async def openp(sym,tf,price,stake,score):
 S['free']-=stake;S['positions'][sym]={'id':str(uuid.uuid4())[:8],'symbol':sym,'timeframe':tf,'entry':price,'current':price,'stake':stake,'score':score,'opened':now()};S['orders'].insert(0,{'symbol':sym,'side':'BUY','status':'FILLED','price':price,'score':score,'time':now()})
async def closep(sym,price,reason):
 p=S['positions'].pop(sym);pnl=(price/p['entry']-1)*p['stake'];S['free']+=p['stake']+pnl;S['real']+=pnl;S['balance']+=pnl;S['orders'].insert(0,{'symbol':sym,'side':'SELL','status':'FILLED','price':price,'score':p['score'],'time':now(),'reason':reason});S['trades'].insert(0,{'id':p['id'],'symbol':sym,'timeframe':p['timeframe'],'entry':p['entry'],'exit':price,'stake':p['stake'],'pnl':pnl,'score':p['score'],'reason':reason,'closed':now()});S['trades']=S['trades'][:100]
async def radar():
 try:
  r=await make_radar()
  async with lock:S['radar']=r;S['err']=None
 except Exception as e:
  async with lock:S['err']=f'Radar: {type(e).__name__}: {e}'
async def cycle():
 async with lock:
  if not S['running']:return
  pairs=list(S['pairs']);S['cycle']+=1;S['last_cycle']=now()
 for x in pairs:
  try:
   a=await analyse(x['symbol'],x['timeframe'])
   if not a:continue
   async with lock:
    p=S['positions'].get(x['symbol'])
    if p:
     p['current']=a['price'];pnl=(a['price']/p['entry']-1)*p['stake'];age=time.time()-datetime.fromisoformat(p['opened']).timestamp()
     if pnl>=p['stake']*.002 or age>={'1m':90,'3m':210,'5m':330}.get(x['timeframe'],210) or (a['trend']<-.03 and pnl>0):await closep(x['symbol'],a['price'],'TP/TIME/TREND')
    elif S['free']>=20 and a['signal']=='BUY' and a['score']>=50:await openp(x['symbol'],x['timeframe'],a['price'],min(50,S['free']),a['score'])
  except Exception as e:
   async with lock:S['err']=f"{x['symbol']}: {type(e).__name__}: {e}"
async def worker():
 while True:
  try:
   async with lock:
    run=S['running'];rot=run and (not S['rotation'] or time.time()-S['rotation']>=S['rotsec'])
   if run:
    if rot:
     await radar()
     async with lock:S['rotation']=time.time()
    await cycle()
  except Exception as e:
   async with lock:S['err']=f'Engine: {e}'
  await asyncio.sleep(5)
@app.on_event('startup')
async def startup():asyncio.create_task(worker())
class Pair(BaseModel):symbol:str=Field(pattern=r'^[A-Z0-9]+USDT$');timeframe:str=Field(pattern=r'^(1m|3m|5m)$')
class PairSet(BaseModel):pairs:list[Pair]=Field(default_factory=list,max_length=N)
@app.get('/api/health')
async def health():return {'ok':True,'running':S['running'],'cycle':S['cycle'],'time':now()}
@app.get('/api/state')
async def state():
 async with lock:return snap()
@app.post('/api/radar')
async def radar_api():
 await radar()
 async with lock:return snap()
@app.post('/api/pairs')
async def setpairs(b:PairSet):
 async with lock:S['pairs']=[p.model_dump() for p in b.pairs]
 return snap()
@app.post('/api/paper/start')
async def start():
 await radar()
 async with lock:
  if not S['pairs']:S['pairs']=[{'symbol':x['symbol'],'timeframe':'3m'} for x in S['radar'][:N]]
  S['running']=True;S['started']=now();S['rotation']=time.time();S['err']=None
 return snap()
@app.post('/api/paper/stop')
async def stop():
 async with lock:S['running']=False
 return snap()
@app.post('/api/reset')
async def reset():
 async with lock:S.update({'running':False,'balance':BAL,'free':BAL,'real':0.0,'positions':{},'trades':[],'orders':[],'pairs':[],'radar':[],'err':None,'started':None,'cycle':0,'rotation':None})
 return snap()
HTML=r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper — New Start</title><style>*{box-sizing:border-box}body{font-family:Arial;background:#080e1d;color:#eef2ff;margin:0;padding:12px}.w{max-width:920px;margin:auto}.head{display:flex;justify-content:space-between;align-items:center}h2{margin:8px 0 2px}.m{color:#8793ad;font-size:12px}.card{background:#131b2d;border:1px solid #293650;border-radius:14px;padding:12px;margin-top:9px}.balance{position:relative;padding-right:145px}.free{position:absolute;right:12px;top:12px}.v{font-size:18px;font-weight:700}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}.stat{background:#10172a;border-radius:9px;padding:8px}.controls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px}.btn{border:0;border-radius:10px;padding:11px;font-weight:700;color:#fff;background:#273552}.on{background:#07824e}.stop{background:#9d2d3d}.pairs{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px}.pair{background:#0d1424;border:1px solid #2b3854;border-radius:9px;padding:7px}.pair input{width:58%;background:transparent;color:#fff;border:0;outline:0;font-weight:700}.pair select{float:right;background:#111a2c;color:#fff;border:1px solid #33405b;border-radius:6px;padding:3px}.radar{display:none;margin-top:8px}.radar.open{display:block}.rg{display:grid;grid-template-columns:1fr 1fr;gap:5px}.cand{display:flex;justify-content:space-between;background:#0d1424;border:1px solid #283550;border-radius:8px;padding:7px}table{width:100%;border-collapse:collapse}td,th{padding:7px 4px;border-bottom:1px solid #273149;font-size:12px;text-align:left}.g{color:#42e28a}.r{color:#ff6873}.timer{font-size:22px;font-weight:800}@media(max-width:650px){.stats{grid-template-columns:repeat(2,1fr)}.pairs{grid-template-columns:repeat(3,1fr)}.rg{grid-template-columns:1fr}}</style></head><body><div class="w"><div class="head"><div><h2>Fast Scalper — New Start</h2><div class="m">PAPER • 6 active pairs • 10-pair radar • 20s rotation</div></div><div class="timer" id="timer">00</div></div><div class="card balance"><div class="m">Account Balance</div><div class="v" id="bal">—</div><div class="free"><div class="m">Free Balance</div><div class="v" id="free">—</div></div><div class="stats"><div class="stat"><div class="m">Realized PnL</div><div class="v" id="real">—</div></div><div class="stat"><div class="m">Unrealized PnL</div><div class="v" id="unreal">—</div></div><div class="stat"><div class="m">Net PnL</div><div class="v" id="net">—</div></div><div class="stat"><div class="m">Engine</div><div class="v" id="eng">OFF</div></div></div></div><div class="card controls"><button class="btn" id="on" onclick="toggle()">PAPER OFF</button><button class="btn stop" onclick="stop()">EMERGENCY STOP</button><button class="btn" onclick="resetAll()">RESET</button></div><div class="card"><b>Open Positions</b><table><tbody id="pos"></tbody></table></div><div class="card"><b>Session Result</b><div class="m" id="session">Trades: 0 • Open: 0 • Realized: 0.00 USDT • Unrealized: 0.00 USDT</div><div class="m" id="cy">Cycle: 0 • Last: —</div></div><div class="card"><b>6 Active Pairs</b><div class="m">Только эти 6 пар участвуют в ордерном цикле.</div><div class="pairs" id="pairs"></div><div class="controls" style="margin-top:7px"><button class="btn" onclick="save()">SAVE 6 PAIRS</button><button class="btn" onclick="radarToggle()">⌄ RATING / 10 PAIRS</button><span></span></div><div class="radar" id="radar"><div class="m" style="margin:7px 0">Рейтинг обновляется каждые 20 секунд во время PAPER.</div><div class="rg" id="rl"></div></div></div><div class="card"><details><summary>Binance API / подключение</summary><div class="m" style="margin-top:7px">В PAPER ключи не используются. Этот блок подготовлен для следующего режима.</div></details></div><div class="card"><b>Closed Trades — latest 5</b><table><thead><tr><th>Pair</th><th>TF</th><th>Score</th><th>PnL</th></tr></thead><tbody id="tr"></tbody></table></div><div class="card"><div class="m" id="status">Engine OFF</div><div class="r" id="err"></div></div></div><script>const $=id=>document.getElementById(id),opts=['1m','3m','5m'];function money(x){return Number(x||0).toFixed(2)+' USDT'}function clock(s){return String(Math.max(0,Math.floor(s))).padStart(2,'0')}function build(a=[]){$('pairs').innerHTML='';for(let i=0;i<6;i++){let p=a[i]||{};$('pairs').innerHTML+=`<div class="pair"><input id="p${i}" placeholder="BTCUSDT" value="${p.symbol||''}"><select id="f${i}">${opts.map(x=>`<option ${x===(p.timeframe||'3m')?'selected':''}>${x}</option>`).join('')}</select></div>`}}async function j(u,o){let r=await fetch(u,o),d=await r.json();if(!r.ok)throw Error(d.detail||'request failed');return d}async function toggle(){try{render(await j($('on').textContent.includes('OFF')?'/api/paper/start':'/api/paper/stop',{method:'POST'}))}catch(e){$('err').textContent=e.message}}async function stop(){try{render(await j('/api/paper/stop',{method:'POST'}))}catch(e){$('err').textContent=e.message}}async function resetAll(){try{render(await j('/api/reset',{method:'POST'}))}catch(e){$('err').textContent=e.message}}async function save(){let p=[];for(let i=0;i<6;i++){let s=$('p'+i).value.trim().toUpperCase();if(s)p.push({symbol:s,timeframe:$('f'+i).value})}try{render(await j('/api/pairs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pairs:p})}))}catch(e){$('err').textContent=e.message}}async function radarToggle(){let x=$('radar');x.classList.toggle('open');if(x.classList.contains('open'))try{render(await j('/api/radar',{method:'POST'}))}catch(e){$('err').textContent=e.message}}function render(d){$('bal').textContent=money(d.balance);$('free').textContent=money(d.free);$('real').textContent=money(d.real);$('unreal').textContent=money(d.unreal);$('net').textContent=money(d.net);$('eng').textContent=d.running?'ON':'OFF';$('eng').className='v '+(d.running?'g':'');$('on').textContent=d.running?'PAPER ON':'PAPER OFF';$('on').className='btn '+(d.running?'on':'');$('timer').textContent=d.running?clock(d.left):'00';$('status').textContent=d.running?`RUNNING • cycle ${d.cycle} • rotation ${d.left}s`:'Engine OFF';$('session').textContent=`Trades: ${d.trades.length} • Open: ${d.positions.length} • Realized: ${money(d.real)} • Unrealized: ${money(d.unreal)}`;$('cy').textContent=`Cycle: ${d.cycle} • Last: ${d.last_cycle||'—'}`;$('pos').innerHTML=d.positions.map(x=>`<tr><td>${x.symbol}</td><td>${x.timeframe}</td><td>${Number(x.score).toFixed(1)}</td><td class="${x.pnl>=0?'g':'r'}">${money(x.pnl)}</td></tr>`).join('')||'<tr><td colspan="4">No open positions</td></tr>';$('tr').innerHTML=d.trades.slice(0,5).map(x=>`<tr><td>${x.symbol}</td><td>${x.timeframe}</td><td>${Number(x.score||0).toFixed(1)}</td><td class="${x.pnl>=0?'g':'r'}">${money(x.pnl)}</td></tr>`).join('')||'<tr><td colspan="4">No closed trades yet</td></tr>';$('rl').innerHTML=(d.radar||[]).map((x,i)=>`<div class="cand"><span>${i+1}. ${x.symbol} <span class="m">${Number(x.change).toFixed(2)}%</span></span><b>${Number(x.rating).toFixed(1)}</b></div>`).join('')||'<div class="m">Нет данных рейтинга</div>';$('err').textContent=d.err||'';build(d.pairs)}async function refresh(){try{render(await j('/api/state'))}catch(e){$('err').textContent='Connection error: '+e.message}}build();refresh();setInterval(refresh,2000)</script></body></html>'''
@app.get('/',response_class=HTMLResponse)
async def root():return HTMLResponse(HTML,headers={'Cache-Control':'no-store,no-cache,must-revalidate,max-age=0'})
