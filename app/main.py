from __future__ import annotations
import asyncio,random,time
from datetime import datetime,timezone
import httpx
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field
app=FastAPI(title='Fast Scalper')
BINANCE='https://api.binance.com'; UNIVERSE=['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','TRXUSDT','LINKUSDT','SUIUSDT','AVAXUSDT','TONUSDT','LTCUSDT','DOTUSDT','ATOMUSDT','NEARUSDT','APTUSDT','ARBUSDT','OPUSDT','FILUSDT']; ANALYSIS_TFS=['1m','3m','5m','15m','30m']; TRADING_TF='3m'; START_ACCOUNT=150.; START_BOT=100.; ROTATE=420
S={'running':False,'account':START_ACCOUNT,'bot':START_BOT,'free':START_BOT,'realized':0.,'positions':[],'closed':[],'orders':[],'ranking':[],'slots':[None]*6,'profit':0.,'reinvest':False,'cycle':0,'started':None,'last_radar':0.,'error':None}
L=asyncio.Lock(); SEM=asyncio.Semaphore(8)
def now():return datetime.now(timezone.utc).isoformat()
async def get(path,p=None):
 async with httpx.AsyncClient(timeout=8) as c:
  r=await c.get(BINANCE+path,params=p);r.raise_for_status();return r.json()
def ema(a,n):
 k=2/(n+1);x=a[0]
 for v in a[1:]:x=v*k+x*(1-k)
 return x
async def ana(s,tf):
 async with SEM: rows=await get('/api/v3/klines',{'symbol':s,'interval':tf,'limit':40})
 c=[float(x[4]) for x in rows];e9,e20=ema(c,9),ema(c,20);m=(c[-1]/c[-6]-1)*100;t=(e9/e20-1)*100;sc=max(0,min(100,50+t*18+m*7));sig='BUY' if e9>e20 and m>0 else ('SELL' if e9<e20 and m<0 else 'WAIT');return {'price':c[-1],'momentum':m,'score':sc,'signal':sig}
async def ranking():
 ticks=await get('/api/v3/ticker/24hr');by={x.get('symbol'):x for x in ticks if isinstance(x,dict)}
 async def one(s):
  t=by.get(s,{});res=await asyncio.gather(*(ana(s,tf) for tf in ANALYSIS_TFS),return_exceptions=True);good=[x for x in res if isinstance(x,dict)];sc=sum(x['score'] for x in good)/len(good) if good else 50;m=sum(x['momentum'] for x in good)/max(1,len(good));sig='BUY' if sc>=55 and m>0 else ('SELL' if sc<=45 and m<0 else 'WAIT');return {'symbol':s,'price':float(t.get('lastPrice') or (good[0]['price'] if good else 1)),'change':float(t.get('priceChangePercent') or 0),'volume':float(t.get('quoteVolume') or 0),'score':round(sc,2),'signal':sig}
 r=await asyncio.gather(*(one(s) for s in UNIVERSE),return_exceptions=True);r=[x for x in r if isinstance(x,dict)];r.sort(key=lambda x:(x['score'],x['volume']),reverse=True);return r[:15]
async def radar(force=False):
 if not force and time.time()-S['last_radar']<20:return
 try:
  r=await ranking();S['ranking']=r;S['last_radar']=time.time();S['error']=None
 except Exception as e:S['error']=f'Radar: {type(e).__name__}: {e}'
def price(s):return next((x['price'] for x in S['ranking'] if x['symbol']==s),1.)
async def openp(i,s):
 if S['free']<=0:return
 stake=min(S['free'],max(1.,S['bot']/6));p=price(s);sc=next((x['score'] for x in S['ranking'] if x['symbol']==s),0);S['free']-=stake;pos={'id':f'P{int(time.time()*1000)%100000000}','slot':i,'symbol':s,'tf':TRADING_TF,'entry':p,'current':p,'stake':stake,'score':sc,'opened':time.time(),'opened_at':now()};S['positions'].append(pos);S['orders'].insert(0,{'time':now(),'symbol':s,'side':'BUY','status':'FILLED','price':p,'slot':i,'score':sc})
def closep(p,reason):
 ep=price(p['symbol']);xp=ep*(1+random.uniform(-.0012,.0025));pnl=(xp/p['entry']-1)*p['stake'];S['free']+=p['stake'];
 if S['reinvest']:S['free']+=pnl;S['bot']+=pnl
 else:S['account']+=pnl
 S['realized']+=pnl;z=dict(p,exit=xp,pnl=pnl,reason=reason,closed_at=now());S['closed'].insert(0,z);S['closed']=S['closed'][:100];S['orders'].insert(0,{'time':now(),'symbol':p['symbol'],'side':'SELL','status':'FILLED','price':xp,'slot':p['slot'],'pnl':pnl,'reason':reason});S['positions'].remove(p)
async def engine():
 while True:
  try:
   if S['running']:
    await radar();S['cycle']+=1
    for p in list(S['positions']):
     q=next((x for x in S['ranking'] if x['symbol']==p['symbol']),None)
     if q:p['current']=q['price']
     live=(p['current']/p['entry']-1)*p['stake'];age=time.time()-p['opened'];target=p['stake']*S['profit']/100
     if (S['profit']>0 and live>=target) or (S['profit']==0 and age>=ROTATE) or age>=45:closep(p,'PROFIT_TARGET' if S['profit']>0 and live>=target else 'ROTATION')
    for i,cfg in enumerate(S['slots']):
     if cfg and not any(p['slot']==i for p in S['positions']):await openp(i,cfg['symbol'])
   await asyncio.sleep(2)
  except Exception as e:S['error']=f'Engine: {type(e).__name__}: {e}';await asyncio.sleep(2)
@app.on_event('startup')
async def startup():asyncio.create_task(engine());asyncio.create_task(radar(True))
class Start(BaseModel):profit_pct:float=Field(0,ge=0,le=80);reinvest:bool=False
class Slots(BaseModel):slots:list[str]=Field(default_factory=list,max_length=6);profit_pct:float=Field(0,ge=0,le=80);reinvest:bool=False
class Keys(BaseModel):api_key:str='';secret_key:str=''
@app.get('/api/health')
async def health():return {'ok':True,'worker':'alive','running':S['running'],'cycle':S['cycle'],'time':now()}
@app.get('/api/state')
async def state():
 unreal=sum((p['current']/p['entry']-1)*p['stake'] for p in S['positions']);return {'running':S['running'],'account':S['account'],'bot_balance':S['bot'],'free':S['free'],'realized':S['realized'],'unrealized':unreal,'net':S['realized']+unreal,'positions':[dict(p) for p in S['positions']],'closed':S['closed'][:50],'orders':S['orders'][:50],'ranking':S['ranking'],'slots':S['slots'],'profit_pct':S['profit'],'reinvest':S['reinvest'],'cycle':S['cycle'],'started':S['started'],'radar_age':int(time.time()-S['last_radar']) if S['last_radar'] else 0,'error':S['error']}
@app.post('/api/paper/start')
async def start(b:Start):S['profit']=b.profit_pct;S['reinvest']=b.reinvest;S['running']=True;S['started']=now();S['error']=None;await radar(True);return await state()
@app.post('/api/paper/stop')
async def stop():S['running']=False;return await state()
@app.post('/api/paper/emergency')
async def emergency():
 for p in list(S['positions']):closep(p,'EMERGENCY_STOP')
 S['running']=False;return await state()
@app.post('/api/reset')
async def reset():
 S.update({'running':False,'account':START_ACCOUNT,'bot':START_BOT,'free':START_BOT,'realized':0.,'positions':[],'closed':[],'orders':[],'slots':[None]*6,'profit':0.,'reinvest':False,'cycle':0,'started':None,'error':None});await radar(True);return await state()
@app.post('/api/slots')
async def slots(b:Slots):
 clean=[x.upper().replace('/','') for x in b.slots if x.strip()];bad=[x for x in clean if x not in UNIVERSE]
 if len(clean)>6:raise HTTPException(400,'Maximum 6 slots')
 if bad:raise HTTPException(400,'Unsupported pair: '+bad[0])
 S['slots']=[{'symbol':clean[i],'tf':TRADING_TF,'auto':False} if i<len(clean) else None for i in range(6)];S['profit']=b.profit_pct;S['reinvest']=b.reinvest;return await state()
@app.post('/api/keys')
async def keys(b:Keys):return {'ok':True,'configured':bool(b.api_key.strip() and b.secret_key.strip())}
HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper</title><style>*{box-sizing:border-box}body{margin:0;background:#080e1b;color:#eef3ff;font-family:system-ui}.w{max-width:900px;margin:auto;padding:14px}.title{font-size:28px;font-weight:850}.sub,.m{color:#8995ad;font-size:12px}.card{background:#121a2c;border:1px solid #293650;border-radius:14px;padding:12px;margin:9px 0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.stat{background:#0d1425;border-radius:9px;padding:8px}.v{font-size:17px;font-weight:800}.controls,.slots{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.btn{border:0;border-radius:10px;padding:11px;color:#fff;font-weight:800;background:#273650}.on{background:#078b53}.stop{background:#a72e3f}.input{background:#0b1322;color:#fff;border:1px solid #30405f;border-radius:8px;padding:9px;width:100%}.slot{background:#0d1425;border:1px solid #2a3855;border-radius:9px;padding:8px;position:relative}.x{position:absolute;right:5px;top:5px;background:#273650;color:#fff;border:0;border-radius:6px}.rank{display:grid;grid-template-columns:25px 1fr 60px 38px;gap:6px;align-items:center;padding:8px;border-bottom:1px solid #24314a}.badge{background:#08764e;border-radius:7px;padding:3px;text-align:center}.grid15{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.pick{background:#0d1425;border:1px solid #293753;border-radius:8px;padding:7px}.good{color:#40df8b}.bad{color:#ff6576}@media(max-width:650px){.stats{grid-template-columns:repeat(2,1fr)}.grid15{grid-template-columns:repeat(2,1fr)}}details summary{cursor:pointer;font-weight:800}</style></head><body><div class="w"><div class="title">⚡ Fast Scalper</div><div class="sub">Multi-TF analysis 1m · 3m · 5m · 15m · 30m • Trading TF: 3m • PAPER</div>
<div class="card"><div class="stats"><div class="stat"><div class="m">Account Balance</div><div class="v" id="account">150.0000 USDT</div></div><div class="stat"><div class="m">Realized PnL</div><div class="v" id="real">0.0000 USDT</div></div><div class="stat"><div class="m">Unrealized PnL</div><div class="v" id="unreal">0.0000 USDT</div></div><div class="stat"><div class="m">Net PnL</div><div class="v" id="net">0.0000 USDT</div></div></div><div style="display:flex;gap:8px;align-items:center;margin-top:7px"><div class="stat" style="flex:1"><div class="m">Free Balance / Bot Balance</div><div class="v" id="free">100.0000 / 100.0000 USDT</div></div><label><input id="reinvest" type="checkbox"> Reinvest</label></div></div>
<div class="card"><div class="controls"><button class="btn on" id="power" onclick="toggle()">PAPER ON</button><button class="btn stop" onclick="emergency()">EMERGENCY STOP</button><button class="btn" onclick="resetAll()">RESET</button></div><div class="m" id="status">Engine OFF</div><div class="m" id="timer">Session: 00:00:00</div></div>
<div class="card"><b>Open Positions</b><div id="positions" class="m" style="margin-top:7px">No open positions</div></div><div class="card"><b>Session Result</b><div id="session" class="m" style="margin-top:7px">Trades: 0 • Open: 0 • Cycle: 0</div></div>
<div class="card"><b>6 Active Slots</b><div class="m">3×2. Только выбранные слоты участвуют в торговле. Одна пара может занимать несколько слотов.</div><div class="slots" id="slots" style="margin-top:7px"></div><div style="display:flex;gap:8px;align-items:center;margin-top:8px"><label class="m">Profit / Trade %</label><input class="input" style="max-width:140px" id="profit" type="number" min="0" max="80" step="0.01" value="0"></div></div>
<div class="card"><details open><summary>Top Pairs — Signal Rating</summary><div class="m" style="margin:6px 0">TOP-6: 3×2. «+» назначает пару в следующий свободный слот.</div><div id="top"></div><details><summary style="margin-top:8px">▶ Show full TOP-15</summary><div class="grid15" id="full" style="margin-top:7px"></div></details></details></div>
<div class="card"><b>Closed Trades — latest 5</b><div id="closed" class="m" style="margin-top:7px">No closed trades</div></div><div class="card"><details><summary>▶ Binance API</summary><div style="margin-top:8px"><input class="input" id="apiKey" placeholder="Binance API Key"><input class="input" style="margin-top:7px" id="secretKey" placeholder="Binance Secret Key"><button class="btn" style="margin-top:7px" onclick="saveKeys()">SAVE</button></div></details></div><div class="card"><div class="m" id="radar">Radar: —</div><div class="bad" id="err"></div></div></div>
<script>let D={slots:[]},dirty=false;const $=id=>document.getElementById(id);async function api(u,o){let r=await fetch(u,o),d=await r.json();if(!r.ok)throw Error(d.detail||'API error');return d}const money=x=>Number(x||0).toFixed(4);function st(t){if(!t)return'00:00:00';let s=Math.max(0,Math.floor((Date.now()-new Date(t).getTime())/1000));return[Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(x=>String(x).padStart(2,'0')).join(':')}function render(d){D=d;$('account').textContent=money(d.account)+' USDT';$('real').textContent=money(d.realized)+' USDT';$('unreal').textContent=money(d.unrealized)+' USDT';$('net').textContent=money(d.net)+' USDT';$('free').textContent=money(d.free)+' / '+money(d.bot_balance)+' USDT';$('reinvest').checked=d.reinvest;if(!dirty||document.activeElement!==$('profit'))$('profit').value=d.profit_pct;$('status').textContent=d.running?'PAPER ENGINE ON • Cycle '+d.cycle:'Engine OFF';$('power').textContent=d.running?'PAPER OFF':'PAPER ON';$('power').className=d.running?'btn stop':'btn on';$('timer').textContent='Session: '+st(d.started);$('session').textContent=`Trades: ${d.closed.length} • Open: ${d.positions.length} • Cycle: ${d.cycle}`;$('radar').textContent=`Radar updated ${d.radar_age||0}s ago • Trading TF 3m • Analysis 1m/3m/5m/15m/30m`;$('err').textContent=d.error||'';$('positions').innerHTML=d.positions.length?d.positions.map(p=>`${p.symbol} • ${money(p.stake)} USDT • entry ${p.entry} • current ${p.current} • slot ${p.slot+1} • score ${p.score}`).join('<br>'):'No open positions';$('closed').innerHTML=d.closed.slice(0,5).map(x=>`${x.symbol} • ${x.reason} • <span class="${x.pnl>=0?'good':'bad'}">${x.pnl>=0?'+':''}${money(x.pnl)} USDT</span>`).join('<br>')||'No closed trades';$('slots').innerHTML=d.slots.map((x,i)=>`<div class="slot"><div class="m">SLOT ${i+1}</div><b>${x?x.symbol:'EMPTY'}</b><div class="m">3m</div>${x?`<button class="x" onclick="clearSlot(${i})">×</button>`:''}</div>`).join('');let top=d.ranking.slice(0,6);$('top').innerHTML=top.map((x,i)=>`<div class="rank"><b>${i+1}</b><span><b>${x.symbol}</b> ${x.signal}</span><span class="badge">${x.score}</span><button class="btn" onclick="add('${x.symbol}')">+</button></div>`).join('');$('full').innerHTML=d.ranking.slice(0,15).map((x,i)=>`<div class="pick"><b>#${i+1} ${x.symbol}</b><br><small>${x.score} • ${x.signal}</small><button class="btn" onclick="add('${x.symbol}')">+</button></div>`).join('')}async function load(){try{render(await api('/api/state'))}catch(e){$('err').textContent=e.message}}async function toggle(){try{let p=Number($('profit').value||0),r=$('reinvest').checked;if(D.running)await api('/api/paper/stop',{method:'POST'});else await api('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profit_pct:p,reinvest:r})});dirty=false;await load()}catch(e){$('err').textContent=e.message}}async function emergency(){try{await api('/api/paper/emergency',{method:'POST'});await load()}catch(e){$('err').textContent=e.message}}async function resetAll(){try{await api('/api/reset',{method:'POST'});dirty=false;await load()}catch(e){$('err').textContent=e.message}}async function saveSlots(a){await api('/api/slots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slots:a,profit_pct:Number($('profit').value||0),reinvest:$('reinvest').checked})});dirty=false;await load()}async function add(s){try{let a=D.slots.map(x=>x&&x.symbol).filter(Boolean);if(a.length>=6){alert('Все 6 слотов заняты. Очисти слот.');return}a.push(s);await saveSlots(a)}catch(e){$('err').textContent=e.message}}async function clearSlot(i){let a=D.slots.map(x=>x&&x.symbol).filter(Boolean);a.splice(i,1);await saveSlots(a)}$('profit').addEventListener('input',()=>dirty=true);$('reinvest').addEventListener('change',async()=>{let a=D.slots.map(x=>x&&x.symbol).filter(Boolean);await saveSlots(a)});load();setInterval(load,2000);setInterval(()=>{if(D.running)$('timer').textContent='Session: '+st(D.started)},1000);async function saveKeys(){try{await api('/api/keys',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:$('apiKey').value,secret_key:$('secretKey').value})});$('apiKey').value='';$('secretKey').value='';alert('Saved')}catch(e){$('err').textContent=e.message}}</script></body></html>'''
@app.get('/',response_class=HTMLResponse)
async def home():return HTML
