from __future__ import annotations

import json, os, subprocess, sys, time, threading
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from .fixed_app import app as app

# Replace only the old root UI. All existing API routes remain intact.
for _route in list(app.router.routes):
    if getattr(_route, 'path', None) == '/' and getattr(_route, 'methods', None) and 'GET' in _route.methods:
        app.router.routes.remove(_route)

MIXED_PROC = None
MIXED_STATE = Path(os.getenv('FAST_SCALPER_MIXED_STATE_FILE', 'fast_scalper_mixed_state.json'))
MIXED_CONTROL = Path(os.getenv('FAST_SCALPER_MIXED_CONTROL_FILE', 'fast_scalper_mixed_control.json'))
MIXED_LOCK = threading.Lock()


def _clean_pair(v):
    return str(v or '').strip().upper().replace('-', '/')


def _mixed_payload(payload):
    capital = float(payload.get('capital', 0))
    slots = payload.get('slots') or []
    clean = []
    for x in slots:
        p = _clean_pair(x.get('pair'))
        if not p:
            continue
        a = float(x.get('allocation', 0) or 0)
        mode = str(x.get('mode', 'PAPER')).upper()
        if mode not in ('PAPER', 'LIVE'):
            mode = 'PAPER'
        clean.append({'pair': p, 'allocation': a, 'mode': mode,
                      'use_amount': bool(x.get('use_amount', True)),
                      'order_amount': float(x.get('order_amount', 0) or 0)})
    if not 1 <= len(clean) <= 5:
        raise HTTPException(400, 'Выберите от 1 до 5 пар')
    if any(x['allocation'] < 0 or x['allocation'] > 100 for x in clean):
        raise HTTPException(400, 'Доля каждой пары: 0–100%')
    total = sum(x['allocation'] for x in clean)
    if abs(total - 100) > .01:
        raise HTTPException(400, 'Доли выбранных пар должны дать ровно 100%')
    if capital <= 0:
        raise HTTPException(400, 'Бюджет должен быть больше 0')
    return capital, clean


@app.post('/api/mixed/start')
def mixed_start(payload: dict):
    global MIXED_PROC
    capital, slots = _mixed_payload(payload)
    live_slots = [x for x in slots if x['mode'] == 'LIVE']
    key = str(payload.get('api_key', '')).strip(); secret = str(payload.get('api_secret', '')).strip()
    if live_slots and (not key or not secret):
        raise HTTPException(400, 'Для LIVE-позиций нужны Binance API Key и Secret')
    with MIXED_LOCK:
        if MIXED_PROC and MIXED_PROC.poll() is None:
            raise HTTPException(409, 'Смешанная сессия уже запущена')
    if live_slots:
        try:
            from .exchange_gateway import gateway
            g = gateway('binance'); g.exchange.apiKey = key; g.exchange.secret = secret; g.load_markets()
            bal = g.exchange.fetch_balance(); free = float((bal.get('free') or {}).get('USDT') or 0)
            live_cap = capital * sum(x['allocation'] for x in live_slots) / 100
            if live_cap > free + 1e-9:
                raise HTTPException(400, f'LIVE-бюджет {live_cap:.4f} USDT выше свободного USDT-баланса {free:.4f} USDT')
            for x in live_slots:
                if x['pair'] not in g.exchange.markets or not g.exchange.markets[x['pair']].get('spot'):
                    raise HTTPException(400, f'Пара недоступна на Binance Spot: {x["pair"]}')
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, f'Binance preflight не пройден: {str(exc)[:240]}')
    MIXED_CONTROL.write_text(json.dumps({'command':'RUN'}))
    env = os.environ.copy()
    env.update({
        'FAST_SCALPER_CAPITAL_USDT': str(capital),
        'FAST_SCALPER_PAIRS': ','.join(x['pair'] for x in slots),
        'FAST_SCALPER_ALLOCATIONS': ','.join(str(x['allocation']) for x in slots),
        'FAST_SCALPER_LIVE_PAIRS': ','.join(x['pair'] for x in live_slots),
        'FAST_SCALPER_PAPER_PAIRS': ','.join(x['pair'] for x in slots if x['mode'] == 'PAPER'),
        'FAST_SCALPER_ORDER_AMOUNTS': ','.join(str(x['order_amount']) for x in slots),
        'FAST_SCALPER_USE_ORDER_AMOUNTS': ','.join('true' if x['use_amount'] else 'false' for x in slots),
        'FAST_SCALPER_LIVE': 'true' if live_slots else 'false',
        'LIVE_TRADING': 'true' if live_slots else 'false',
        'LIVE_TRADING_ARMED': 'true' if live_slots else 'false',
        'TRADING_MODE': 'mixed' if live_slots and len(live_slots) < len(slots) else ('live' if live_slots else 'paper'),
        'BINANCE_API_KEY': key, 'BINANCE_API_SECRET': secret,
        'FAST_SCALPER_STATE_FILE': str(MIXED_STATE),
        'FAST_SCALPER_CONTROL_FILE': str(MIXED_CONTROL),
    })
    try:
        proc = subprocess.Popen([sys.executable, '-m', 'scripts.fast_scalper_3m'], cwd=os.getcwd(), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, text=True)
    except Exception as exc:
        raise HTTPException(500, f'Не удалось запустить сессию: {exc}')
    with MIXED_LOCK: MIXED_PROC = proc
    return {'ok': True, 'running': True, 'mode': 'MIXED', 'capital': capital, 'slots': slots}


@app.post('/api/mixed/stop')
def mixed_stop():
    global MIXED_PROC
    MIXED_CONTROL.write_text(json.dumps({'command':'STOP'}))
    with MIXED_LOCK: proc = MIXED_PROC
    if proc and proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=8)
        except subprocess.TimeoutExpired: proc.kill()
    with MIXED_LOCK: MIXED_PROC = None
    return {'ok': True, 'running': False, 'stop_type': 'STOP'}


@app.post('/api/mixed/emergency-stop')
def mixed_emergency():
    global MIXED_PROC
    MIXED_CONTROL.write_text(json.dumps({'command':'EMERGENCY_STOP'}))
    deadline = time.time() + 10
    while time.time() < deadline:
        with MIXED_LOCK: proc = MIXED_PROC
        if not proc or proc.poll() is not None: break
        time.sleep(.25)
    with MIXED_LOCK: proc = MIXED_PROC
    if proc and proc.poll() is None: proc.terminate()
    with MIXED_LOCK: MIXED_PROC = None
    return {'ok': True, 'running': False, 'stop_type': 'EMERGENCY_STOP'}


@app.get('/api/mixed/status')
def mixed_status():
    with MIXED_LOCK: proc = MIXED_PROC
    running = bool(proc and proc.poll() is None)
    state = {}
    try:
        if MIXED_STATE.exists(): state = json.loads(MIXED_STATE.read_text())
    except Exception: pass
    state['running'] = running
    return state


HTML = r'''<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>LazyBot FS — Fast Scalper</title>
<style>
:root{--bg:#101827;--card:#202b3b;--field:#3a4658;--line:#526174;--text:#f5f7fa;--muted:#aeb8c7;--ok:#22c55e;--blue:#60a5fa;--red:#ef4444;--darkred:#991b1b;--gold:#f5c542}*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);max-width:800px;margin:auto;padding:12px}.card{background:var(--card);border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:40px 1fr 90px;gap:7px;align-items:center}.grid input{min-width:0}input,select{background:var(--field);color:#fff;border:1px solid var(--line);border-radius:11px;padding:12px;width:100%;margin:4px 0;font-size:16px}button{border:0;border-radius:11px;padding:12px;margin:4px 0;font-weight:800;width:100%;cursor:pointer;transition:.12s transform,.12s filter,.12s box-shadow}.click:active,button:active{transform:scale(.97);filter:brightness(1.12)}.selected{box-shadow:0 0 0 3px var(--gold) inset,0 0 10px #f5c54255}.clear{background:#475569;color:#fff;font-size:12px}.paper{background:var(--blue)}.live{background:var(--ok)}.stop{background:var(--red);color:#fff}.em{background:var(--darkred);color:#fff}.ghost{background:#374151;color:#fff}.mode{font-size:12px;padding:8px;margin:2px 0}.mode.paperMode{background:#2563eb}.mode.liveMode{background:#16a34a}.muted{color:var(--muted);font-size:14px}.rec{padding:11px 0;border-bottom:1px solid #394659}.pill{display:inline-block;padding:3px 7px;border-radius:8px;background:#374151;margin:2px;font-size:12px}.price{font-variant-numeric:tabular-nums}.small{font-size:13px}.two{display:grid;grid-template-columns:1fr 1fr;gap:8px}.pick{background:#4b5563;color:#fff}.pick.isSelected{background:#f5c542;color:#111;box-shadow:0 0 0 2px #fff inset}.rowLabel{font-size:12px;color:var(--muted);text-align:center}.slotMode{display:grid;grid-template-columns:1fr 1fr;gap:4px}.amountRow{display:grid;grid-template-columns:1fr 1fr;gap:6px}.hint{font-size:12px;color:var(--muted)}@media(max-width:520px){.two{grid-template-columns:1fr}.grid{grid-template-columns:36px 1fr 82px}}
</style></head><body>
<h1>⚡ LazyBot FS</h1><p class="muted">Fast Scalper • Binance Spot • 3m + pump hunter • WebSocket radar</p>
<div class="card"><h3>Режим</h3><button class="paper" onclick="startSession()">▶ ЗАПУСТИТЬ — PAPER / LIVE ПО ВЫБОРУ</button><div class="two"><button class="stop" onclick="stopSession()">■ STOP</button><button class="em" onclick="emergency()">⛔ EMERGENCY STOP — ЗАКРЫТЬ LIVE</button></div><p id="status">⚪ Бот остановлен</p></div>
<div class="card"><h3>Binance API для LIVE</h3><input id="key" placeholder="API Key" autocomplete="off"><input id="secret" placeholder="Secret Key" type="password" autocomplete="off"><p class="muted">Ключи только для текущей LIVE-сессии. Withdrawals не используются. Для LIVE — Spot Trading + IP restriction.</p></div>
<div class="card"><h3>Бюджет бота</h3><input id="capital" type="number" value="30" min="0.01" step="0.01"><span>USDT</span><p class="muted">Бюджет динамический. LIVE-проверка не даст превысить свободный USDT-баланс.</p></div>
<div class="card"><h3>5 выбранных пар</h3><p class="muted">Заполняй строки по одной. «Выбрать» больше не перезаписывает предыдущую строку. Доля может быть 0–100%, итог — ровно 100%.</p><div id="slots"></div><button class="ghost click" onclick="addSlot()">＋ ДОБАВИТЬ ПАРУ</button><p class="muted">Слева — «Очистить всё» и очистка каждой строки. Справа — доля.</p></div>
<div class="card"><h3>20 кандидатов</h3><button class="ghost click" onclick="recs()">↻ ОБНОВИТЬ АНАЛИЗ</button><div id="r">Загрузка WebSocket-данных…</div></div>
<div class="card"><h3>Топ-5 Fast Scalper</h3><div id="top5">Загрузка…</div></div>
<div class="card"><h3>Session Result</h3><p>Старт: <b id="ib">0</b> USDT</p><p>Баланс: <b id="bal">0</b> USDT</p><p>NET: <b id="pn">0</b> USDT</p><p>Сделок: <b id="n">0</b></p><h4>Открытые сделки</h4><div id="o">Нет</div><h4>Ордера / fills</h4><div id="ord">Нет</div><h4>Последние сделки</h4><div id="t">Нет</div></div>
<script>
let slots=Array.from({length:5},()=>({p:'',a:0,mode:'PAPER',useAmount:false,amount:0}));
function renderSlots(){document.getElementById('slots').innerHTML=slots.map((x,i)=>`<div class="grid"><button class="clear click" onclick="clearSlot(${i})">${i===0?'Очистить всё':'Очистить'}</button><div><input id="p${i}" value="${esc(x.p)}" placeholder="Пара ${i+1}" oninput="slots[${i}].p=this.value.trim().toUpperCase().replace('-', '/')"><div class="slotMode"><button class="mode ${x.mode==='PAPER'?'paperMode':''} click" onclick="setMode(${i},'PAPER')">PAPER</button><button class="mode ${x.mode==='LIVE'?'liveMode':''} click" onclick="setMode(${i},'LIVE')">LIVE</button></div><div class="amountRow"><label class="hint"><input type="checkbox" ${x.useAmount?'checked':''} onchange="slots[${i}].useAmount=this.checked"> Учитывать объём</label><input id="amt${i}" type="number" min="0" step="0.0001" value="${x.amount}" placeholder="Объём/ордер" oninput="slots[${i}].amount=+this.value"></div></div><input id="a${i}" value="${x.a}" type="number" min="0" max="100" step="0.01" oninput="slots[${i}].a=+this.value"></div>`).join('')}
function esc(s){return String(s||'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function clearSlot(i){if(i===0){slots=Array.from({length:5},()=>({p:'',a:0,mode:'PAPER',useAmount:false,amount:0}))}else slots[i]={p:'',a:0,mode:'PAPER',useAmount:false,amount:0};renderSlots()}
function setMode(i,m){slots[i].mode=m;renderSlots();let b=document.querySelectorAll('.mode')[i*2+(m==='LIVE'?1:0)];if(b){b.classList.add('selected');setTimeout(()=>b.classList.remove('selected'),180)}}
function addSlot(){let i=slots.findIndex(x=>!x.p);if(i<0){alert('Все 5 строк уже заняты');return}document.getElementById('p'+i)?.focus();}
function selectCandidate(s,btn){let i=slots.findIndex(x=>!x.p);if(i<0){alert('Все 5 строки уже заняты. Очисти строку слева и выбери снова.');return}slots[i].p=s;renderSlots();let b=document.querySelector(`[data-p="${s}"]`);if(b){b.classList.add('isSelected');b.textContent='✓ Выбрано → строка '+(i+1);setTimeout(()=>{b.classList.remove('isSelected');b.textContent='✓ Выбрать'},500)}}
function cfg(){let xs=slots.filter(x=>x.p).map(x=>({...x,p:x.p.trim().toUpperCase().replace('-', '/')}));return{capital:+document.getElementById('capital').value,slots:xs,pairs:xs.map(x=>x.p),allocations:xs.map(x=>x.a)}}
async function recs(){try{let r=await fetch('/api/recommendations?limit=20');let d=await r.json();if(!d.candidates20.length){document.getElementById('r').textContent='WebSocket подключается… обнови через 3–5 секунд';return}let html=d.candidates20.map((x,i)=>`<div class="rec"><b>${i+1}. ${x.symbol}</b> <span class="pill">${x.signal}</span><br><span class="small price">Цена ${Number(x.price).toPrecision(8)} • 24ч ${Number(x.change_24h_pct).toFixed(2)}% • 3m ${Number(x.change_3m_pct||0).toFixed(3)}% • vol ×${Number(x.volume_ratio||1).toFixed(2)} • pumps ${x.pump_events}</span><br><span class="small">Вход <b>${fmt(x.estimated_entry)}</b> → выход <b>${fmt(x.estimated_exit)}</b> • SL ${fmt(x.estimated_stop)} • ${x.hold_seconds||180} сек.</span><button class="pick click" data-p="${x.symbol}" onclick="selectCandidate('${x.symbol}',this)">✓ Выбрать</button></div>`).join('');document.getElementById('r').innerHTML=html;document.getElementById('top5').innerHTML=d.top5.map((x,i)=>`<div class="rec"><b>#${i+1} ${x.symbol}</b> — ${x.signal} — score ${x.score}<br><span class="small">Вход ${fmt(x.estimated_entry)} → выход ${fmt(x.estimated_exit)} • пампы ${x.pump_events} • удержание ${x.hold_seconds} сек.</span></div>`).join('')}catch(e){document.getElementById('r').textContent='Ошибка анализа: '+e.message}}
function fmt(v){return v==null?'—':Number(v).toPrecision(9)}
async function startSession(){let c=cfg();if(!c.slots.length||Math.abs(c.allocations.reduce((a,b)=>a+b,0)-100)>.01){alert('Выбери 1–5 пар и распредели 100%. Нули разрешены до запуска, но активные строки должны суммироваться в 100%.');return}let r=await fetch('/api/mixed/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...c,api_key:key.value,api_secret:secret.value})});let d=await r.json();if(!r.ok){alert(d.detail||'Ошибка запуска');return}document.getElementById('status').innerHTML='🟢 Сессия работает: '+d.slots.map(x=>x.pair+' '+x.mode).join(', ');refresh()}
async function stopSession(){await fetch('/api/mixed/stop',{method:'POST'});document.getElementById('status').innerHTML='⚪ STOP — бот остановлен; открытые LIVE-позиции не закрываются автоматически';refresh()}
async function emergency(){await fetch('/api/mixed/emergency-stop',{method:'POST'});document.getElementById('status').innerHTML='⛔ EMERGENCY STOP — LIVE закрытие запрошено';refresh()}
async function refresh(){try{let r=await fetch('/api/mixed/status');let d=await r.json();document.getElementById('ib').textContent=Number(d.capital||d.initial_balance||0).toFixed(4);document.getElementById('bal').textContent=Number(d.free_capital||d.balance||0).toFixed(4);document.getElementById('pn').textContent=Number(d.realized_pnl??d.pnl??0).toFixed(4);document.getElementById('n').textContent=(d.trades||[]).length;document.getElementById('o').innerHTML=Object.entries(d.positions||d.open_positions||{}).map(([s,p])=>`<div class="rec"><b>${s}</b> • вход ${fmt(p.entry||p.entry_price)} • объём ${Number(p.amount||0).toPrecision(8)} • бюджет ${Number(p.capital||p.allocated_usdt||0).toFixed(4)} • fills ${(p.fills||[]).length}</div>`).join('')||'Нет';document.getElementById('ord').innerHTML=Object.entries(d.orders||{}).map(([s,o])=>`<div class="rec"><b>${s}</b> • ${o.status} • ${Number(o.filled_amount||o.filledAmount||0).toPrecision(8)} / ${Number(o.requested_amount||0).toPrecision(8)} • fills ${(o.fills||[]).length}</div>`).join('')||'Нет';document.getElementById('t').innerHTML=(d.trades||[]).slice(-10).reverse().map(t=>`<div class="rec"><b>${t.symbol}</b> • ${t.reason||''} • NET ${Number(t.pnl??t.net_pnl??0).toFixed(4)} USDT</div>`).join('')||'Нет'}catch(e){}}
renderSlots();recs();setInterval(refresh,3000);setInterval(recs,15000);refresh();
</script></body></html>'''

@app.get('/', response_class=HTMLResponse)
def home():
    return HTML
