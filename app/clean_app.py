from __future__ import annotations
import json, os, subprocess, sys, threading, time
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from .exchange_gateway import gateway
from .market_radar import RADAR
from .profit_first_engine_v4 import start_paper, stop_paper, emergency_stop_paper, snapshot as paper_snapshot
from . import fixed_app as live_core

app=FastAPI(title='Fast Scalper',version='native-3')
LIVE_PROC=None; LIVE_LOCK=threading.Lock(); LIVE_STATE=live_core.LIVE_STATE; LIVE_CONTROL=live_core.LIVE_CONTROL

def pair(v:Any)->str:return str(v or '').strip().upper().replace('-','/')
def paper_report():
    s=paper_snapshot(); return {**s,'positions':list((s.get('open_positions') or {}).values()),'open_positions':list((s.get('open_positions') or {}).values()),'orders':list((s.get('orders') or {}).values()),'trades':list(s.get('trades') or [])[-30:],'order_history':list(s.get('order_history') or [])[-30:]}
def validate(p):
    capital=float(p.get('capital',0) or 0); pairs=[pair(x) for x in p.get('pairs',[]) if pair(x)]; alloc=[float(x) for x in p.get('allocations',[])]; tfs=[str(x).lower() for x in p.get('timeframes',[])] or ['3m']*len(pairs)
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
        rows=RADAR.snapshot(max(10,min(limit,20)));return {'ok':True,'generated_at':time.time(),'refresh_sec':5,'data_source':'Binance WebSocket','radar_status':RADAR.status(),'candidates20':rows[:20],'top5':rows[:5]}
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
    LIVE_PROC=subprocess.Popen([sys.executable,'-m','scripts.fast_scalper_3m'],cwd=os.getcwd(),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,text=True);return {'ok':True,'running':True,'mode':'LIVE'}
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
:root{--bg:#07090b;--panel:#0c1013;--line:#292f35;--red:#ff3040;--green:#20e875;--gold:#ffc02e;--muted:#87909a}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f2f4f6;font:14px/1.35 system-ui,-apple-system,Roboto,sans-serif}.app{max-width:720px;margin:auto;padding:8px 12px 28px}.bar{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 0;background:rgba(7,9,11,.97)}.brand{font-weight:950;font-size:19px}.brand i{font-style:normal;color:var(--red)}button,input,select{font:inherit}.switches{display:flex;gap:5px}.sw{border:1px solid #3b4249;background:#171b20;color:#9aa1a9;border-radius:20px;padding:8px 12px;font-weight:900}.sw.active{background:#087d3d;border-color:var(--green);color:#fff}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:12px;margin:8px 0}.session{display:grid;grid-template-columns:1fr 1fr;gap:8px}.label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px}.big{font-weight:950}.timer{font:900 24px/1.1 ui-monospace,monospace;margin:3px 0 8px}.balance{font-size:22px;font-weight:950}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:9px}.metric{border-top:1px solid #252b30;padding-top:7px}.metric b{display:block}.metric small{color:var(--muted)}.pnl{font-size:28px;font-weight:950;color:var(--gold)}.controls{display:flex;gap:7px}.controls button{flex:1;border:1px solid #3b4249;background:#171b20;color:#fff;border-radius:10px;padding:11px 7px;font-weight:950;transition:.08s transform,.08s filter}.controls button:active,.controls button.pressed{transform:scale(.96);filter:brightness(1.35)}.go{background:#087d3d!important;border-color:var(--green)!important}.stop{background:#341016!important;border-color:var(--red)!important}.section{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}.section h3{margin:0;font-size:15px}.status{font-size:11px;color:var(--muted)}.intel{display:grid;grid-template-columns:1fr 1fr;gap:7px}.signal{border:1px solid #252b30;border-radius:12px;padding:9px;background:#090c0f;cursor:pointer;transition:.12s}.signal:active,.signal.selected{border-color:var(--green);box-shadow:0 0 0 1px rgba(32,232,117,.25)}.top{display:flex;justify-content:space-between;align-items:center}.sym{font-weight:950}.score{color:var(--green);font-weight:950}.sub{color:#9aa1a9;font-size:11px}.matrix{display:grid;grid-template-columns:repeat(5,1fr);gap:3px;margin-top:7px}.tfm{border:1px solid #242a30;border-radius:6px;padding:4px 2px;text-align:center;font-size:10px}.up{border-color:#17683d;color:var(--green)}.down{border-color:#6c2029;color:#ff6974}.wall{display:flex;justify-content:space-between;margin-top:6px;font-size:11px}.bull{color:var(--green)}.bear{color:#ff6974}.neutral{color:var(--gold)}.position{border:1px solid #1e573a;background:#09120d;border-radius:12px;padding:10px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:8px}.order{border:1px solid #4b3b10;background:#11100a;border-radius:10px;padding:9px}.recent{display:flex;justify-content:space-between;border-bottom:1px solid #1b2025;padding:7px 0;font-size:12px}.profit{color:var(--green)}.loss{color:#ff6974}.settings{display:grid;grid-template-columns:1fr 1fr;gap:7px}.settings input,.settings select{width:100%;background:#11161a;color:#fff;border:1px solid #30363c;border-radius:9px;padding:10px}.note{color:var(--muted);font-size:11px;margin-top:7px}@media(max-width:520px){.intel{grid-template-columns:1fr}.metrics{grid-template-columns:1fr 1fr}}
</style></head><body><main class="app"><div class="bar"><div class="brand">⚡ <i>FAST SCALPER</i></div><div class="switches"><button id="paper" class="sw active">● PAPER</button><button id="live" class="sw">LIVE</button></div></div>
<div class="card"><div class="session"><div><div class="label">Сессия</div><div id="session" class="big">Остановлен</div><div id="timer" class="timer">00:00:00</div></div><div><div class="label">Баланс счёта</div><div id="bal" class="balance">50.0000</div><div class="label" style="margin-top:5px">Свободно</div><div id="free" class="big">50.0000</div></div></div><div class="controls" style="margin-top:9px"><button id="startBtn" class="go">▶ ЗАПУСТИТЬ PAPER</button><button id="stopBtn" class="stop">■ STOP</button></div></div>
<div class="card"><div class="label">PnL / Equity</div><div id="pnl" class="pnl">0.0000 USDT</div><div id="pnlpct" class="sub">0.00%</div><div class="metrics"><div class="metric"><small>Realized</small><b id="real">0.0000</b></div><div class="metric"><small>Unrealized</small><b id="unreal">0.0000</b></div><div class="metric"><small>Invested</small><b id="invested">0.0000</b></div><div class="metric"><small>Equity</small><b id="eq">50.0000</b></div></div></div>
<div class="card"><div class="section"><h3>🚀 РЫНОЧНАЯ АНАЛИТИКА</h3><span id="refresh" class="status">обновление</span></div><div id="intel" class="intel">Загрузка...</div></div>
<div class="card"><div class="section"><h3>📌 ОРДЕР / ПОЗИЦИЯ</h3><span id="flow" class="status">ожидание</span></div><div id="position">Нет открытой позиции</div><div id="orders"></div></div>
<div class="card"><div class="section"><h3>📜 ПОСЛЕДНИЕ СДЕЛКИ</h3><span class="status">последние 30</span></div><div id="recent">Нет сделок</div></div>
<div class="card"><div class="section"><h3>⚙ НАСТРОЙКИ</h3></div><div class="settings"><div><div class="label">Капитал USDT</div><input id="capital" type="number" value="50" min="1" step="1"></div><div><div class="label">Таймфрейм сделки</div><select id="tf"><option>3m</option><option>1m</option><option>5m</option></select></div><div><div class="label">Выбранная пара</div><input id="pair" placeholder="Выберите пару выше"></div><div><div class="label">Доля капитала</div><input id="alloc" type="number" value="100" min="1" max="100"></div></div><div class="note">Нажмите на любую пару в рейтинге — она станет выбранной. 15m/30m используются только внутри аналитики; таймфрейм сделки — 1m/3m/5m.</div></div></main><script>
const $=id=>document.getElementById(id);let state={running:false,started:0,initial:50},selected='';
function esc(x){return String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}
function n(x){return Number(x||0).toFixed(4)}
function press(el,txt){el.classList.add('pressed');let old=el.textContent;el.textContent=txt;setTimeout(()=>{el.classList.remove('pressed');el.textContent=old},500)}
function timer(){if(state.running&&state.started){let s=Math.max(0,Math.floor(Date.now()/1000-state.started)),h=Math.floor(s/3600),m=Math.floor(s%3600/60),z=s%60;$('timer').textContent=[h,m,z].map(x=>String(x).padStart(2,'0')).join(':')}requestAnimationFrame(timer)}
function selectPair(p,el){selected=p; $('pair').value=p;document.querySelectorAll('.signal').forEach(x=>x.classList.remove('selected'));if(el)el.classList.add('selected');$('flow').textContent='выбрано '+p}
function row(r,i){let p=esc(r.symbol||r.pair||'');let score=Number(r.score||r.quality||0);let tf=r.matrix||r.tf||{};let wall=r.wall||{};return `<div class="signal ${selected===p?'selected':''}" onclick="selectPair('${p}',this)"><div class="top"><span class="sym">#${i+1} ${p}</span><span class="score">${score.toFixed(0)}</span></div><div class="sub">${esc(r.signal||'WAIT')} · 24h ${(Number(r.change_24h_pct||r.change24h||0)).toFixed(2)}%</div><div class="matrix">${['1m','3m','5m','15m','30m'].map(t=>{let x=tf[t]||{};let c=Number(x.change_pct||0);return `<div class="tfm ${c>0?'up':c<0?'down':''}">${t}<br>${c.toFixed(2)}%</div>`}).join('')}</div><div class="wall"><span class="${wall.direction==='bullish'?'bull':wall.direction==='bearish'?'bear':'neutral'}">СТЕНКИ: ${esc(wall.direction||'neutral')}</span><span>score ${Number(wall.score||0).toFixed(2)}</span></div></div>`}
async function loadRank(){try{let d=await fetch('/api/recommendations?limit=10').then(r=>r.json());let rows=d.candidates20||d.top5||[];$('intel').innerHTML=rows.length?rows.map(row).join(''):'Нет данных';$('refresh').textContent='обновлено '+new Date().toLocaleTimeString()}catch(e){$('intel').textContent='Ошибка аналитики'}}
function render(s){state.running=!!s.running;state.started=s.started_at?Math.floor(new Date(s.started_at).getTime()/1000):state.started;state.initial=Number(s.initial_balance||50);$('session').textContent=state.running?'PAPER запущен':'Остановлен';$('bal').textContent=n(s.account_balance_usdt??s.balance_usdt??s.initial_balance);$('free').textContent=n(s.free_usdt);$('invested').textContent=n(s.invested_usdt);$('real').textContent=n(s.realized_pnl);$('unreal').textContent=n(s.unrealized_pnl);$('net').textContent=n(s.net_pnl);$('eq').textContent=n(s.equity_usdt);let net=Number(s.net_pnl||0);$('pnl').textContent=n(net)+' USDT';$('pnlpct').textContent=((net/state.initial)*100).toFixed(2)+'%';let pos=(s.positions||[])[0];$('position').innerHTML=pos?`<div class="position"><b>${esc(pos.symbol)}</b> · вход ${n(pos.entry_price)} · сейчас ${n(pos.current_price)}<div class="grid3"><div><span class="label">PNL</span><br><b>${n(pos.unrealized_pnl)} USDT</b></div><div><span class="label">Стены</span><br><b>${esc(pos.wall_direction||'neutral')}</b></div><div><span class="label">Цель/мин</span><br><b>${n(pos.acceptable_pnl_per_min||0)} USDT</b></div></div></div>`:'Нет открытой позиции';let os=s.orders||[];$('orders').innerHTML=os.map(o=>`<div class="order"><b>${esc(o.symbol)}</b> · BUY ${esc(o.status)} · цена ${n(o.price)} · ${n(o.requested_usdt)} USDT</div>`).join('');$('flow').textContent=pos?'ПОЗИЦИЯ АКТИВНА':os.length?'ОРДЕР ОЖИДАЕТ':'ожидание';let tr=s.trades||[];$('recent').innerHTML=tr.length?tr.slice().reverse().map(t=>`<div class="recent"><span><b>${esc(t.symbol)}</b> · ${esc(t.reason||'CLOSED')}</span><b class="${Number(t.net_pnl)>=0?'profit':'loss'}">${n(t.net_pnl)} USDT</b></div>`).join(''):'Нет сделок'}
async function refresh(){try{let s=await fetch('/api/paper/status').then(r=>r.json());render(s)}catch(e){}}
async function startPaper(){let p=selected||$('pair').value.trim().toUpperCase();if(!p){$('flow').textContent='Сначала выберите пару';return}let b=$('startBtn');press(b,'⏳ ЗАПУСК...');let r=await fetch('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({capital:+$('capital').value,pairs:[p],allocations:[+$('alloc').value],timeframes:[$('tf').value],fee_pct:.10})});let d=await r.json();if(!r.ok){$('flow').textContent=d.detail||'Ошибка запуска';return}await refresh()}
async function stopBot(){let b=$('stopBtn');press(b,'⏳ ОСТАНОВКА...');let r=await fetch('/api/paper/stop',{method:'POST'});let d=await r.json();if(!r.ok){$('flow').textContent=d.detail||'Ошибка остановки';return}await refresh()}
$('startBtn').onclick=startPaper;$('stopBtn').onclick=stopBot;$('paper').onclick=()=>{$('paper').classList.add('active');$('live').classList.remove('active')};$('live').onclick=()=>alert('LIVE подключается отдельным режимом после настройки API');loadRank();refresh();setInterval(loadRank,5000);setInterval(refresh,1000);timer();
</script></body></html>'''

@app.get('/',response_class=HTMLResponse)
def home():return HTMLResponse(HTML)
