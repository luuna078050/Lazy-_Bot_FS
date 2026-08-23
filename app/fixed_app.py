from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .exchange_gateway import gateway
from .paper_engine import start_paper, stop_paper, emergency_stop_paper, snapshot
from .pump_detector import analyze_3m_ohlcv

app = FastAPI(title='LazyBot FS', version='2.0.0')
LIVE_PROC = None
LIVE_STATE = Path(os.getenv('FAST_SCALPER_LIVE_STATE_FILE', 'fast_scalper_live_state.json'))
LIVE_CONTROL = Path(os.getenv('FAST_SCALPER_CONTROL_FILE', 'fast_scalper_control.json'))
LIVE_LOCK = threading.Lock()


def _clean_pair(value: Any) -> str:
    return str(value or '').strip().upper().replace('-', '/')


def _pairs_alloc(payload: dict[str, Any]):
    capital = float(payload.get('capital', 0))
    pairs = [_clean_pair(x) for x in payload.get('pairs', []) if _clean_pair(x)]
    alloc = [float(x) for x in payload.get('allocations', [])]
    if not 1 <= len(pairs) <= 5:
        raise HTTPException(status_code=400, detail='Можно выбрать от 1 до 5 пар')
    if len(alloc) != len(pairs) or any(x <= 0 for x in alloc) or abs(sum(alloc) - 100) > .01:
        raise HTTPException(status_code=400, detail='Доли выбранных пар должны дать ровно 100%')
    if capital <= 0:
        raise HTTPException(status_code=400, detail='Бюджет должен быть больше 0')
    return capital, pairs, alloc


def _pump_metrics(ex, symbol: str) -> dict[str, Any]:
    try:
        rows = ex.fetch_ohlcv(symbol, timeframe='3m', limit=60)
        pm = analyze_3m_ohlcv(rows)
        last = float(rows[-1][4]) if rows else 0.0
        if last <= 0:
            return pm
        recent9 = pm.get('change_9m_pct', 0.0) / 100
        entry = last if pm.get('signal') == 'PUMP_NOW' else (last * .997 if recent9 <= 0 else last)
        target_pct = min(.012, max(.0035, abs(pm.get('change_3m_pct', 0.0)) / 100 * (1.25 if pm.get('signal') == 'PUMP_NOW' else .8)))
        pm.update({'estimated_entry': entry, 'estimated_exit': entry * (1 + target_pct), 'estimated_stop': entry * (1 - (.006 if pm.get('signal') == 'PUMP_NOW' else .004))})
        return pm
    except Exception:
        return {'pump_events': 0, 'pump_score': 0.0, 'change_3m_pct': 0.0, 'volume_ratio': 1.0, 'signal': 'NO_DATA'}


def _scan_recommendations(limit: int = 20):
    g = gateway('binance'); ex = g.exchange; markets = g.load_markets()
    symbols = [s for s, m in markets.items() if m.get('spot') and m.get('active', True) and m.get('quote') == 'USDT' and '/' in s and m.get('base') not in {'USDT','USDC','FDUSD','USDE','TUSD','DAI','USD1'}]
    tickers = ex.fetch_tickers(symbols)
    base = []
    for s, t in tickers.items():
        p = float(t.get('last') or 0); vol = float(t.get('quoteVolume') or 0); pct = float(t.get('percentage') or 0)
        if p > 0 and vol >= 10000: base.append((s, p, pct, vol))
    base.sort(key=lambda x: x[3], reverse=True)
    rows = []
    for s, p, pct, vol in base[:max(20, limit)]:
        pm = _pump_metrics(ex, s)
        liquidity = min(1.0, math.log10(max(vol, 1)) / 8)
        momentum = min(1.0, max(0.0, pct) / 20)
        score = 100 * (.32 * pm.get('pump_score', 0) + .23 * momentum + .25 * liquidity + .20 * min(1.0, max(0.0, pm.get('change_3m_pct', 0)) / 1.2))
        rows.append({'symbol': s, 'price': p, 'change_24h_pct': pct, 'quote_volume_24h': vol, 'score': round(score, 2), **pm})
    rows.sort(key=lambda x: (x.get('score', 0), x.get('quote_volume_24h', 0)), reverse=True)
    return {'ok': True, 'generated_at': time.time(), 'candidates20': rows[:20], 'top5': rows[:5]}


@app.get('/api/health')
def health(): return {'ok': True, 'project': 'LazyBot FS', 'mode': 'paper/live', 'workspace': 'Fast Scalper'}

@app.get('/api/recommendations')
def recommendations(limit: int = 20):
    try: return _scan_recommendations(max(5, min(limit, 20)))
    except Exception as exc: raise HTTPException(status_code=400, detail=str(exc)[:300])

@app.post('/api/paper/start')
def paper_start(payload: dict[str, Any]): return start_paper(payload, gateway)
@app.post('/api/paper/stop')
def paper_stop(): return stop_paper(gateway)
@app.post('/api/paper/emergency-stop')
def emergency(): return emergency_stop_paper(gateway)
@app.get('/api/paper/status')
def paper_status(): return snapshot()

@app.post('/api/live/start')
def live_start(payload: dict[str, Any]):
    global LIVE_PROC
    capital, pairs, alloc = _pairs_alloc(payload)
    key = str(payload.get('api_key', '')).strip(); secret = str(payload.get('api_secret', '')).strip()
    if not key or not secret: raise HTTPException(status_code=400, detail='Для LIVE нужны Binance API Key и Secret')
    with LIVE_LOCK:
        if LIVE_PROC and LIVE_PROC.poll() is None: raise HTTPException(status_code=409, detail='LIVE уже запущен')
    try:
        g = gateway('binance'); g.exchange.apiKey = key; g.exchange.secret = secret; g.load_markets(); balance = g.exchange.fetch_balance()
        free = float((balance.get('free') or {}).get('USDT') or 0)
        if capital > free + 1e-9: raise HTTPException(status_code=400, detail=f'Бюджет {capital:.4f} USDT превышает свободный USDT-баланс {free:.4f} USDT')
        for p in pairs:
            if p not in g.exchange.markets or not g.exchange.markets[p].get('spot'): raise HTTPException(status_code=400, detail=f'Пара недоступна на Binance Spot: {p}')
    except HTTPException: raise
    except Exception as exc: raise HTTPException(status_code=400, detail=f'Binance preflight не пройден: {str(exc)[:240]}')
    LIVE_CONTROL.write_text(json.dumps({'command':'RUN'}))
    env = os.environ.copy(); env.update({'BINANCE_API_KEY':key,'BINANCE_API_SECRET':secret,'FAST_SCALPER_CAPITAL_USDT':str(capital),'FAST_SCALPER_PAIRS':','.join(pairs),'FAST_SCALPER_ALLOCATIONS':','.join(str(x) for x in alloc),'FAST_SCALPER_LIVE':'true','LIVE_TRADING':'true','LIVE_TRADING_ARMED':'true','TRADING_MODE':'live','FAST_SCALPER_STATE_FILE':str(LIVE_STATE),'FAST_SCALPER_CONTROL_FILE':str(LIVE_CONTROL)})
    try: proc = subprocess.Popen([sys.executable,'-m','scripts.fast_scalper_3m'], cwd=os.getcwd(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, text=True)
    except Exception as exc: raise HTTPException(status_code=500, detail=f'Не удалось запустить LIVE: {exc}')
    with LIVE_LOCK: LIVE_PROC = proc
    return {'ok':True,'running':True,'mode':'LIVE','capital':capital,'pairs':pairs,'allocations':alloc}

@app.post('/api/live/stop')
def live_stop():
    global LIVE_PROC
    with LIVE_LOCK: proc = LIVE_PROC
    if proc and proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=8)
        except subprocess.TimeoutExpired: proc.kill()
    with LIVE_LOCK: LIVE_PROC = None
    return {'ok':True,'running':False,'stop_type':'STOP'}

@app.post('/api/live/emergency-stop')
def live_emergency():
    global LIVE_PROC
    LIVE_CONTROL.write_text(json.dumps({'command':'EMERGENCY_STOP'})); deadline = time.time() + 10
    while time.time() < deadline:
        with LIVE_LOCK: proc = LIVE_PROC
        if not proc or proc.poll() is not None: break
        time.sleep(.25)
    with LIVE_LOCK: proc = LIVE_PROC
    if proc and proc.poll() is None: proc.terminate()
    with LIVE_LOCK: LIVE_PROC = None
    return {'ok':True,'running':False,'stop_type':'EMERGENCY_STOP'}

@app.get('/api/live/status')
def live_status():
    with LIVE_LOCK: proc = LIVE_PROC
    running = bool(proc and proc.poll() is None); state = {}
    try:
        if LIVE_STATE.exists(): state = json.loads(LIVE_STATE.read_text())
    except Exception: state = {}
    state['running'] = running; state['mode'] = 'LIVE'; return state

@app.get('/', response_class=HTMLResponse)
def home(): return _CONTROL_HTML

_CONTROL_HTML = r'''<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>LazyBot FS — Fast Scalper</title><style>body{font-family:system-ui,-apple-system,sans-serif;background:#111827;color:#f5f7fa;max-width:760px;margin:auto;padding:14px}.card{background:#202b3b;border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:1fr 90px;gap:7px}input{box-sizing:border-box;background:#374151;color:#fff;border:1px solid #526174;border-radius:10px;padding:11px;width:100%;margin:4px 0}button{border:0;border-radius:11px;padding:12px;margin:4px 0;font-weight:800;width:100%}.paper{background:#60a5fa}.live{background:#22c55e}.stop{background:#ef4444;color:#fff}.em{background:#991b1b;color:#fff}.ghost{background:#374151;color:#fff}.muted{color:#aeb8c7;font-size:14px}.rec{padding:10px 0;border-bottom:1px solid #394659}.pill{display:inline-block;padding:3px 7px;border-radius:8px;background:#374151;margin:2px;font-size:12px}.price{font-variant-numeric:tabular-nums}.small{font-size:13px}.two{display:grid;grid-template-columns:1fr 1fr;gap:8px}@media(max-width:520px){.two{grid-template-columns:1fr}}</style></head><body><h1>⚡ LazyBot FS</h1><p class="muted">Fast Scalper • Binance Spot • multi-TF + pump hunter</p><div class="card"><h3>Режим</h3><button class="paper" onclick="startPaper()">▶ PAPER — ЗАПУСТИТЬ</button><button class="live" onclick="startLive()">▶ LIVE — РЕАЛЬНЫЕ ДЕНЬГИ</button><div class="two"><button class="stop" onclick="stopAll()">■ STOP</button><button class="em" onclick="emergency()">⛔ EMERGENCY STOP — ЗАКРЫТЬ ВСЁ</button></div><p id="status">⚪ Бот остановлен</p></div><div class="card"><h3>Binance API для LIVE</h3><input id="key" placeholder="API Key" autocomplete="off"><input id="secret" placeholder="Secret Key" type="password" autocomplete="off"><p class="muted">Ключи используются только для текущего LIVE-процесса и не записываются в репозиторий. Withdrawals не используются. Для LIVE — только Spot Trading + IP restriction.</p></div><div class="card"><h3>Бюджет бота</h3><input id="capital" type="number" value="30" min="0.01" step="0.01"><span>USDT</span><p class="muted">Сумма динамическая. LIVE не позволит выставить бюджет выше свободного USDT-баланса Binance.</p></div><div class="card"><h3>5 выбранных пар</h3><p class="muted">Можно выбрать до 5 пар вручную из списка ниже. Примеры DGB/ZRO/TUT больше не зашиты.</p><div id="slots"></div><p class="muted">Доли должны дать 100%.</p></div><div class="card"><h3>20 кандидатов</h3><button class="ghost" onclick="recs()">↻ ОБНОВИТЬ АНАЛИЗ</button><div id="r">Загрузка…</div></div><div class="card"><h3>Топ-5 Fast Scalper</h3><div id="top5">Загрузка…</div></div><div class="card"><h3>Session Result</h3><p>Старт: <b id="ib">0</b> USDT</p><p>Баланс: <b id="bal">0</b> USDT</p><p>NET: <b id="pn">0</b> USDT</p><p>Сделок: <b id="n">0</b></p><h4>Открытые сделки</h4><div id="o">Нет</div><h4>Ордера / fills</h4><div id="ord">Нет</div><h4>Последние сделки</h4><div id="t">Нет</div></div><script>let slots=[{p:'',a:20},{p:'',a:20},{p:'',a:20},{p:'',a:20},{p:'',a:20}];function renderSlots(){document.getElementById('slots').innerHTML=slots.map((x,i)=>'<div class="grid"><input id="p'+i+'" value="'+x.p+'" placeholder="Пара '+(i+1)+'"><input id="a'+i+'" value="'+x.a+'" type="number" min="0.01"></div>').join('')}function getCfg(){let xs=[0,1,2,3,4].map(i=>({p:document.getElementById('p'+i).value.trim().toUpperCase().replace('-', '/'),a:+document.getElementById('a'+i).value})).filter(x=>x.p);return {pairs:xs.map(x=>x.p),allocations:xs.map(x=>x.a),capital:+document.getElementById('capital').value}}function fillPair(s){let i=slots.findIndex(x=>!x.p);if(i<0)i=0;slots[i].p=s;renderSlots()}async function recs(){try{let d=await (await fetch('/api/recommendations?limit=20')).json();if(!d.ok)throw Error(d.detail);document.getElementById('r').innerHTML=d.candidates20.map((x,i)=>'<div class="rec"><b>'+(i+1)+'. '+x.symbol+'</b> <span class="pill">'+x.signal+'</span><br><span class="small price">Цена '+Number(x.price).toPrecision(8)+' • 24ч '+Number(x.change_24h_pct).toFixed(2)+'% • 3m '+Number(x.change_3m_pct||0).toFixed(3)+'% • vol ×'+Number(x.volume_ratio||1).toFixed(2)+' • pumps '+x.pump_events+'</span><br><span class="small">Вход <b>'+fmt(x.estimated_entry)+'</b> → выход <b>'+fmt(x.estimated_exit)+'</b> • SL '+fmt(x.estimated_stop)+' • '+(x.hold_seconds||180)+' сек.</span><button class="ghost" onclick="fillPair(\''+x.symbol+'\')">Выбрать</button></div>').join('');document.getElementById('top5').innerHTML=d.top5.map((x,i)=>'<div class="rec"><b>#'+(i+1)+' '+x.symbol+'</b> — '+x.signal+' — score '+x.score+'<br><span class="small">Вход '+fmt(x.estimated_entry)+' → выход '+fmt(x.estimated_exit)+' • пампы '+x.pump_events+' • удержание '+x.hold_seconds+' сек.</span></div>').join('')}catch(e){document.getElementById('r').textContent='Ошибка анализа: '+e.message}}function fmt(v){return v==null?'—':Number(v).toPrecision(9)}async function startPaper(){let c=getCfg();if(!c.pairs.length||Math.abs(c.allocations.reduce((a,b)=>a+b,0)-100)>.01){alert('Выбери 1–5 пар и распредели 100%');return}let r=await fetch('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...c,target_usdt:.30,min_usdt:.20,sl_pct:.5,max_hold:180,fee_pct:.1})});let d=await r.json();if(!r.ok){alert(d.detail||'Ошибка запуска');return}document.getElementById('status').innerHTML='🟢 PAPER работает';refresh()}async function startLive(){let c=getCfg();if(!c.pairs.length||Math.abs(c.allocations.reduce((a,b)=>a+b,0)-100)>.01){alert('Выбери 1–5 пар и распредели 100%');return}if(!key.value||!secret.value){alert('Для LIVE введи API Key и Secret');return}let r=await fetch('/api/live/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...c,api_key:key.value,api_secret:secret.value})});let d=await r.json();if(!r.ok){alert(d.detail||'Ошибка LIVE');return}document.getElementById('status').innerHTML='🟢 LIVE работает';refresh()}async function stopAll(){await fetch('/api/paper/stop',{method:'POST'});await fetch('/api/live/stop',{method:'POST'});document.getElementById('status').innerHTML='⚪ STOP — бот остановлен';refresh()}async function emergency(){await fetch('/api/paper/emergency-stop',{method:'POST'});await fetch('/api/live/emergency-stop',{method:'POST'});document.getElementById('status').innerHTML='⛔ EMERGENCY STOP — закрытие всего';refresh()}async function refresh(){let p=await (await fetch('/api/paper/status')).json();let l=await (await fetch('/api/live/status')).json();let d=l.running?l:p;document.getElementById('ib').textContent=Number(d.initial_balance||d.capital||0).toFixed(4);document.getElementById('bal').textContent=Number(d.balance||d.free_capital||0).toFixed(4);document.getElementById('pn').textContent=Number(d.pnl||d.realized_pnl||0).toFixed(4);document.getElementById('n').textContent=(d.trades||[]).length;document.getElementById('o').innerHTML=Object.values(d.open_positions||d.positions||{}).map(p=>'<div><b>'+p.symbol+'</b> • вход '+fmt(p.entry_price||p.entry)+' • исполнено '+Number(p.amount||0).toFixed(6)+' • статус '+(p.order_status||'OPEN')+'<br>fills: '+(p.fills||[]).map(f=>Number(f.amount||0).toFixed(6)+' @ '+fmt(f.price)).join(' | ')+'</div>').join('<hr>')||'Нет';document.getElementById('ord').innerHTML=Object.values(d.orders||{}).map(q=>'<div><b>'+q.symbol+'</b> • запрос '+Number(q.requested_amount||0).toFixed(6)+' • исполнено '+Number(q.filled_amount||0).toFixed(6)+' • остаток '+Number(q.remaining_amount||0).toFixed(6)+' • '+q.status+'</div>').join('<hr>')||'Нет';document.getElementById('t').innerHTML=(d.trades||[]).slice().reverse().map(q=>'<div>'+q.symbol+': '+fmt(q.entry_price||q.entry)+' → '+fmt(q.exit_price||q.exit)+' • NET '+Number(q.net_pnl||q.pnl||0).toFixed(4)+' USDT • '+q.reason+'</div>').join('<hr>')||'Нет'}renderSlots();recs();setInterval(refresh,3000);refresh();</script></body></html>'''
