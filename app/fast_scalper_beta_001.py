from __future__ import annotations
import asyncio,hashlib,hmac,os,time
from datetime import datetime,timezone
from urllib.parse import quote
import httpx
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field
from .market_radar import RADAR

VERSION='0.01 REPAIR PAPER'; MAX_SLOTS=6; TF='3m'; MAX_AGE=60; START=1850.0
S={'running':False,'mode':'PAPER','account':START,'bot':0.0,'free':0.0,'reserve':0.0,'realized':0.0,'session_realized':0.0,'session_trades':0,'session_started':None,'session_elapsed':0.0,'day_started':None,'positions':[],'closed':[],'orders':[],'ranking':[],'slots':[None]*MAX_SLOTS,'profit':0.0,'reinvest':False,'cycle':0,'last_radar':0.0,'error':None,'source':'Binance WebSocket'}
class Start(BaseModel): profit_pct:float=Field(0,ge=0,le=80); reinvest:bool=False
class Slots(BaseModel): slots:list[str]=Field(default_factory=list,max_length=MAX_SLOTS); profit_pct:float=Field(0,ge=0,le=80); reinvest:bool=False
class Mode(BaseModel): mode:str
class Allocation(BaseModel): amount:float=Field(0,ge=0)
def now():return datetime.now(timezone.utc).isoformat()

class Binance:
 def __init__(self):
  self.key=os.getenv('BINANCE_API_KEY','').strip();self.secret=os.getenv('BINANCE_API_SECRET','').strip();self.testnet=os.getenv('BINANCE_TESTNET','1').lower() not in {'0','false','no'};self.live=os.getenv('BINANCE_LIVE_ENABLED','0').lower() in {'1','true','yes'};self.base='https://testnet.binance.vision/api' if self.testnet else 'https://api.binance.com/api'
 @property
 def configured(self):return bool(self.key and self.secret)
 def diagnostics(self):
  return {'testnet':self.testnet,'base':self.base,'api_key_present':bool(self.key),'api_key_length':len(self.key),'api_key_prefix':self.key[:4] if self.key else '','api_key_suffix':self.key[-4:] if self.key else '','api_key_sha256':hashlib.sha256(self.key.encode('utf-8')).hexdigest()[:16] if self.key else '','secret_present':bool(self.secret),'secret_length':len(self.secret),'secret_sha256':hashlib.sha256(self.secret.encode('utf-8')).hexdigest()[:16] if self.secret else '','live_enabled':self.live}
 def sign(self,p):
  if not self.configured:raise RuntimeError('Binance API credentials are not configured')
  p=dict(p);p.setdefault('timestamp',int(time.time()*1000));p.setdefault('recvWindow',5000)
  q='&'.join(f'{quote(str(k),safe="-_.~")}={quote(str(v),safe="-_.~")}' for k,v in p.items())
  p['signature']=hmac.new(self.secret.encode('utf-8'),q.encode('utf-8'),hashlib.sha256).hexdigest();return p
 async def ping(self):
  async with httpx.AsyncClient(timeout=8) as c:r=await c.get(self.base+'/v3/ping');r.raise_for_status()
 async def account(self):
  async with httpx.AsyncClient(timeout=8) as c:
   tr=await c.get(self.base+'/v3/time');tr.raise_for_status();server_ms=int(tr.json()['serverTime'])
   p=self.sign({'timestamp':server_ms})
   r=await c.get(self.base+'/v3/account',params=p,headers={'X-MBX-APIKEY':self.key})
  if r.status_code>=400:
   try: body=r.json()
   except Exception: body=r.text[:500]
   raise RuntimeError(f'Binance HTTP {r.status_code}: {body}')
  return r.json()
 async def order(self,params):
  p=dict(params)
  async with httpx.AsyncClient(timeout=10) as c:
   tr=await c.get(self.base+'/v3/time');tr.raise_for_status();p['timestamp']=int(tr.json()['serverTime'])
   p=self.sign(p)
   r=await c.post(self.base+'/v3/order',params=p,headers={'X-MBX-APIKEY':self.key})
  if r.status_code>=400:
   try: body=r.json()
   except Exception: body=r.text[:500]
   raise RuntimeError(f'Binance order HTTP {r.status_code}: {body}')
  return r.json()
 async def market_buy(self,symbol,quote_qty):
  return await self.order({'symbol':symbol,'side':'BUY','type':'MARKET','quoteOrderQty':f'{quote_qty:.8f}','newOrderRespType':'FULL'})
 async def market_sell(self,symbol,qty):
  return await self.order({'symbol':symbol,'side':'SELL','type':'MARKET','quantity':str(qty),'newOrderRespType':'FULL'})
B=Binance()

async def radar(force=False):
 if not force and S['last_radar'] and time.time()-S['last_radar']<60:return
 try:
  rows=RADAR.snapshot(15);out=[]
  for x in rows:
   s=str(x.get('symbol','')).replace('/','').upper()
   if s:out.append({'symbol':s,'price':float(x.get('price') or 0),'change':float(x.get('change_24h_pct') or 0),'volume':float(x.get('quote_volume_24h') or 0),'score':float(x.get('score') or 0),'signal':x.get('signal','WAIT'),'tf':TF})
  out.sort(key=lambda x:(x['score'],x['volume']),reverse=True);S['ranking']=out[:15];S['last_radar']=time.time();S['error']=None if not getattr(RADAR,'last_error',None) else 'Radar WebSocket: '+RADAR.last_error
 except Exception as e:S['error']=f'Radar: {type(e).__name__}: {e}';S['last_radar']=time.time()
def price(s):
 try:
  p=float(RADAR.price(s) or 0)
  if p>0:return p
 except Exception:pass
 return next((float(x['price']) for x in S['ranking'] if x['symbol']==s),0)
def invested():return sum(float(x['stake']) for x in S['positions'])
def refresh_reserve():S['reserve']=max(0.0,S['account']-S['bot'])
async def close(p,reason):
 if S['mode']=='BINANCE_TEST':
  r=await B.market_sell(p['symbol'],p['qty']);status=r.get('status','')
  if status!='FILLED':raise RuntimeError(f'Binance SELL not filled: {status or r}')
  xp=float(r.get('cummulativeQuoteQty') or 0)/float(r.get('executedQty') or p['qty']);proceeds=float(r.get('cummulativeQuoteQty') or 0);pnl=proceeds-p['stake'];S['free']+=proceeds
  if S['reinvest':
   S['bot']+=pnl
  else:
   S['account']+=pnl
   S['free']=max(0.0,S['bot']-invested())
  refresh_reserve()
  S['orders'].insert(0,{'time':now(),'symbol':p['symbol'],'side':'SELL','status':status,'price':xp,'qty':p['qty'],'order_id':r.get('orderId'),'pnl':pnl,'reason':reason})
 else:
  ep=p['entry'];xp=price(p['symbol']) or ep;pnl=(xp/ep-1)*p['stake'];S['free']+=p['stake'];S['bot']+=pnl if S['reinvest'] else 0;S['account']+=pnl if not S['reinvest'] else 0;refresh_reserve();S['orders'].insert(0,{'time':now(),'symbol':p['symbol'],'side':'SELL','price':xp,'pnl':pnl,'reason':reason})
 S['realized']+=pnl;S['session_realized']+=pnl;S['session_trades']+=1;S['closed'].insert(0,dict(p,exit=xp,pnl=pnl,reason=reason,closed_at=now()));S['closed']=S['closed'][:100];S['positions'].remove(p)
async def open_pos(i,s):
 if not s:return
 n=sum(1 for x in S['slots'] if x)
 if not n:return
 if S['mode']=='BINANCE_TEST':
  if S['free']<=0:return
  stake=min(S['free'],S['bot']/n)
  if stake<=0:return
  try:
   r=await B.market_buy(s,stake);status=r.get('status','')
   if status!='FILLED':raise RuntimeError(f'Binance BUY not filled: {status or r}')
   qty=float(r.get('executedQty') or 0);spent=float(r.get('cummulativeQuoteQty') or 0)
   if qty<=0 or spent<=0:raise RuntimeError(f'Binance BUY returned empty fill: {r}')
   ep=spent/qty;S['free']-=spent;p={'id':f"B{r.get('orderId',int(time.time()*1000))}",'slot':i,'symbol':s,'tf':TF,'entry':ep,'current':ep,'stake':spent,'qty':qty,'opened':time.time(),'opened_at':now(),'order_id':r.get('orderId')};S['positions'].append(p);S['orders'].insert(0,{'time':now(),'symbol':s,'side':'BUY','status':status,'price':ep,'qty':qty,'stake':spent,'order_id':r.get('orderId'),'slot':i})
  except Exception as e:S['error']=f'Binance BUY {s}: {type(e).__name__}: {e}'
  return
 if S['free']<=0:return
 ep=price(s)
 if ep<=0:return
 stake=min(S['free'],max(1.0,S['bot']/n));S['free']-=stake;p={'id':f'P{int(time.time()*1000)}','slot':i,'symbol':s,'tf':TF,'entry':ep,'current':ep,'stake':stake,'opened':time.time(),'opened_at':now()};S['positions'].append(p);S['orders'].insert(0,{'time':now(),'symbol':s,'side':'BUY','status':'PAPER_FILLED','price':ep,'slot':i})
async def manage():
 for p in list(S['positions']):
  p['current']=price(p['symbol']) or p['current'];live=(p['current']/p['entry']-1)*100
  if S['profit']>0 and live>=S['profit']:
   try:await close(p,'PROFIT_TARGET')
   except Exception as e:S['error']=f'Close {p["symbol"]}: {type(e).__name__}: {e}'
  elif time.time()-p['opened']>=MAX_AGE:
   try:await close(p,'TIMEOUT')
   except Exception as e:S['error']=f'Close {p["symbol"]}: {type(e).__name__}: {e}'
async def engine():
 while True:
  try:
   await manage()
   if S['running']:
    S['cycle']+=1;await radar()
    for i,s in enumerate(S['slots']):
     if s and not any(p['slot']==i for p in S['positions']):await open_pos(i,s)
   await asyncio.sleep(1)
  except Exception as e:S['error']=f'Engine: {type(e).__name__}: {e}';await asyncio.sleep(1)
app=FastAPI(title='Fast Scalper Beta '+VERSION)
@app.on_event('startup')
async def startup():RADAR.start();asyncio.create_task(engine());asyncio.create_task(radar(True))
@app.on_event('shutdown')
async def shutdown():RADAR.stop()
@app.get('/',response_class=HTMLResponse)
async def home():return HTML
@app.get('/api/health')
async def health():return {'ok':True,'version':VERSION,'mode':S['mode'],'running':S['running'],'cycle':S['cycle'],'positions':len(S['positions']),'radar_ok':bool(S['ranking']),'error':S['error'],'binance_configured':B.configured,'binance_testnet':B.testnet,'live_enabled':B.live}
@app.get('/api/state')
async def state():
 sa=int(time.time()-datetime.fromisoformat(S['session_started']).timestamp()) if S['session_started'] else int(S['session_elapsed']);da=int(time.time()-datetime.fromisoformat(S['day_started']).timestamp()) if S['day_started'] else 0;un=sum((p['current']/p['entry']-1)*p['stake'] for p in S['positions']);return {'version':VERSION,'running':S['running'],'mode':S['mode'],'account':S['account'],'bot_balance':S['bot'],'free':S['free'],'reserve':S['reserve'],'realized':S['realized'],'session_realized':S['session_realized'],'session_trades':S['session_trades'],'unrealized':un,'total_equity':S['account'],'positions':S['positions'],'closed':S['closed'][:20],'orders':S['orders'][:20],'ranking':S['ranking'],'slots':S['slots'],'profit_pct':S['profit'],'reinvest':S['reinvest'],'cycle':S['cycle'],'session_age':sa,'day_age':da,'error':S['error'],'binance_configured':B.configured,'binance_testnet':B.testnet,'live_enabled':B.live}
@app.post('/api/paper/start')
async def start(b:Start):
 if S['positions']:raise HTTPException(400,'Close current positions before a new session')
 if S['mode']=='PAPER':
  if S['bot']<=0:S['bot']=S['account'];refresh_reserve();S['free']=max(0.0,S['bot']-invested())
  S.update(profit=b.profit_pct,reinvest=b.reinvest,running=True,started=now(),session_started=now(),session_elapsed=0.0,session_realized=0.0,session_trades=0,error=None);S['day_started']=S['day_started'] or now();return await state()
 if S['mode']=='BINANCE_TEST':
  if not B.configured:raise HTTPException(400,'Binance API credentials are not configured')
  if not B.testnet:raise HTTPException(403,'BINANCE_TEST requires Binance Testnet')
  if S['bot']<=0:raise HTTPException(400,'Set Bot Allocation before starting BINANCE_TEST')
  try:
   await B.ping();acc=await B.account();free_usdt=next((float(x['free']) for x in acc.get('balances',[]) if x.get('asset')=='USDT'),0.0)
   if free_usdt<S['bot']:raise RuntimeError(f'Bot allocation {S["bot"]:.8f} exceeds free USDT {free_usdt:.8f}')
   S['account']=free_usdt+invested();refresh_reserve();S.update(profit=b.profit_pct,reinvest=b.reinvest,running=True,started=now(),session_started=now(),session_elapsed=0.0,session_realized=0.0,session_trades=0,error=None);S['day_started']=S['day_started'] or now();return await state()
  except Exception as e:raise HTTPException(400,f'Binance TEST start failed: {type(e).__name__}: {e}')
 raise HTTPException(403,'Unsupported trading mode')
@app.post('/api/paper/stop')
async def stop():S['running']=False;return await state()
@app.post('/api/paper/emergency')
async def emergency():
 for p in list(S['positions']):
  try:await close(p,'EMERGENCY_STOP')
  except Exception as e:S['error']=f'Close {p["symbol"]}: {type(e).__name__}: {e}'
 S['running']=False;S['session_started']=None;return await state()
@app.post('/api/reset')
async def reset():
 if S['running']:raise HTTPException(400,'STOP the bot before RESET')
 S['slots']=[None]*MAX_SLOTS;S['profit']=0;S['reinvest']=False;S['session_elapsed']=0;S['error']=None
 if S['mode']=='PAPER':S['account']=START;S['bot']=0.0;S['free']=0.0;S['reserve']=0.0
 return await state()
@app.post('/api/allocation')
async def allocation(b:Allocation):
 if S['running']:raise HTTPException(400,'STOP the bot before changing Bot Allocation')
 if S['mode']=='PAPER':
  if b.amount>S['account']:raise HTTPException(400,f'Allocation {b.amount:.8f} exceeds PAPER account {S["account"]:.8f}')
  if b.amount<invested():raise HTTPException(400,f'Allocation cannot be below open capital {invested():.8f}')
  S['bot']=b.amount;S['free']=max(0.0,b.amount-invested());refresh_reserve();return await state()
 if S['mode']!='BINANCE_TEST':raise HTTPException(403,'Unsupported trading mode')
 try:
  await B.ping();acc=await B.account();account_usdt=next((float(x['free']) for x in acc.get('balances',[]) if x.get('asset')=='USDT'),0.0)
  if b.amount>account_usdt:raise HTTPException(400,f'Allocation {b.amount:.8f} exceeds free USDT {account_usdt:.8f}')
  if b.amount<invested():raise HTTPException(400,f'Allocation cannot be below open capital {invested():.8f}')
  S['account']=account_usdt+invested();S['bot']=b.amount;S['free']=max(0.0,b.amount-invested());refresh_reserve();return await state()
 except HTTPException:raise
 except Exception as e:raise HTTPException(400,f'Bot Allocation failed: {type(e).__name__}: {e}')
def clean(a):
 o=[]
 for x in a:
  z=x.upper().replace('/','').strip()
  if z and z not in o:o.append(z)
 if len(o)>MAX_SLOTS:raise HTTPException(400,'Maximum 6 pairs')
 bad=[x for x in o if not x.endswith('USDT') or len(x)<=4]
 if bad:raise HTTPException(400,'Invalid Binance pairs: '+','.join(bad))
 return o
@app.post('/api/slots')
async def slots(b:Slots):
 a=clean(b.slots);new=a+[None]*(MAX_SLOTS-len(a));old=list(S['slots'])
 for i in range(MAX_SLOTS):
  if old[i] and old[i]!=new[i]:
   for p in list(S['positions']):
    if p['slot']==i:
     try:await close(p,'MANUAL_REMOVE')
     except Exception as e:S['error']=f'Close {p["symbol"]}: {type(e).__name__}: {e}'
 S['slots']=new;S['profit']=b.profit_pct;S['reinvest']=b.reinvest;return await state()
@app.post('/api/slots/auto-top6')
async def auto_top6(b:Slots):
 await radar(True);S['slots']=[x['symbol'] for x in S['ranking'][:MAX_SLOTS]];S['profit']=b.profit_pct;S['reinvest']=b.reinvest;return await state()
@app.post('/api/mode')
async def mode(b:Mode):
 m=b.mode.upper()
 if m not in {'PAPER','BINANCE_TEST'}:raise HTTPException(403,'Only PAPER and BINANCE_TEST are enabled in Beta 0.01')
 if S['running'] or S['positions']:raise HTTPException(400,'STOP and close positions before changing mode')
 if m=='BINANCE_TEST' and not B.testnet:raise HTTPException(403,'BINANCE_TEST requires Binance Testnet')
 S['mode']=m
 if m=='PAPER':
  S['account']=START;S['bot']=0.0;S['free']=0.0;S['reserve']=START
 else:
  S['account']=0.0;S['bot']=0.0;S['free']=0.0;S['reserve']=0.0
 return await state()
@app.post('/api/binance/test')
async def binance_test():
 diag=B.diagnostics()
 try:
  await B.ping();acc=await B.account();balances=acc.get('balances',[]);free_usdt=next((float(x['free']) for x in balances if x.get('asset')=='USDT'),0.0)
  if S['mode']=='BINANCE_TEST' and not S['running'] and not S['positions']:
   S['account']=free_usdt;S['bot']=0.0;S['free']=0.0;S['reserve']=free_usdt
  return {'ok':True,'testnet':B.testnet,'configured':B.configured,'account_checked':bool(acc),'balances':balances,'diagnostics':diag}
 except Exception as e:raise HTTPException(400,f'Binance connection failed: {type(e).__name__}: {e} | DIAGNOSTICS: {diag}')

HTML="""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Fast Scalper Beta</title><style>*{box-sizing:border-box}body{margin:0;background:#080e1b;color:#eef3ff;font-family:system-ui}.w{max-width:900px;margin:auto;padding:14px}.title{font-size:30px;font-weight:900}.muted{color:#8b97ae}.card{background:#121a2c;border:1px solid #293650;border-radius:16px;padding:14px;margin:10px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.stat{background:#0d1425;border-radius:10px;padding:10px}.v{font-size:19px;font-weight:850}.row{display:flex;gap:8px;flex-wrap:wrap}.input,.select,.slot{background:#0b1322;color:#fff;border:1px solid #30405f;border-radius:9px;padding:10px;flex:1;min-width:120px}.btn{border:0;border-radius:10px;padding:11px 15px;color:#fff;font-weight:850;background:#273650}.on{background:#078b53}.stop{background:#a72e3f}.test{background:#183b66}.grid6{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.rank{display:grid;grid-template-columns:22px 1fr 65px 50px;gap:5px;padding:5px;border-bottom:1px solid #24314a;font-size:9px}.line{font-size:12px;padding:4px 0;border-bottom:1px solid #24314a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}@media(max-width:650px){.stats{grid-template-columns:repeat(2,1fr)}.grid6{grid-template-columns:repeat(2,1fr)}}</style></head><body><div class='w'><div class='title'>⚡ Fast Scalper Beta</div><div class='muted'>Version 0.01 REPAIR PAPER · Trading TF: 3m</div><div class='card'><div class='stats'><div class='stat'>Account Balance<div class='v' id='account'>—</div></div><div class='stat'>Bot Balance<div class='v' id='bot'>—</div></div><div class='stat'>Reserve<div class='v' id='reserve'>—</div></div><div class='stat'>Session PnL<div class='v' id='sp'>—</div></div></div><div class='row' style='margin-top:10px'><select id='modeSel' class='select'><option>PAPER</option><option>BINANCE_TEST</option></select><button class='btn test' onclick='setMode()'>SET MODE</button><button class='btn test' onclick='bt()'>TEST BINANCE</button></div><div id='msg' class='muted'>PAPER and BINANCE_TEST are independent modes. TEST BINANCE checks the Testnet connection.</div></div><div class='card'><div class='row'><input id='allocation' class='input' type='number' step='0.01' min='0' placeholder='Bot Allocation, USDT'><button class='btn test' onclick='applyAllocation()'>SET BOT BALANCE</button><input id='profit' class='input' type='number' step='0.01' value='0.41'><label style='padding:10px'><input id='reinvest' type='checkbox' checked> Reinvest</label></div><div class='row' style='margin-top:8px'><button class='btn on' onclick='start()'>BOT ON · ACTIVE</button><button class='btn stop' onclick='emergency()'>EMERGENCY</button><button class='btn' onclick='reset()'>RESET</button><button class='btn stop' onclick='stop()'>BOT OFF</button><span class='muted' id='tim'>SESSION 00:00 · 24H 00:00</span></div></div><div class='card'><h2>Slots · TOP-6</h2><div class='grid6' id='slots'></div><div class='row' style='margin-top:10px'><button class='btn on' onclick='setPairs()'>SET PAIRS</button><button class='btn' onclick='addPair()'>＋ ADD PAIR</button><button class='btn' onclick='top6()'>AUTO TOP-6</button></div><div class='muted'>Manual pairs can be entered directly in the six slots. ADD PAIR focuses the next empty slot. SET PAIRS saves them.</div></div><div class='card'><details open><summary>Radar · TOP-15 · recommended pairs</summary><div id='radar'></div></details></div><div class='card'><h2>Open Positions</h2><div id='pos' class='muted'>No open positions</div></div><div class='card'><h2>Closed Trades — latest 5</h2><div id='closed' class='muted'>No closed trades</div></div><div class='card'><div class='muted'>Health: <span id='health'>—</span> · <span id='err'></span></div></div></div><script>let s={};const $=x=>document.getElementById(x),P=()=>$('profit').value*1||0,R=()=>$('reinvest').checked;async function api(p,m='GET',b){let r=await fetch(p,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):null}),j=await r.json();if(!r.ok)throw Error(j.detail||JSON.stringify(j));return j}async function start(){try{await api('/api/paper/start','POST',{profit_pct:P(),reinvest:R()})}catch(e){alert(e.message)}}async function stop(){try{await api('/api/paper/stop','POST')}catch(e){alert(e.message)}}async function emergency(){try{await api('/api/paper/emergency','POST')}catch(e){alert(e.message)}}async function reset(){try{await api('/api/reset','POST');slots();load()}catch(e){alert(e.message)}}async function setMode(){try{await api('/api/mode','POST',{mode:$('modeSel').value});load()}catch(e){alert(e.message)}}async function bt(){try{let x=await api('/api/binance/test','POST');$('msg').textContent=x.account_checked?'Binance TEST signed account check OK':'Binance public ping OK; credentials not configured';load()}catch(e){$('msg').textContent=e.message}}async function applyAllocation(){try{let a=+$('allocation').value;if(!Number.isFinite(a)||a<0)throw Error('Enter Bot Allocation');await api('/api/allocation','POST',{amount:a});load()}catch(e){alert(e.message)}}function slots(){ $('slots').innerHTML=Array.from({length:6},(_,i)=>`<input class='slot' id='s${i}' placeholder='USDT pair' value='${(s.slots||[])[i]||''}'>`).join('')}function addPair(){let i=Array.from({length:6},(_,i)=>$('s'+i).value.trim()).findIndex(x=>!x);if(i<0){alert('Maximum 6 pairs');return}$('s'+i).focus()}async function setPairs(){try{let a=Array.from({length:6},(_,i)=>$('s'+i).value).filter(Boolean);await api('/api/slots','POST',{slots:a,profit_pct:P(),reinvest:R()});load()}catch(e){alert(e.message)}}async function top6(){try{await api('/api/slots/auto-top6','POST',{slots:[],profit_pct:P(),reinvest:R()});load();slots()}catch(e){alert(e.message)}}function f(x){return (+x||0).toFixed(4)}function clock(x){x=Math.floor(x||0);return String(Math.floor(x/60)).padStart(2,'0')+':'+String(x%60).padStart(2,'0')}function render(){ $('modeSel').value=s.mode;$('account').textContent=f(s.account);$('bot').textContent=f(s.bot_balance);$('reserve').textContent=f(s.reserve);$('sp').textContent=f(s.session_realized);let p=s.positions||[];$('tim').textContent='SESSION '+clock(s.session_age)+' · 24H '+clock(s.day_age);$('health').textContent=s.running?'RUNNING':'STOPPED';$('err').textContent=s.error||'OK';$('pos').innerHTML=p.length?p.map(x=>`<div class='line'>${x.symbol} · ${f(x.stake)} USDT · ${f(x.current)}</div>`).join(''):'No open positions';$('closed').innerHTML=(s.closed||[]).slice(0,5).map(x=>`<div class='line'>${x.symbol} · ${x.reason} · ${f(x.pnl)} USDT · ${f(x.exit)}</div>`).join('')||'No closed trades';$('radar').innerHTML=(s.ranking||[]).map((x,i)=>`<div class='rank'><b>${i+1}</b><b>${x.symbol}</b><span>${f(x.price)}</span><span>${f(x.score)}</span></div>`).join('')}async function load(){try{s=await api('/api/state');render()}catch(e){$('err').textContent=e.message}}slots();load();setInterval(load,1000)</script></body></html>"""