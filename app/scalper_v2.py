from __future__ import annotations
import threading,time
from datetime import datetime,timezone
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
try:
 from .market_radar import RADAR
except Exception: RADAR=None
app=FastAPI(title='Fast Scalper v2')
LOCK=threading.RLock(); STOP=threading.Event(); WORKER=None
UNIVERSE=['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','TRXUSDT','LINKUSDT','SUIUSDT','AVAXUSDT','TONUSDT','LTCUSDT','DOTUSDT','BCHUSDT','NEARUSDT','APTUSDT','ATOMUSDT','UNIUSDT','FILUSDT']
FALLBACK={'BTCUSDT':79000,'ETHUSDT':2500,'BNBUSDT':700,'SOLUSDT':100,'XRPUSDT':2.1,'DOGEUSDT':.22,'ADAUSDT':.22,'TRXUSDT':.34,'LINKUSDT':12,'SUIUSDT':3.5,'AVAXUSDT':25,'TONUSDT':3.2,'LTCUSDT':100,'DOTUSDT':4,'BCHUSDT':550,'NEARUSDT':2.5,'APTUSDT':4.5,'ATOMUSDT':4.5,'UNIUSDT':8,'FILUSDT':1.5}
STATE={'running':False,'initial_balance':1000.,'account_balance':1000.,'free_balance':1000.,'realized':0.,'unrealized':0.,'net':0.,'pairs':[],'timeframes':[],'open':[],'closed':[],'orders':[],'error':None,'started_at':None,'last_cycle':None,'cycle':0,'trade_delay':8,'capital_per_trade':100.,'ranked':[]}
class StartReq(BaseModel):
 capital:float=1000.; pairs:list[str]=[]; timeframes:list[str]=[]; trade_delay:int=8
class PairReq(BaseModel): pairs:list[str]=[]; timeframes:list[str]=[]
def now():return datetime.now(timezone.utc).isoformat()
def get_price(s):
 if RADAR:
  try:
   with RADAR.lock:p=float((RADAR.tickers.get(s) or {}).get('c') or 0)
   if p>0:return p
  except Exception:pass
 return FALLBACK.get(s,1.)
def ranking():
 rows=[]
 for s in UNIVERSE:
  pct=0.;vol=0.
  if RADAR:
   try:
    with RADAR.lock:t=dict(RADAR.tickers.get(s) or {})
    p=float(t.get('c') or 0);o=float(t.get('o') or p or 1);vol=float(t.get('q') or 0)
    if p and o:pct=(p/o-1)*100
   except Exception:pass
  momentum=max(0,min(100,50+pct*8));liq=max(0,min(100,vol/1e9*50));score=round(.65*momentum+.35*liq,2)
  rows.append({'symbol':s,'score':score,'price':get_price(s),'change_24h':round(pct,3),'signal':'HOT' if score>=70 else 'WATCH' if score>=55 else 'NORMAL'})
 rows.sort(key=lambda x:x['score'],reverse=True);return rows
def reset_state(cap=1000.):
 with LOCK:STATE.update({'running':False,'initial_balance':cap,'account_balance':cap,'free_balance':cap,'realized':0.,'unrealized':0.,'net':0.,'pairs':[],'timeframes':[],'open':[],'closed':[],'orders':[],'error':None,'started_at':None,'last_cycle':None,'cycle':0,'trade_delay':8,'capital_per_trade':max(1,cap/3),'ranked':ranking()})
def open_trade(s,tf,a):
 with LOCK:
  if a<=0 or STATE['free_balance']<a or any(x['symbol']==s for x in STATE['open']):return
  p=get_price(s);STATE['free_balance']-=a;pos={'symbol':s,'timeframe':tf,'entry':p,'allocation':a,'opened':time.time(),'opened_at':now()};STATE['open'].append(pos);STATE['orders'].insert(0,{'time':now(),'symbol':s,'side':'BUY','status':'FILLED','price':p,'allocation':a})
def close_trade(pos,reason):
 p=get_price(pos['symbol']);e=float(pos['entry']);a=float(pos['allocation']);gross=(p/e-1)*a;fee=(a+p*(a/e))*.001;net=gross-fee
 with LOCK:
  STATE['free_balance']+=a+net;STATE['account_balance']+=net;STATE['realized']+=net;STATE['closed'].insert(0,{**pos,'exit':p,'gross':gross,'fee':fee,'net':net,'reason':reason,'closed_at':now()});STATE['closed']=STATE['closed'][:100];STATE['orders'].insert(0,{'time':now(),'symbol':pos['symbol'],'side':'SELL','status':'FILLED','price':p,'net':net,'reason':reason});STATE['open']=[x for x in STATE['open'] if x is not pos]
def worker():
 if RADAR:
  try:RADAR.start()
  except Exception:pass
 next_trade=0
 while not STOP.is_set():
  try:
   t=time.time()
   with LOCK:STATE['ranked']=ranking();pairs=list(STATE['pairs']);tfs=list(STATE['timeframes']);delay=STATE['trade_delay']
   if pairs and t>=next_trade:
    with LOCK:opened={x['symbol'] for x in STATE['open']};scores={x['symbol']:x['score'] for x in STATE['ranked']}
    choices=sorted([s for s in pairs if s not in opened],key=lambda s:scores.get(s,0),reverse=True)
    if choices:
     s=choices[0];tf=tfs[pairs.index(s)] if s in pairs else '3m';open_trade(s,tf,min(STATE['capital_per_trade'],STATE['free_balance']))
    next_trade=t+delay
   with LOCK:ps=list(STATE['open'])
   for p in ps:
    if t-p['opened']>=max(4,min(30,delay)):close_trade(p,'PAPER_CYCLE')
   with LOCK:
    u=sum((get_price(x['symbol'])/x['entry']-1)*x['allocation'] for x in STATE['open']);STATE['unrealized']=u;STATE['net']=STATE['account_balance']+u-STATE['initial_balance'];STATE['cycle']+=1;STATE['last_cycle']=now()
  except Exception as e:
   with LOCK:STATE['error']=str(e)[:300]
  time.sleep(1)
 with LOCK:STATE['running']=False
def snap():
 with LOCK:
  u=sum((get_price(x['symbol'])/x['entry']-1)*x['allocation'] for x in STATE['open']);STATE['unrealized']=u;STATE['net']=STATE['account_balance']+u-STATE['initial_balance'];STATE['ranked']=ranking();wins=sum(1 for x in STATE['closed'] if x['net']>0)
  return {**STATE,'open':[dict(x,current=get_price(x['symbol'])) for x in STATE['open']],'session':{'trades':len(STATE['closed']),'wins':wins,'win_rate':round(wins/len(STATE['closed'])*100,1) if STATE['closed'] else 0,'realized':round(STATE['realized'],4),'unrealized':round(u,4),'net':round(STATE['net'],4)}}
@app.get('/',response_class=HTMLResponse)
def home():return HTML
@app.get('/api/health')
def health():return {'ok':True,'running':STATE['running'],'engine':'PAPER v2'}
@app.get('/api/state')
def state():return snap()
@app.get('/api/ranking')
def api_ranking():return {'pairs':ranking()}
@app.post('/api/paper/start')
def start(r:StartReq):
 global WORKER
 p=[x.upper().replace('/','') for x in r.pairs if x.strip()]
 if not p:p=[x['symbol'] for x in ranking()[:3]]
 if len(p)>6:raise HTTPException(400,'Максимум 6 пар')
 tf=[x.lower() for x in r.timeframes] or ['3m']*len(p)
 if len(tf)!=len(p) or any(x not in {'1m','3m','5m'} for x in tf):raise HTTPException(400,'Таймфрейм: 1m, 3m или 5m')
 if r.capital<=0:raise HTTPException(400,'Капитал должен быть больше 0')
 STOP.clear()
 with LOCK:STATE.update({'running':True,'initial_balance':r.capital,'account_balance':r.capital,'free_balance':r.capital,'realized':0.,'unrealized':0.,'net':0.,'pairs':p,'timeframes':tf,'open':[],'closed':[],'orders':[],'error':None,'started_at':now(),'trade_delay':max(5,min(60,r.trade_delay)),'capital_per_trade':r.capital/len(p),'cycle':0})
 if not WORKER or not WORKER.is_alive():WORKER=threading.Thread(target=worker,daemon=True);WORKER.start()
 return snap()
@app.post('/api/paper/stop')
def stop():
 STOP.set()
 with LOCK:STATE['running']=False
 return snap()
@app.post('/api/paper/emergency')
def emergency():
 STOP.set()
 with LOCK:ps=list(STATE['open'])
 for p in ps:close_trade(p,'EMERGENCY_STOP')
 with LOCK:STATE['running']=False
 return snap()
@app.post('/api/reset')
def reset():reset_state();return snap()
@app.post('/api/pairs')
def save_pairs(r:PairReq):
 p=[x.upper().replace('/','') for x in r.pairs if x.strip()]
 if len(p)>6:raise HTTPException(400,'Максимум 6 пар')
 tf=[x.lower() for x in r.timeframes] or ['3m']*len(p)
 if len(tf)!=len(p):raise HTTPException(400,'Количество таймфреймов не совпадает')
 with LOCK:STATE['pairs']=p;STATE['timeframes']=tf
 return snap()
HTML='''<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper v2</title><style>*{box-sizing:border-box}body{margin:0;background:#08101e;color:#eef4ff;font-family:system-ui}.wrap{max-width:820px;margin:auto;padding:14px}.title{font-size:28px;font-weight:900}.muted{color:#8996ae}.card{background:#111b2e;border:1px solid #273653;border-radius:16px;padding:14px;margin:10px 0}h2{font-size:18px;margin:4px 0 12px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.metric{font-size:12px;color:#8d9ab2}.val{font-size:20px;font-weight:800}.buttons{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}.btn{border:0;border-radius:12px;padding:14px;font-weight:900;color:#fff;font-size:15px}.on{background:#078e55}.off{background:#b53145}.gray{background:#293a59}.pair{display:grid;grid-template-columns:1fr 80px;gap:7px;margin:7px 0}.sel{width:100%;background:#0b1424;color:#fff;border:1px solid #2a3b59;border-radius:10px;padding:10px}.rank{display:grid;grid-template-columns:32px 1fr 65px 75px 65px;gap:7px;align-items:center;padding:9px 3px;border-bottom:1px solid #22304a}.check{width:20px;height:20px}.score{font-weight:900}.hot{color:#48eb9b}.watch{color:#ffd166}.pos{padding:8px 2px;border-bottom:1px solid #22304a}.good{color:#48eb9b}.bad{color:#ff687a}.err{background:#351624;color:#ff7180;padding:8px;border-radius:8px;margin-top:8px}@media(max-width:600px){.grid{grid-template-columns:1fr 1fr}.rank{grid-template-columns:28px 1fr 60px 60px}.chg{display:none}.buttons{grid-template-columns:1fr 1fr}.pair{grid-template-columns:1fr 70px}}</style></head><body><div class="wrap"><div class="title">⚡ FAST SCALPER v2</div><div class="muted">PAPER • рейтинг • выбор пар • статистика</div><div class="card"><div class="grid"><div><div class="metric">Баланс</div><div id="bal" class="val">1000</div></div><div><div class="metric">Свободно</div><div id="free" class="val">1000</div></div><div><div class="metric">Realized PnL</div><div id="real" class="val">0</div></div><div><div class="metric">Net PnL</div><div id="net" class="val">0</div></div></div></div><div class="card"><div class="buttons"><button id="on" class="btn on">PAPER ON</button><button id="em" class="btn off">EMERGENCY STOP</button><button id="rs" class="btn gray">RESET</button></div><div id="status" class="muted" style="margin-top:10px">OFF</div><div id="error"></div></div><div class="card"><h2>Выбор пар</h2><button id="a3" class="btn on" style="width:100%;margin-bottom:7px">АВТО TOP-3 ПО РЕЙТИНГУ</button><button id="a5" class="btn gray" style="width:100%;margin-bottom:7px">АВТО TOP-5 ПО РЕЙТИНГУ</button><div id="selected"></div><button id="save" class="btn gray" style="width:100%;margin-top:7px">СОХРАНИТЬ ВЫБОР</button><div class="muted" style="margin-top:7px">Выбирай 1–6 пар вручную или автоматически TOP-3/TOP-5.</div></div><div class="card"><h2>Рейтинг пар</h2><div id="ranking">Загрузка…</div></div><div class="card"><h2>Открытые позиции</h2><div id="open">Нет</div></div><div class="card"><h2>Статистика</h2><div id="stats">Сделок: 0 • Побед: 0 • Win rate: 0% • Realized: 0 • Net: 0</div></div><div class="card"><h2>Последние сделки</h2><div id="closed">Нет закрытых сделок</div></div></div><script>let S={pairs:[],timeframes:[],ranked:[]};const $=s=>document.querySelector(s);async function api(u,o){let r=await fetch(u,o),j=await r.json();if(!r.ok)throw Error(j.detail||JSON.stringify(j));return j}function render(){let opts=S.ranked.map(x=>`<option value="${x.symbol}">${x.symbol} • ${x.score}</option>`).join('');let h='';for(let i=0;i<6;i++){let p=S.pairs[i]||'',tf=S.timeframes[i]||'3m';h+=`<div class="pair"><select class="sel sp"><option value="">— не выбрано —</option>${opts}</select><select class="sel st"><option ${tf==='1m'?'selected':''}>1m</option><option ${tf==='3m'?'selected':''}>3m</option><option ${tf==='5m'?'selected':''}>5m</option></select></div>`}$('#selected').innerHTML=h;document.querySelectorAll('.sp').forEach((x,i)=>x.value=S.pairs[i]||'');let c=new Set(S.pairs);$('#ranking').innerHTML=S.ranked.slice(0,20).map((x,i)=>`<label class="rank"><input class="check rc" type="checkbox" data-p="${x.symbol}" ${c.has(x.symbol)?'checked':''}><b>#${i+1}</b><b>${x.symbol}</b><span class="score ${x.score>=70?'hot':x.score>=55?'watch':''}">${x.score}</span><span class="chg">${x.change_24h.toFixed(3)}%</span><span>${x.signal}</span></label>`).join('')}function collect(){let sp=[...document.querySelectorAll('.sp')],pairs=sp.map(x=>x.value).filter(Boolean),timeframes=sp.map((_,i)=>document.querySelectorAll('.st')[i].value).slice(0,pairs.length);return{pairs,timeframes}}async function load(){try{S=await api('/api/state');$('#bal').textContent=S.account_balance.toFixed(2)+' USDT';$('#free').textContent=S.free_balance.toFixed(2)+' USDT';$('#real').textContent=S.realized.toFixed(4);$('#net').textContent=S.net.toFixed(4);$('#status').textContent=S.running?'🟢 PAPER ON • cycle '+S.cycle:'🔴 PAPER OFF';$('#error').innerHTML=S.error?`<div class="err">${S.error}</div>`:'';$('#open').innerHTML=S.open.length?S.open.map(x=>`<div class="pos"><b>${x.symbol}</b> • ${x.timeframe} • ${x.entry} → ${x.current}</div>`).join(''):'Нет';$('#stats').textContent=`Сделок: ${S.session.trades} • Побед: ${S.session.wins} • Win rate: ${S.session.win_rate}% • Realized: ${S.session.realized.toFixed(4)} • Unrealized: ${S.session.unrealized.toFixed(4)} • Net: ${S.session.net.toFixed(4)}`;$('#closed').innerHTML=S.closed.length?S.closed.slice(0,8).map(x=>`<div class="pos"><b>${x.symbol}</b> • ${x.reason} • <span class="${x.net>=0?'good':'bad'}">${x.net>=0?'+':''}${x.net.toFixed(4)} USDT</span></div>`).join(''):'Нет';render()}catch(e){$('#error').innerHTML='<div class="err">API: '+e.message+'</div>'}}async function save(){try{S=await api('/api/pairs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collect())});load()}catch(e){alert(e.message)}}async function start(){try{let d=collect();if(!d.pairs.length){d.pairs=S.ranked.slice(0,3).map(x=>x.symbol);d.timeframes=d.pairs.map(()=> '3m')}await api('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({capital:1000,pairs:d.pairs,timeframes:d.timeframes,trade_delay:8})});load()}catch(e){alert('PAPER ON: '+e.message)}}async function auto(n){S.pairs=S.ranked.slice(0,n).map(x=>x.symbol);S.timeframes=S.pairs.map(()=> '3m');save()}$('#on').onclick=start;$('#em').onclick=async()=>{await api('/api/paper/emergency',{method:'POST'});load()};$('#rs').onclick=async()=>{await api('/api/reset',{method:'POST'});load()};$('#save').onclick=save;$('#a3').onclick=()=>auto(3);$('#a5').onclick=()=>auto(5);setInterval(load,2000);load();</script></body></html>'''
reset_state()
