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

HTML=r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper</title><style>
:root{--bg:#07090b;--panel:#0d1115;--line:#293038;--green:#20e875;--red:#ff3040;--gold:#ffc02e;--muted:#8d969f}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f3f5f7;font:14px/1.35 system-ui,-apple-system,Roboto,sans-serif}.app{max-width:760px;margin:auto;padding:10px 12px 30px}.bar{position:sticky;top:0;z-index:5;background:rgba(7,9,11,.97);display:flex;justify-content:space-between;align-items:center;padding:8px 0}.brand{font-size:19px;font-weight:950}.brand b{color:var(--red)}button,input,select{font:inherit}.mode{display:flex;gap:5px}.mode button,.action{border:1px solid #394149;background:#171c21;color:#fff;border-radius:10px;padding:9px 12px;font-weight:900}.mode .active{border-color:var(--green);background:#087d3d}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:12px;margin:8px 0}.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:9px}.head h3{font-size:15px;margin:0}.muted{color:var(--muted);font-size:11px}.slots{display:grid;grid-template-columns:1fr 1fr;gap:8px}.slot{border:1px solid #2a3137;border-radius:12px;padding:9px;background:#090d10}.slot.selected{border-color:var(--green);box-shadow:0 0 0 1px rgba(32,232,117,.2)}.slotrow{display:grid;grid-template-columns:28px 1fr 92px;gap:7px;align-items:center}.num{color:var(--muted);font-weight:900}.slot input{width:100%;background:#11161a;color:#fff;border:1px solid #30373e;border-radius:8px;padding:8px}.pairbtn{width:100%;text-align:left;background:#12181c;border:1px solid #343c43;color:#fff;border-radius:8px;padding:8px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pairbtn.on{border-color:var(--green);color:var(--green)}.radar{display:grid;grid-template-columns:1fr 1fr;gap:7px}.candidate{border:1px solid #252d33;border-radius:11px;padding:9px;background:#090d10;cursor:pointer}.candidate:hover,.candidate.on{border-color:var(--green)}.top{display:flex;justify-content:space-between;font-weight:900}.score{color:var(--green)}.sub{color:#929ba4;font-size:11px;margin-top:4px}.controls{display:grid;grid-template-columns:1fr 1fr;gap:7px}.go{background:#087d3d!important;border-color:var(--green)!important}.stop{background:#351117!important;border-color:var(--red)!important}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.metric{border-top:1px solid #252c32;padding-top:7px}.metric small{color:var(--muted);display:block}.metric b{font-size:15px}.pnl{font-size:27px;font-weight:950;color:var(--gold);margin-bottom:5px}.state{font-weight:950}.green{color:var(--green)}.red{color:#ff6974}.settings{display:grid;grid-template-columns:1fr 1fr;gap:7px}.settings input,.settings select{width:100%;background:#11161a;color:#fff;border:1px solid #30373e;border-radius:8px;padding:9px}.hint{margin-top:8px;color:var(--muted);font-size:11px}@media(max-width:540px){.metrics{grid-template-columns:1fr 1fr}.slotrow{grid-template-columns:24px 1fr 80px}}
</style></head><body><main class="app"><div class="bar"><div class="brand">⚡ <b>FAST SCALPER</b></div><div class="mode"><button id="paper" class="active">PAPER</button><button id="live">LIVE</button></div></div>
<div class="card"><div class="head"><h3>🎯 ВЫБОР ТОРГОВЫХ ПОЗИЦИЙ</h3><span class="muted" id="selectedCount">0 / 10</span></div><div class="slots" id="slots"></div><div class="hint">Вы выбираете только пары и сумму. После запуска бот сам выбирает момент входа и выхода. Пустые слоты не торгуются.</div></div>
<div class="card"><div class="head"><h3>🚀 АНАЛИТИКА — КАНДИДАТЫ</h3><span class="muted" id="radarStatus">загрузка</span></div><div id="radar" class="radar">Загрузка аналитики...</div></div>
<div class="card"><div class="head"><h3>💰 СОСТОЯНИЕ</h3><span id="runState" class="state">Остановлен</span></div><div id="pnl" class="pnl">0.0000 USDT</div><div class="metrics"><div class="metric"><small>Баланс</small><b id="bal">0.0000</b></div><div class="metric"><small>Свободно</small><b id="free">0.0000</b></div><div class="metric"><small>Инвестировано</small><b id="invested">0.0000</b></div><div class="metric"><small>Сделок</small><b id="trades">0</b></div></div></div>
<div class="card"><div class="head"><h3>⚡ УПРАВЛЕНИЕ</h3><span class="muted">без лишнего таймера</span></div><div class="controls"><button id="start" class="action go">▶ ЗАПУСТИТЬ PAPER</button><button id="stop" class="action stop">■ STOP</button></div></div>
<div class="card"><div class="head"><h3>📌 ОТКРЫТЫЕ ПОЗИЦИИ</h3><span class="muted" id="posCount">0</span></div><div id="positions">Нет открытых позиций</div></div>
<div class="card"><div class="head"><h3>⚙ ПАРАМЕТРЫ</h3></div><div class="settings"><div><div class="muted">Общий капитал USDT</div><input id="capital" type="number" value="50" min="1" step="1"></div><div><div class="muted">Таймфрейм анализа</div><select id="tf"><option>3m</option><option>1m</option><option>5m</option></select></div></div><div class="hint">Ориентир: $0.15–$0.30 в минуту на $25 задействованного капитала. Это ориентир производительности, а не гарантированная прибыль.</div></div></main><script>
const $=id=>document.getElementById(id);let slots=Array.from({length:10},()=>({pair:'',amount:5}));let running=false;
function esc(x){return String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}
function renderSlots(){let active=slots.filter(x=>x.pair).length;$('selectedCount').textContent=active+' / 10';$('slots').innerHTML=slots.map((s,i)=>`<div class="slot ${s.pair?'selected':''}"><div class="slotrow"><div class="num">${i+1}</div><button class="pairbtn ${s.pair?'on':''}" onclick="clearSlot(${i})">${s.pair?'✓ '+esc(s.pair):'Пусто — выберите'}</button><input type="number" min="1" step="0.5" value="${s.amount}" onchange="slots[${i}].amount=Number(this.value)||1"></div></div>`).join('')}
function clearSlot(i){if(slots[i].pair){slots[i].pair='';renderSlots()}}
function choosePair(p){let idx=slots.findIndex(x=>x.pair===p);if(idx<0)idx=slots.findIndex(x=>!x.pair);if(idx<0){$('radarStatus').textContent='10 слотов заполнены';return}slots[idx].pair=p;renderSlots();$('radarStatus').textContent=p+' добавлена'}
function renderRadar(rows){$('radar').innerHTML=(rows||[]).slice(0,20).map(r=>{let p=esc(r.symbol||r.pair||'');let sc=Number(r.score||r.quality||0);let price=Number(r.price||0);let ch=Number(r.change_pct||r.change||0);return `<div class="candidate" onclick="choosePair('${p}')"><div class="top"><span>${p}</span><span class="score">${sc.toFixed(1)}</span></div><div class="sub">Цена ${price?price.toPrecision(8):'—'} · Δ ${ch.toFixed(3)}% · нажмите, чтобы добавить</div></div>`}).join('')||'Нет данных'}
async function refreshRadar(){try{let r=await fetch('/api/recommendations?limit=20');let j=await r.json();renderRadar(j.candidates20||[]);$('radarStatus').textContent=j.ok?'WebSocket · обновление 5с':'ошибка аналитики'}catch(e){$('radar').textContent='Аналитика недоступна: '+e.message}}
async function status(){try{let j=await fetch('/api/paper/status').then(r=>r.json());let eq=Number(j.equity??j.balance??0),pnl=Number(j.realized_pnl??j.pnl??0);$('bal').textContent=eq.toFixed(4);$('free').textContent=Number(j.free_usdt??0).toFixed(4);$('invested').textContent=Number(j.invested_usdt??0).toFixed(4);$('trades').textContent=(j.trades||[]).length;$('pnl').textContent=pnl.toFixed(4)+' USDT';let pos=j.open_positions||j.positions||[];$('posCount').textContent=pos.length;$('positions').innerHTML=pos.length?pos.map(x=>`<div style="padding:8px 0;border-bottom:1px solid #20262b"><b>${esc(x.symbol)}</b> · вход ${Number(x.entry_price||0).toPrecision(8)} · цель ${Number(x.target_price||0).toPrecision(8)} · ${Number(x.allocated_usdt||0).toFixed(2)} USDT</div>`).join(''):'Нет открытых позиций';running=!!j.running;$('runState').textContent=running?'🟢 Работает':'Остановлен';$('runState').className='state '+(running?'green':'');}catch(e){}}
$('start').onclick=async()=>{let selected=slots.filter(x=>x.pair);if(!selected.length){alert('Выберите хотя бы одну пару');return}let capital=Number($('capital').value)||50;let total=selected.reduce((a,x)=>a+x.amount,0);if(total>capital+1e-9){alert('Сумма слотов больше общего капитала');return}let allocations=selected.map(x=>x.amount/capital*100);let payload={capital,pairs:selected.map(x=>x.pair),allocations,timeframes:selected.map(()=>$('tf').value)};let r=await fetch('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});let j=await r.json();if(!r.ok||j.ok===false)alert(j.detail||j.error||'Не удалось запустить PAPER');await status()};
$('stop').onclick=async()=>{await fetch('/api/paper/stop',{method:'POST'});await status()};$('paper').onclick=()=>{$('paper').classList.add('active');$('live').classList.remove('active')};$('live').onclick=()=>{$('live').classList.add('active');$('paper').classList.remove('active');alert('LIVE оставлен отдельным режимом. Сначала проверяем PAPER.')};
renderSlots();refreshRadar();status();setInterval(refreshRadar,5000);setInterval(status,1000);
</script></body></html>'''

@app.get('/',response_class=HTMLResponse)
def home():return HTML
