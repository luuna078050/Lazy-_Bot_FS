from __future__ import annotations
import json,os,subprocess,sys,threading,time
from typing import Any
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse
from .exchange_gateway import gateway
from .market_radar import RADAR
from .profit_first_engine_v4 import start_paper,stop_paper,emergency_stop_paper,snapshot as paper_snapshot
from . import fixed_app as live_core

app=FastAPI(title='Fast Scalper',version='native-2')
LIVE_PROC=None;LIVE_LOCK=threading.Lock();LIVE_STATE=live_core.LIVE_STATE;LIVE_CONTROL=live_core.LIVE_CONTROL

def pair(v:Any)->str:return str(v or '').strip().upper().replace('-','/')
def paper_report():
 s=paper_snapshot();p=list((s.get('open_positions') or {}).values());return {**s,'positions':p,'open_positions':p,'orders':list((s.get('orders') or {}).values()),'trades':list(s.get('trades') or [])[-30:],'order_history':list(s.get('order_history') or [])[-30:]}

def validate(p):
 capital=float(p.get('capital',0) or 0);pairs=[pair(x) for x in p.get('pairs',[]) if pair(x)];alloc=[float(x) for x in p.get('allocations',[])];tfs=[str(x).lower() for x in p.get('timeframes',[])] or ['3m']*len(pairs)
 if not 1<=len(pairs)<=10:raise HTTPException(400,'Выберите от 1 до 10 пар')
 if len(alloc)!=len(pairs) or any(x<=0 for x in alloc) or sum(alloc)>100.01:raise HTTPException(400,'Распределение должно быть >0% и не превышать 100%')
 if capital<=0:raise HTTPException(400,'Капитал должен быть больше 0 USDT')
 if len(tfs)!=len(pairs) or any(x not in {'1m','3m','5m'} for x in tfs):raise HTTPException(400,'Таймфрейм: 1m / 3m / 5m')
 return capital,pairs,alloc,tfs

@app.get('/api/health')
def health():return {'ok':True,'project':'Fast Scalper','engine':'native-wall-matrix','radar':'websocket'}
@app.get('/api/recommendations')
def recommendations(limit:int=20):
 try:
  rows=RADAR.snapshot(max(10,min(limit,20)));return {'ok':True,'generated_at':time.time(),'refresh_sec':10,'data_source':'Binance WebSocket','radar_status':RADAR.status(),'candidates20':rows[:20],'top5':rows[:5]}
 except Exception as e:return {'ok':False,'error':str(e)[:300],'candidates20':[],'top5':[]}
@app.get('/api/paper/status')
def paper_status():return paper_report()
@app.post('/api/paper/start')
def paper_start(p:dict[str,Any]):return {'ok':True,**start_paper(p,gateway)}
@app.post('/api/paper/stop')
def paper_stop():return {'ok':True,**stop_paper(gateway)}
@app.post('/api/paper/emergency-stop')
def paper_emergency():return {'ok':True,**emergency_stop_paper(gateway)}
@app.get('/api/session/report/{mode}')
def session_report(mode:str):
 if mode.upper()=='PAPER':return paper_report()
 try:s=json.loads(LIVE_STATE.read_text()) if LIVE_STATE.exists() else {}
 except Exception:s={}
 with LIVE_LOCK:s['running']=bool(LIVE_PROC and LIVE_PROC.poll() is None)
 s['mode']='LIVE';return s
@app.post('/api/live/start')
def live_start(p:dict[str,Any]):
 global LIVE_PROC
 capital,pairs,alloc,tfs=validate(p);key=str(p.get('api_key','')).strip();secret=str(p.get('api_secret','')).strip()
 if not key or not secret:raise HTTPException(400,'Для LIVE нужны API Key и Secret')
 with LIVE_LOCK:
  if LIVE_PROC and LIVE_PROC.poll() is None:raise HTTPException(409,'LIVE уже запущен')
 try:
  g=gateway('binance');g.exchange.apiKey=key;g.exchange.secret=secret;g.load_markets();b=g.exchange.fetch_balance();free=float((b.get('free') or {}).get('USDT') or 0)
  if capital>free+1e-9:raise HTTPException(400,f'Недостаточно свободного USDT: {free:.4f}')
 except HTTPException:raise
 except Exception as e:raise HTTPException(400,f'Binance preflight: {str(e)[:240]}')
 LIVE_CONTROL.write_text(json.dumps({'command':'RUN'}));env=os.environ.copy();env.update({'BINANCE_API_KEY':key,'BINANCE_API_SECRET':secret,'FAST_SCALPER_CAPITAL_USDT':str(capital),'FAST_SCALPER_PAIRS':','.join(pairs),'FAST_SCALPER_ALLOCATIONS':','.join(map(str,alloc)),'FAST_SCALPER_TIMEFRAMES':','.join(tfs),'FAST_SCALPER_LIVE':'true','LIVE_TRADING':'true','LIVE_TRADING_ARMED':'true','TRADING_MODE':'live','FAST_SCALPER_STATE_FILE':str(LIVE_STATE),'FAST_SCALPER_CONTROL_FILE':str(LIVE_CONTROL)})
 LIVE_PROC=subprocess.Popen([sys.executable,'-m','scripts.fast_scalper_3m'],cwd=os.getcwd(),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,text=True)
 return {'ok':True,'running':True,'mode':'LIVE'}
@app.post('/api/live/stop')
def live_stop():
 global LIVE_PROC
 with LIVE_LOCK:p=LIVE_PROC
 if p and p.poll() is None:p.terminate()
 with LIVE_LOCK:LIVE_PROC=None
 return {'ok':True,'running':False}
@app.post('/api/live/emergency-stop')
def live_emergency():
 global LIVE_PROC
 LIVE_CONTROL.write_text(json.dumps({'command':'EMERGENCY_STOP'}));deadline=time.time()+10
 while time.time()<deadline:
  with LIVE_LOCK:p=LIVE_PROC
  if not p or p.poll() is not None:break
  time.sleep(.2)
 with LIVE_LOCK:p=LIVE_PROC
 if p and p.poll() is None:p.terminate()
 with LIVE_LOCK:LIVE_PROC=None
 return {'ok':True,'running':False,'stop_type':'EMERGENCY_STOP'}

HTML=r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Fast Scalper</title><style>
:root{--bg:#07090b;--panel:#0c1013;--line:#2b1218;--red:#ff3040;--green:#2cff86;--gold:#ffc02e;--muted:#87909a}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f1f3f5;font:14px/1.35 Inter,Roboto,system-ui,-apple-system,sans-serif}.app{max-width:720px;margin:auto;padding:10px 12px 30px}.bar{display:flex;align-items:center;justify-content:space-between;gap:8px;position:sticky;top:0;background:rgba(7,9,11,.96);z-index:5;padding:8px 0}.brand{font-weight:900;letter-spacing:.4px}.brand i{color:var(--red);font-style:normal}.liveDot{width:8px;height:8px;border-radius:50%;background:#666;display:inline-block;margin-right:5px}.on{background:var(--green)}button,input,select{font:inherit}.switches{display:flex;gap:5px}.sw{border:1px solid #333;background:#171b20;color:#9aa1a9;border-radius:20px;padding:7px 11px;font-weight:800}.sw.active{background:#087d3d;border-color:#2cff86;color:#fff}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:12px;margin:8px 0}.hero{display:grid;grid-template-columns:1.15fr .85fr;gap:8px}.label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px}.pnl{font-size:28px;font-weight:900;color:var(--gold);margin-top:2px}.balance{font-size:21px;font-weight:900}.timer{font:800 22px/1.1 ui-monospace,SFMono-Regular,monospace}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:9px}.metric{border-top:1px solid #24151a;padding-top:7px}.metric b{display:block;font-size:14px}.metric small{color:var(--muted)}.section{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}.section h3{margin:0;font-size:15px;color:#fff}.status{font-size:11px;color:var(--muted)}.intel{display:grid;grid-template-columns:1fr 1fr;gap:7px}.signal{border:1px solid #25151a;border-radius:12px;padding:9px;background:#090c0f}.signalTop{display:flex;justify-content:space-between;align-items:center}.sym{font-weight:900}.score{color:var(--green);font-weight:900}.sub{color:#9aa1a9;font-size:11px;margin-top:3px}.matrix{display:grid;grid-template-columns:repeat(5,1fr);gap:3px;margin-top:7px}.tf{border:1px solid #242a30;border-radius:6px;padding:4px 2px;text-align:center;font-size:10px}.tf.up{border-color:#17683d;color:var(--green)}.tf.down{border-color:#6c2029;color:#ff6974}.wall{display:flex;justify-content:space-between;margin-top:6px;font-size:11px}.bull{color:var(--green)}.bear{color:#ff6974}.neutral{color:#ffc02e}.position{border:1px solid #1e573a;background:#09120d;border-radius:12px;padding:10px}.posGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:7px}.bigNum{font-weight:900}.order{border:1px solid #3e3312;background:#11100a;border-radius:10px;padding:8px;margin-top:6px}.recent{display:flex;justify-content:space-between;border-bottom:1px solid #1b2025;padding:7px 0;font-size:12px}.recent:last-child{border:0}.profit{color:var(--green)}.loss{color:#ff6974}.settings{display:grid;grid-template-columns:1fr 1fr;gap:7px}.settings input,.settings select{width:100%;background:#11161a;color:#fff;border:1px solid #30363c;border-radius:9px;padding:9px}.actions{display:flex;gap:6px}.actions button{flex:1;border:1px solid #444;background:#171b20;color:#ddd;border-radius:10px;padding:10px;font-weight:900}.actions .go{background:#087d3d;border-color:#2cff86;color:#fff}.actions .stop{background:#341016;border-color:#ff3040;color:#fff}.note{color:var(--muted);font-size:11px;margin-top:6px}@media(max-width:520px){.hero{grid-template-columns:1fr 1fr}.metrics{grid-template-columns:1fr 1fr}.intel{grid-template-columns:1fr}.pnl{font-size:24px}}
</style></head><body><main class="app"><div class="bar"><div class="brand">⚡ <i>FAST SCALPER</i></div><div class="switches"><button id="paper" class="sw active" onclick="start('PAPER')"><span class="liveDot" id="pd"></span>PAPER</button><button id="live" class="sw" onclick="start('LIVE')">LIVE</button></div></div>
<div class="card hero"><div><div class="label">Сессия</div><div id="session" class="bigNum">Остановлен</div><div id="timer" class="timer">00:00:00</div></div><div><div class="label">Баланс</div><div id="bal" class="balance">50.0000</div><div class="label" style="margin-top:5px">Свободно</div><div id="free" class="bigNum">50.0000</div></div></div>
<div class="card"><div class="label">PnL / Equity</div><div id="pnl" class="pnl">0.0000 USDT</div><div id="pnlpct" class="sub">0.00%</div><div class="metrics"><div class="metric"><small>Realized</small><b id="real">0.0000</b></div><div class="metric"><small>Unrealized</small><b id="unreal">0.0000</b></div><div class="metric"><small>Net</small><b id="net">0.0000</b></div><div class="metric"><small>Equity</small><b id="eq">50.0000</b></div></div></div>
<div class="card"><div class="section"><h3>🚀 РЫНОЧНАЯ АНАЛИТИКА</h3><span id="refresh" class="status">обновление 10с</span></div><div id="intel" class="intel"></div></div>
<div class="card"><div class="section"><h3>📌 ОРДЕР / ПОЗИЦИЯ</h3><span id="flow" class="status">ожидание</span></div><div id="position">Нет открытой позиции</div><div id="orders"></div></div>
<div class="card"><div class="section"><h3>📜 ПОСЛЕДНИЕ СДЕЛКИ</h3><span class="status">последние 30</span></div><div id="recent">Нет сделок</div></div>
<div class="card"><div class="section"><h3>⚙ НАСТРОЙКИ</h3></div><div class="settings"><div><div class="label">Капитал USDT</div><input id="capital" type="number" value="50" min="1" step="1"></div><div><div class="label">Таймфрейм сделки</div><select id="tf"><option>3m</option><option>1m</option><option>5m</option></select></div><div><div class="label">Пара</div><input id="pair" placeholder="BTC/USDT"></div><div><div class="label">Доля</div><input id="alloc" type="number" value="100" min="1" max="100"></div></div><div class="actions" style="margin-top:8px"><button class="go" onclick="startPaper()">▶ ЗАПУСТИТЬ PAPER</button><button class="stop" onclick="stopBot()">■ STOP</button></div><div class="note">Логика: 1m / 3m / 5m / 15m / 30m + движение стенок. Идеал 0.30 USDT/мин на 50 USDT; допустимо 0.23; ниже 0.15 — выход/отмена. Перестановка ордера не чаще 1 раза в 5 секунд.</div></div>
</main><script>
let state={started:0,running:false},rank=[];const $=x=>document.getElementById(x);function esc(x){return String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}function fmt(x){return Number(x||0).toFixed(4)}function timer(){if(state.running&&state.started){let s=Math.max(0,Math.floor(Date.now()/1000-state.started));let h=Math.floor(s/3600),m=Math.floor(s%3600/60),z=s%60;$('timer').textContent=[h,m,z].map(x=>String(x).padStart(2,'0')).join(':')}requestAnimationFrame(timer)}
async function startPaper(){let p=($('pair').value||'BTC/USDT').trim().toUpperCase();let r=await fetch('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({capital:+$('capital').value,pairs:[p],allocations:[+$('alloc').value],timeframes:[$('tf').value],fee_pct:.10})});let d=await r.json();if(!r.ok){alert(d.detail||'Ошибка запуска');return}refreshState()}
async function start(mode){if(mode==='PAPER')return startPaper();alert('LIVE оставлен отдельным режимом. Для теста используй PAPER.')}
async function stopBot(){await fetch('/api/paper/stop',{method:'POST'});refreshState()}
function renderRank(){if(!rank.length){$('intel').innerHTML='<div class="status">Радар набирает данные…</div>';return}$('intel').innerHTML=rank.slice(0,6).map((x,i)=>{let tf=['1m','3m','5m','15m','30m'].map(t=>{let v=(x.tf||{})[t]||{};return '<div class="tf '+(v.trend>0?'up':v.trend<0?'down':'')+'">'+t+'<br>'+Number(v.change_pct||0).toFixed(2)+'%</div>'}).join('');let w=x.wall||{};let wc=w.direction==='bullish'?'bull':w.direction==='bearish'?'bear':'neutral';return '<div class="signal"><div class="signalTop"><span class="sym">#'+(i+1)+' '+esc(x.symbol)+'</span><span class="score">'+x.score+'</span></div><div class="sub">'+esc(x.direction)+' · 24ч '+Number(x.change_24h_pct||0).toFixed(2)+'% · цель/мин $'+Number(x.ideal_pnl_per_min_100||0).toFixed(2)+' / допустимо $'+Number(x.acceptable_pnl_per_min_100||0).toFixed(2)+'</div><div class="matrix">'+tf+'</div><div class="wall"><span class="'+wc+'">СТЕНКИ: '+esc(w.direction)+'</span><span>shift B '+Number(w.bid_shift_pct||0).toFixed(2)+'% / A '+Number(w.ask_shift_pct||0).toFixed(2)+'%</span></div></div>'}).join('')}
async function refreshRank(){try{let r=await fetch('/api/recommendations?limit=20');let d=await r.json();if(d.ok){rank=d.top5||[];renderRank();$('refresh').textContent='зафиксировано · '+(d.refresh_sec||10)+'с'}}catch(e){}}
async function refreshState(){try{let r=await fetch('/api/paper/status');let s=await r.json();state.running=!!s.running;state.started=s.started_at?Date.parse(s.started_at)/1000:0;$('session').textContent=state.running?'PAPER работает':'Остановлен';$('bal').textContent=fmt(s.initial_balance||0);$('free').textContent=fmt(s.free_usdt||0);let pnl=Number(s.net_pnl||0);$('pnl').textContent=fmt(pnl)+' USDT';$('pnlpct').textContent=((Number(s.equity_usdt||0)/(Number(s.initial_balance||1))-1)*100).toFixed(2)+'%';$('real').textContent=fmt(s.realized_pnl);$('unreal').textContent=fmt(s.unrealized_pnl);$('net').textContent=fmt(s.net_pnl);$('eq').textContent=fmt(s.equity_usdt);let p=(s.positions||[])[0];$('position').innerHTML=p?'<div class="position"><b>'+esc(p.symbol)+'</b> · вход '+fmt(p.entry_price)+' · сейчас '+fmt(p.current_price)+'<div class="posGrid"><div><span class="label">PnL</span><div class="bigNum">'+fmt(p.unrealized_pnl)+'</div></div><div><span class="label">Стены</span><div class="bigNum">'+esc(p.wall_direction||'—')+'</div></div><div><span class="label">Цель/мин</span><div class="bigNum">$'+fmt(p.acceptable_pnl_per_min)+'</div></div></div></div>':'Нет открытой позиции';let os=s.orders||[];$('orders').innerHTML=os.map(o=>'<div class="order"><b>'+esc(o.symbol)+'</b> · '+o.status+' · лимит '+fmt(o.price)+' · reprice '+o.reprice_count+' · стены '+esc(o.wall_direction||'—')+'</div>').join('');$('flow').textContent=os.length?'ОРДЕР АКТИВЕН':p?'ПОЗИЦИЯ АКТИВНА':'поиск сигнала';let ts=s.trades||[];$('recent').innerHTML=ts.length?ts.slice().reverse().map(t=>'<div class="recent"><span>'+esc(t.symbol)+' · '+esc(t.reason||'EXIT')+'</span><b class="'+(Number(t.net_pnl||0)>=0?'profit':'loss')+'">'+fmt(t.net_pnl)+'</b></div>').join(''):'Нет сделок'}catch(e){}}
setInterval(refreshState,1500);setInterval(refreshRank,10000);refreshState();refreshRank();timer();
</script></body></html>'''
@app.get('/',response_class=HTMLResponse)
def home():return HTML
