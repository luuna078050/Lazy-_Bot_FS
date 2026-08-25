from __future__ import annotations

import json, os, subprocess, sys, threading, time
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from .exchange_gateway import gateway
from .market_radar import RADAR
from .profit_first_engine_v4 import start_paper, stop_paper, emergency_stop_paper, snapshot as paper_snapshot

app=FastAPI(title='Fast Scalper',version='canonical-test-1')
LIVE_PROC=None; LIVE_LOCK=threading.Lock(); LIVE_STATE=Path(os.getenv('FAST_SCALPER_LIVE_STATE_FILE','fast_scalper_live_state.json')); LIVE_CONTROL=Path(os.getenv('FAST_SCALPER_CONTROL_FILE','fast_scalper_control.json'))

def pair(v:Any)->str:return str(v or '').strip().upper().replace('-','/')
def validate(p):
    capital=float(p.get('capital',0) or 0); pairs=[pair(x) for x in p.get('pairs',[]) if pair(x)]; amounts=[float(x) for x in p.get('amounts',[])]; tfs=[str(x).lower() for x in p.get('timeframes',[])]
    if not 1<=len(pairs)<=10:raise HTTPException(400,'Выберите от 1 до 10 пар')
    if len(amounts)!=len(pairs) or any(x<=0 for x in amounts):raise HTTPException(400,'Сумма каждой позиции должна быть больше 0 USDT')
    if capital<=0:raise HTTPException(400,'Капитал должен быть больше 0 USDT')
    if sum(amounts)>capital+1e-9:raise HTTPException(400,f'Сумма позиций {sum(amounts):.2f} USDT превышает капитал {capital:.2f} USDT')
    if not tfs:tfs=['3m']*len(pairs)
    if len(tfs)!=len(pairs) or any(x not in {'1m','3m','5m'} for x in tfs):raise HTTPException(400,'Таймфрейм: 1m / 3m / 5m')
    return capital,pairs,amounts,[x/capital*100 for x in amounts],tfs

def report():
    s=paper_snapshot(); bal=float(s.get('account_balance_usdt',s.get('initial_balance',0)) or 0); free=float(s.get('free_usdt',0) or 0); pos=list((s.get('open_positions') or {}).values())
    return {**s,'running':bool(s.get('running')),'positions':pos,'open_positions':pos,'orders':list((s.get('orders') or {}).values()),'trades':list(s.get('trades') or [])[-50:],'order_history':list(s.get('order_history') or [])[-50:],'account_balance_usdt':bal,'free_usdt':free,'invested_usdt':max(0,bal-free)}

@app.get('/api/health')
def health():return {'ok':True,'project':'Fast Scalper','runtime':'canonical','analytics':'unchanged','engine':'profit_first_v4'}
@app.get('/api/recommendations')
def recommendations(limit:int=20):
    try:
        RADAR.start(); rows=RADAR.snapshot(max(10,min(limit,20))); return {'ok':True,'generated_at':time.time(),'data_source':'Binance WebSocket','radar_status':RADAR.status(),'candidates20':rows[:20],'top5':rows[:5]}
    except Exception as e:return {'ok':False,'error':str(e)[:300],'candidates20':[],'top5':[]}
@app.get('/api/paper/status')
def paper_status():return report()
@app.get('/api/session/report/{mode}')
def session_report(mode:str):return report() if mode.upper()=='PAPER' else live_status()
@app.post('/api/paper/start')
def paper_start(p:dict[str,Any]):
    capital,pairs,amounts,alloc,tfs=validate(p); cfg=dict(p); cfg.update({'capital':capital,'pairs':pairs,'allocations':alloc,'timeframes':tfs,'fee_pct':float(p.get('fee_pct',.10))}); start_paper(cfg,gateway); return {'ok':True,**report()}
@app.post('/api/paper/stop')
def paper_stop():return {'ok':True,**stop_paper(gateway)}
@app.post('/api/paper/emergency-stop')
def paper_emergency():return {'ok':True,**emergency_stop_paper(gateway)}
@app.post('/api/live/start')
def live_start(p:dict[str,Any]):
    global LIVE_PROC
    capital,pairs,amounts,alloc,tfs=validate(p); key=str(p.get('api_key','')).strip(); secret=str(p.get('api_secret','')).strip()
    if not key or not secret:raise HTTPException(400,'Для LIVE нужны API Key и Secret')
    with LIVE_LOCK:
        if LIVE_PROC and LIVE_PROC.poll() is None:raise HTTPException(409,'LIVE уже запущен')
    try:
        g=gateway('binance'); g.exchange.apiKey=key; g.exchange.secret=secret; g.load_markets(); b=g.exchange.fetch_balance(); free=float((b.get('free') or {}).get('USDT') or 0)
        if capital>free+1e-9:raise HTTPException(400,f'Недостаточно свободного USDT: {free:.4f}')
        for x in pairs:
            if x not in g.exchange.markets or not g.exchange.markets[x].get('spot'):raise HTTPException(400,f'Пара недоступна на Binance Spot: {x}')
    except HTTPException:raise
    except Exception as e:raise HTTPException(400,f'Binance preflight: {str(e)[:240]}')
    LIVE_CONTROL.write_text(json.dumps({'command':'RUN'})); env=os.environ.copy(); env.update({'BINANCE_API_KEY':key,'BINANCE_API_SECRET':secret,'FAST_SCALPER_CAPITAL_USDT':str(capital),'FAST_SCALPER_PAIRS':','.join(pairs),'FAST_SCALPER_ALLOCATIONS':','.join(map(str,alloc)),'FAST_SCALPER_TIMEFRAMES':','.join(tfs),'FAST_SCALPER_LIVE':'true','LIVE_TRADING':'true','LIVE_TRADING_ARMED':'true','TRADING_MODE':'live','FAST_SCALPER_STATE_FILE':str(LIVE_STATE),'FAST_SCALPER_CONTROL_FILE':str(LIVE_CONTROL)})
    try:proc=subprocess.Popen([sys.executable,'-m','scripts.fast_scalper_3m'],cwd=os.getcwd(),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,text=True)
    except Exception as e:raise HTTPException(500,f'Не удалось запустить LIVE: {e}')
    with LIVE_LOCK:LIVE_PROC=proc
    return {'ok':True,'running':True,'mode':'LIVE','capital':capital,'pairs':pairs,'amounts':amounts}
@app.post('/api/live/stop')
def live_stop():
    global LIVE_PROC
    with LIVE_LOCK:p=LIVE_PROC
    if p and p.poll() is None:p.terminate()
    with LIVE_LOCK:LIVE_PROC=None
    return {'ok':True,'running':False,'stop_type':'STOP'}
@app.post('/api/live/emergency-stop')
def live_emergency():
    global LIVE_PROC
    LIVE_CONTROL.write_text(json.dumps({'command':'EMERGENCY_STOP'})); deadline=time.time()+10
    while time.time()<deadline:
        with LIVE_LOCK:p=LIVE_PROC
        if not p or p.poll() is not None:break
        time.sleep(.2)
    with LIVE_LOCK:p=LIVE_PROC
    if p and p.poll() is None:p.terminate()
    with LIVE_LOCK:LIVE_PROC=None
    return {'ok':True,'running':False,'stop_type':'EMERGENCY_STOP'}
@app.get('/api/live/status')
def live_status():
    with LIVE_LOCK:p=LIVE_PROC
    state={}
    try:
        if LIVE_STATE.exists():state=json.loads(LIVE_STATE.read_text())
    except Exception:state={}
    state['running']=bool(p and p.poll() is None); state['mode']='LIVE'; return state

HTML=r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Cache-Control" content="no-store"><title>Fast Scalper</title><style>:root{--bg:#07090b;--panel:#0d1115;--line:#293038;--g:#20e875;--r:#ff3040;--m:#8d969f;--y:#ffc02e}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f3f5f7;font:14px system-ui,-apple-system,Roboto,sans-serif}.app{max-width:760px;margin:auto;padding:10px 12px 30px}.bar{position:sticky;top:0;z-index:5;background:#07090bf7;display:flex;justify-content:space-between;align-items:center;padding:8px 0}.brand{font-size:19px;font-weight:950;color:var(--r)}button,input,select{font:inherit}.mode{display:flex;gap:5px}.mode button,.action{border:1px solid #394149;background:#171c21;color:#fff;border-radius:10px;padding:9px 12px;font-weight:900}.mode .active{border-color:var(--g);background:#087d3d}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:12px;margin:8px 0}.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:9px}.head h3{font-size:15px;margin:0}.muted{color:var(--m);font-size:11px}.slots{display:grid;grid-template-columns:1fr 1fr;gap:8px}.slot{border:1px solid #2a3137;border-radius:12px;padding:9px;background:#090d10}.slot.on{border-color:var(--g);box-shadow:0 0 0 1px #20e87533}.slotrow{display:grid;grid-template-columns:24px 1fr 78px;gap:7px;align-items:center}.num{color:var(--m);font-weight:900}.slot button{width:100%;text-align:left;background:#12181c;border:1px solid #343c43;color:#fff;border-radius:8px;padding:8px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.slot button.sel{border-color:var(--g);color:var(--g)}input,select{width:100%;background:#11161a;color:#fff;border:1px solid #30373e;border-radius:8px;padding:9px}.radar{display:grid;grid-template-columns:1fr 1fr;gap:7px}.cand{border:1px solid #252d33;border-radius:11px;padding:9px;background:#090d10;cursor:pointer}.top{display:flex;justify-content:space-between;font-weight:900}.score{color:var(--g)}.sub{color:#929ba4;font-size:11px;margin-top:4px}.controls{display:grid;grid-template-columns:1fr 1fr;gap:7px}.go{background:#087d3d!important;border-color:var(--g)!important}.stop{background:#351117!important;border-color:var(--r)!important}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.metric{border-top:1px solid #252c32;padding-top:7px}.metric small{color:var(--m);display:block}.metric b{font-size:15px}.pnl{font-size:27px;font-weight:950;color:var(--y);margin-bottom:5px}.green{color:var(--g);font-weight:900}.timer{font-variant-numeric:tabular-nums;font-size:20px;font-weight:950}.line{padding:8px 0;border-bottom:1px solid #20262b}.hint{margin-top:8px;color:var(--m);font-size:11px}@media(max-width:540px){.metrics{grid-template-columns:1fr 1fr}.slotrow{grid-template-columns:22px 1fr 70px}}</style></head><body><main class="app"><div class="bar"><div class="brand">⚡ FAST SCALPER</div><div class="mode"><button id="pm" class="active">PAPER</button><button id="lm">LIVE</button></div></div><div class="card"><div class="head"><h3>🎯 ТОРГОВЫЕ ПОЗИЦИИ</h3><span class="muted" id="cnt">0 / 10</span></div><div id="slots" class="slots"></div><div class="hint">Выбираешь только пары и сумму. Бот сам выбирает момент входа и выхода. Пустые слоты не торгуются.</div></div><div class="card"><div class="head"><h3>🚀 АНАЛИТИКА — КАНДИДАТЫ</h3><span class="muted" id="rs">WebSocket</span></div><div id="radar" class="radar">Загрузка...</div></div><div class="card"><div class="head"><h3>💰 СОСТОЯНИЕ</h3><span id="state">Остановлен</span></div><div id="timer" class="timer">00:00:00</div><div id="pnl" class="pnl">0.0000 USDT</div><div class="metrics"><div class="metric"><small>Баланс</small><b id="bal">0.0000</b></div><div class="metric"><small>Свободно</small><b id="free">0.0000</b></div><div class="metric"><small>Инвестировано</small><b id="inv">0.0000</b></div><div class="metric"><small>Сделок</small><b id="tr">0</b></div></div></div><div class="card"><div class="head"><h3>⚡ УПРАВЛЕНИЕ</h3><span class="muted">PAPER</span></div><div class="controls"><button id="start" class="action go">▶ ЗАПУСТИТЬ PAPER</button><button id="stop" class="action stop">■ STOP</button></div></div><div class="card"><div class="head"><h3>📌 ОТКРЫТЫЕ ПОЗИЦИИ</h3><span class="muted" id="pc">0</span></div><div id="pos">Нет открытых позиций</div></div><div class="card"><div class="head"><h3>📋 ОРДЕРА</h3></div><div id="ord">Нет активных ордеров</div></div><div class="card"><div class="head"><h3>⚙ ПАРАМЕТРЫ</h3></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:7px"><div><div class="muted">Общий капитал USDT</div><input id="capital" type="number" value="50" min="1" step="1"></div><div><div class="muted">Таймфрейм</div><select id="tf"><option>3m</option><option>1m</option><option>5m</option></select></div></div><div class="hint">Ориентир: $0.15–$0.30 в минуту на $25. Это ориентир, не гарантия. Вход всегда ниже целевой цены выхода.</div></div><script>const $=x=>document.getElementById(x),S=Array.from({length:10},()=>({pair:'',amount:5}));let ti=null;function esc(x){return String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}function slots(){let n=S.filter(x=>x.pair).length;$('cnt').textContent=n+' / 10';$('slots').innerHTML=S.map((s,i)=>`<div class="slot ${s.pair?'on':''}"><div class="slotrow"><span class="num">${i+1}</span><button class="${s.pair?'sel':''}" onclick="clr(${i})">${s.pair?'✓ '+esc(s.pair):'Выбрать пару'}</button><input type="number" min="1" step="0.5" value="${s.amount}" onchange="S[${i}].amount=Number(this.value)||1"></div></div>`).join('')}function clr(i){S[i].pair='';slots()}function pick(p){let i=S.findIndex(x=>x.pair===p);if(i<0)i=S.findIndex(x=>!x.pair);if(i<0){$('rs').textContent='10 слотов заполнены';return}S[i].pair=p;slots()}function radar(rows){$('radar').innerHTML=(rows||[]).slice(0,20).map(r=>{let p=r.symbol||'',e=Number(r.estimated_entry||r.price||0),x=Number(r.estimated_exit||0);if(x<=e)x=e*1.0008;return `<div class="cand" onclick="pick('${esc(p)}')"><div class="top"><b>${esc(p)}</b><span class="score">${Number(r.score||0).toFixed(1)}</span></div><div class="sub">Цена ${Number(r.price||0).toPrecision(9)} · 3m ${Number(r.change_3m_pct||0).toFixed(3)}%<br>Вход ${e.toPrecision(9)} → выход ${x.toPrecision(9)}<br>Нажмите, чтобы добавить</div></div>`}).join('')||'Нет данных'}async function rr(){try{let j=await fetch('/api/recommendations?limit=20',{cache:'no-store'}).then(r=>r.json());radar(j.candidates20||[]);$('rs').textContent=j.ok?'WebSocket · 5с':'ошибка'}catch(e){$('radar').textContent='Ошибка: '+e.message}}function cfg(){let a=S.filter(x=>x.pair);return{capital:Number($('capital').value)||50,pairs:a.map(x=>x.pair),amounts:a.map(x=>x.amount),timeframes:a.map(()=> $('tf').value)}}function timer(ts){clearInterval(ti);if(!ts){$('timer').textContent='00:00:00';return}let f=()=>{let n=Math.max(0,Math.floor((Date.now()-ts)/1000)),h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;$('timer').textContent=[h,m,s].map(x=>String(x).padStart(2,'0')).join(':')};f();ti=setInterval(f,1000)}async function stat(){try{let j=await fetch('/api/paper/status',{cache:'no-store'}).then(r=>r.json());let on=!!j.running;$('state').textContent=on?'🟢 Работает':'Остановлен';$('state').className=on?'green':'';timer(j.started_at?new Date(j.started_at).getTime():null);$('bal').textContent=Number(j.account_balance_usdt??j.initial_balance??0).toFixed(4);$('free').textContent=Number(j.free_usdt??0).toFixed(4);$('inv').textContent=Number(j.invested_usdt??0).toFixed(4);$('pnl').textContent=Number(j.realized_pnl??0).toFixed(4)+' USDT';$('tr').textContent=(j.trades||[]).length;let p=j.positions||[];$('pc').textContent=p.length;$('pos').innerHTML=p.length?p.map(x=>{let e=Number(x.entry_price||0),t=Number(x.target_price||0);if(t<=e)t=e*1.0008;return `<div class="line"><b>${esc(x.symbol)}</b> · вход ${e.toPrecision(9)} · цель ${t.toPrecision(9)} · ${Number(x.allocated_usdt||0).toFixed(2)} USDT</div>`}).join(''):'Нет открытых позиций';let o=j.orders||[];$('ord').innerHTML=o.length?o.map(x=>`<div class="line"><b>${esc(x.symbol)}</b> · LIMIT ${Number(x.price||0).toPrecision(9)} · ${Number(x.requested_usdt||0).toFixed(2)} USDT · ${esc(x.status)}</div>`).join(''):'Нет активных ордеров'}catch(e){$('state').textContent='Ошибка состояния'}}$('start').onclick=async()=>{let c=cfg();if(!c.pairs.length)return alert('Выберите хотя бы одну пару');let sum=c.amounts.reduce((a,b)=>a+b,0);if(sum>c.capital)return alert('Сумма позиций больше капитала');let r=await fetch('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c)}),j=await r.json();if(!r.ok||j.ok===false)return alert(j.detail||j.error||'Ошибка запуска');stat()};$('stop').onclick=async()=>{await fetch('/api/paper/stop',{method:'POST'});stat()};$('lm').onclick=()=>alert('LIVE пока не включаем. Сначала тестируем PAPER.');slots();rr();stat();setInterval(rr,5000);setInterval(stat,1000)</script></main></body></html>'''

@app.get('/',response_class=HTMLResponse)
def home():return HTMLResponse(HTML,headers={'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0','Pragma':'no-cache','Expires':'0'})
