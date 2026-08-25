from __future__ import annotations

import json
import time
from typing import Any

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.routing import request_response

from .fixed_app import app, gateway, LIVE_STATE, LIVE_PROC, LIVE_LOCK
from .market_radar import RADAR
from . import fixed_app as core
from .profit_first_engine_v4 import start_paper, stop_paper, emergency_stop_paper, snapshot


def _remove(path: str) -> None:
    for r in list(app.router.routes):
        if getattr(r, "path", None) == path:
            app.router.routes.remove(r)


def _paper_report() -> dict[str, Any]:
    s = snapshot()
    positions = list((s.get("open_positions") or {}).values())
    free = float(s.get("free_usdt", 0) or 0)
    capital = float(s.get("initial_balance", 0) or 0)
    realized = float(s.get("realized_pnl", 0) or 0)
    unreal = float(s.get("unrealized_pnl", 0) or 0)
    return {
        "mode": "PAPER", "running": bool(s.get("running")),
        "started_at": s.get("started_at"), "stopped_at": s.get("stopped_at"),
        "initial_balance": capital, "account_balance_usdt": free + realized,
        "bot_balance_usdt": capital, "free_usdt": free,
        "equity_usdt": float(s.get("equity_usdt", free + unreal) or 0),
        "realized_pnl": realized, "unrealized_pnl": unreal,
        "net_pnl": float(s.get("net_pnl", realized + unreal) or 0),
        "positions": positions, "open_positions": positions,
        "orders": list((s.get("orders") or {}).values()),
        "order_history": list(s.get("order_history") or [])[-50:],
        "trades": list(s.get("trades") or [])[-50:],
        "config": s.get("config") or {}, "error": s.get("error"),
        "stop_type": s.get("stop_type"),
    }


def _live_report() -> dict[str, Any]:
    try:
        state = json.loads(LIVE_STATE.read_text()) if LIVE_STATE.exists() else {}
    except Exception:
        state = {}
    with LIVE_LOCK:
        running = bool(LIVE_PROC and LIVE_PROC.poll() is None)
    state["running"] = running
    state["mode"] = "LIVE"
    state.setdefault("positions", [])
    state.setdefault("trades", [])
    state.setdefault("orders", {})
    return state


def _recommendations(limit: int = 20):
    rows = RADAR.snapshot(max(10, min(int(limit), 20)))
    return {"ok": True, "generated_at": time.time(), "data_source": "Binance WebSocket",
            "rest_polling": False, "radar_error": RADAR.last_error,
            "candidates20": rows[:20], "top5": rows[:5]}


# Replace the old paper routes so PAPER always uses the same engine as the report.
for _p in ("/api/paper/start", "/api/paper/stop", "/api/paper/emergency-stop", "/api/paper/status", "/api/session/report/{mode}", "/api/recommendations", "/"):
    _remove(_p)


@app.get("/api/recommendations")
def recommendations(limit: int = 20):
    try:
        return _recommendations(limit)
    except Exception as exc:
        return {"ok": True, "generated_at": time.time(), "data_source": "Binance WebSocket",
                "rest_polling": False, "radar_error": str(exc)[:300], "candidates20": [], "top5": []}


@app.post("/api/paper/start")
def paper_start(payload: dict[str, Any]):
    try:
        result = start_paper(payload, gateway)
        return {"ok": True, **result}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, str(exc)[:300])


@app.post("/api/paper/stop")
def paper_stop():
    return {"ok": True, **stop_paper(gateway)}


@app.post("/api/paper/emergency-stop")
def paper_emergency():
    return {"ok": True, **emergency_stop_paper(gateway)}


@app.get("/api/paper/status")
def paper_status():
    return snapshot()


@app.get("/api/session/report/{mode}")
def session_report(mode: str):
    mode = mode.upper()
    if mode == "PAPER":
        return _paper_report()
    if mode == "LIVE":
        return _live_report()
    raise HTTPException(400, "Unknown mode")


CONTROL_HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fast Scalper</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#08090a;color:#eee;font-family:Arial,system-ui,sans-serif}.wrap{max-width:760px;margin:auto;padding:14px 18px 40px}.card{border:1px solid #5b0b13;border-radius:20px;background:#090a0b;margin:12px 0;padding:12px}.title{color:#ff303b;font-weight:900;font-size:21px;margin:0 0 8px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}.mode{border:1px solid #541018;border-radius:14px;padding:8px;text-align:center}.label{font-weight:900;color:#ddd}.switch{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-width:96px;border:1px solid #555;background:#1c1d20;color:#aaa;border-radius:22px;padding:8px 15px;font-weight:900;cursor:pointer}.switch.on{background:#0a8d40;border-color:#20ef76;color:#fff}.dot{width:10px;height:10px;border-radius:50%;background:#777}.switch.on .dot{background:#2dff7c}.status{font-size:13px;color:#777;margin-top:4px}.status.on{color:#21ed71}.timer{font-size:22px;font-weight:900;margin-top:4px;font-variant-numeric:tabular-nums}.em{width:100%;border:0;border-radius:18px;background:#2b2c30;color:#eee;padding:8px;font-weight:900;margin-top:8px}.big{font-size:44px;font-weight:900;color:#ffb300}.balance{border:1px solid #7d5b00;border-radius:18px;padding:12px;margin-top:8px}.muted{color:#aaa}.row4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;border-top:1px solid #4b151a;margin-top:12px;padding-top:10px}.metric b{display:block;color:#eee}.metric small{color:#aaa}.metric.net b{color:#62ef89}.empty{font-size:22px;color:#ddd}.top{display:grid;grid-template-columns:1fr 1fr;gap:8px}.pair{border:1px solid #53101a;border-radius:14px;padding:9px;background:#08090a}.rank{display:flex;justify-content:space-between;font-weight:900}.score{color:#65ef8a;border:1px solid #1d8d46;border-radius:6px;padding:2px 6px}.meta{display:grid;grid-template-columns:1fr 1fr;gap:3px;color:#aaa;font-size:11px;margin-top:6px}.price{color:#ff4050;font-weight:900;font-size:15px}.green{color:#65ef8a}.pair button,.pick{width:100%;border:1px solid #ffb300;background:#211804;color:#ffd04d;border-radius:8px;padding:7px;font-weight:900;margin-top:7px}.pair button.selected{background:#078b40;border-color:#21f275;color:white}.pos{border:1px solid #53101a;border-radius:12px;padding:8px;margin:6px 0}.controls{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.tf{border:1px solid #444;background:#191a1c;color:#bbb;border-radius:9px;padding:10px;font-weight:900}.tf.active{border-color:#ffb300;color:#ffd04d}.slots{display:grid;grid-template-columns:1fr 1fr;gap:7px}.slot{border:1px solid #53101a;border-radius:12px;padding:8px}.slot input,.slot select,.api input{width:100%;background:#151619;color:#eee;border:1px solid #4e1018;border-radius:8px;padding:9px;margin-bottom:6px}.slot button{width:100%;background:#292a2d;color:#eee;border:0;border-radius:8px;padding:8px;font-weight:900}.alloc{display:flex;gap:7px}.alloc button{flex:1;padding:9px;border-radius:9px;border:1px solid #444;background:#1a1b1d;color:#bbb;font-weight:900}.alloc button.active{background:#087d39;color:#fff;border-color:#20ef76}.api{margin-top:8px}.notice{color:#ffd04d;font-size:12px}.error{color:#ff5962}.hidden{display:none}@media(max-width:560px){.row4{grid-template-columns:1fr 1fr}.top,.slots{grid-template-columns:1fr 1fr}.big{font-size:39px}}
</style></head><body><div class="wrap">
<div class="card"><div class="title">⚡ УПРАВЛЕНИЕ БОТОМ</div><div class="grid2">
<div class="mode"><div class="label">PAPER</div><button id="paperSwitch" class="switch" onclick="toggleMode('PAPER')"><span class="dot"></span><span>OFF</span></button><div id="paperStatus" class="status">PAPER остановлен</div><div id="paperTimer" class="timer">00:00:00</div></div>
<div class="mode"><div class="label">LIVE</div><button id="liveSwitch" class="switch" onclick="toggleMode('LIVE')"><span class="dot"></span><span>OFF</span></button><div id="liveStatus" class="status">LIVE остановлен</div><div id="liveTimer" class="timer">00:00:00</div></div></div><button class="em" onclick="emergency()">⛔ EMERGENCY STOP</button></div>
<div class="card"><div class="title">PnL СЕГОДНЯ / ACCUMULATED</div><div id="pnlBig" class="big">0.0000 USDT (0.00%)</div><div class="balance"><div>💼 BALANCE ACCOUNT</div><b id="balance" style="font-size:25px">100.0000 USDT</b><div class="muted">(including bot accumulated: <span id="acc">0.0000</span> USDT)</div><div class="row4"><div class="metric"><small>Realized PnL</small><b id="realized">0.0000</b></div><div class="metric"><small>Unrealized PnL</small><b id="unrealized">0.0000</b></div><div class="metric net"><small>Net PnL</small><b id="net">0.0000</b></div><div class="metric net"><small>Hypothetical Net</small><b id="equity">0.0000</b></div></div></div></div>
<div class="card"><div class="title">📋 SESSION RESULT</div><div id="sessionText" class="empty">Нет активной сессии</div></div>
<div class="card"><div class="title">📜 ПОСЛЕДНИЕ ЗАКРЫТЫЕ СДЕЛКИ · 15 МИН</div><div id="recent">Нет сделок</div></div>
<div class="card"><div class="title">🚀 ТОП ПАРЫ · РЕЙТИНГ СИГНАЛОВ</div><div id="radarInfo" class="muted">Подключение радара…</div><div id="top" class="top"></div></div>
<div class="card"><div class="title">🔴 ОТКРЫТЫЕ ПОЗИЦИИ</div><div id="positions">Нет открытых позиций</div></div>
<div class="card"><div class="title">⚙ РЕЖИМ РАБОТЫ</div><div class="muted">Таймфрейм</div><div class="controls"><button class="tf active" data-tf="3m" onclick="setDefaultTf('3m')">3m</button><button class="tf" data-tf="1m" onclick="setDefaultTf('1m')">1m</button><button class="tf" data-tf="5m" onclick="setDefaultTf('5m')">5m</button></div><div class="muted" style="margin-top:7px">Сделка может закрыться раньше горизонта, если цель/стенка/гипотеза сработали.</div></div>
<div class="card"><div class="title">⚙ НАСТРОЙКИ СЕССИИ</div><div class="muted">Выделенный баланс бота</div><input id="capital" value="100" type="number" min="0.01" step="0.01" style="width:100%;background:#151619;color:#eee;border:1px solid #53101a;border-radius:9px;padding:10px"><div class="alloc"><button id="autoBtn" class="active" onclick="setAlloc('AUTO')">АВТОРАСПРЕДЕЛЕНИЕ</button><button id="manualBtn" onclick="setAlloc('MANUAL')">ВРУЧНУЮ</button></div><div id="slots" class="slots"></div><div id="allocTotal" class="muted">PAPER 0% • LIVE 0% • ВСЕГО 0%</div><div class="api"><input id="apiKey" placeholder="Binance API Key"><input id="apiSecret" placeholder="Binance Secret Key" type="password"></div></div>
</div>
<script>
const SLOT_KEY='fsStableSlotsV1', RANK_KEY='fsStableRankingV1';
let slots=JSON.parse(localStorage.getItem(SLOT_KEY)||'[]'); while(slots.length<10)slots.push({p:'',v:0,tf:'3m',mode:'PAPER'}); slots=slots.slice(0,10);
let allocMode='AUTO', defaultTf='3m';
let state={PAPER:{running:false,started_at:null},LIVE:{running:false,started_at:null}}; let lastRank=JSON.parse(localStorage.getItem(RANK_KEY)||'[]');
const $=id=>document.getElementById(id); const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function parseTs(v){if(v==null)return 0;if(typeof v==='number')return v<1e12?v*1000:v;const n=Number(v);if(Number.isFinite(n)&&n>0)return n<1e12?n*1000:n;const t=Date.parse(v);return Number.isFinite(t)?t:0}
function fmt(sec){sec=Math.max(0,Math.floor(sec));const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=sec%60;return [h,m,s].map(x=>String(x).padStart(2,'0')).join(':')}
function saveSlots(){localStorage.setItem(SLOT_KEY,JSON.stringify(slots))}
function renderSlots(){ $('slots').innerHTML=slots.map((x,i)=>`<div class="slot"><input value="${esc(x.p)}" placeholder="ПАРА ${i+1}" onchange="slotPair(${i},this.value)"><select onchange="slotTf(${i},this.value)"><option value="1m" ${x.tf==='1m'?'selected':''}>1 мин</option><option value="3m" ${x.tf==='3m'?'selected':''}>3 мин</option><option value="5m" ${x.tf==='5m'?'selected':''}>5 мин</option></select><input type="number" min="0" max="100" step="0.01" value="${Number(x.v||0)}" onchange="slotVal(${i},this.value)"><button onclick="clearSlot(${i})">ОЧИСТИТЬ</button></div>`).join(''); updateAlloc()}
function slotPair(i,v){slots[i].p=v.trim().toUpperCase().replace('-', '/');saveSlots();renderSlots()}
function slotTf(i,v){slots[i].tf=v;saveSlots()}
function slotVal(i,v){slots[i].v=Math.max(0,Number(v)||0);if(allocMode==='AUTO')rebalance(i);saveSlots();renderSlots()}
function clearSlot(i){slots[i]={p:'',v:0,tf:defaultTf,mode:'PAPER'};saveSlots();renderSlots()}
function selected(){return slots.filter(x=>x.p)}
function rebalance(changed){const arr=slots.map((x,i)=>({x,i})).filter(z=>z.x.p);if(!arr.length)return;const fixed=Math.min(100,Math.max(0,Number(slots[changed].v)||0));const other=arr.filter(z=>z.i!==changed);slots[changed].v=fixed;if(!other.length)return;const each=Math.max(0,(100-fixed)/other.length);other.forEach(z=>z.x.v=Math.round(each*100)/100)}
function updateAlloc(){const t=selected().reduce((s,x)=>s+Number(x.v||0),0);$('allocTotal').textContent=`PAPER ${selected().filter(x=>x.mode==='PAPER').reduce((s,x)=>s+Number(x.v||0),0).toFixed(2)}% • LIVE ${selected().filter(x=>x.mode==='LIVE').reduce((s,x)=>s+Number(x.v||0),0).toFixed(2)}% • ВСЕГО ${t.toFixed(2)}%`;}
function setAlloc(m){allocMode=m;$('autoBtn').classList.toggle('active',m==='AUTO');$('manualBtn').classList.toggle('active',m==='MANUAL');if(m==='AUTO'&&selected().length){const each=100/selected().length;slots.forEach(x=>{if(x.p)x.v=Math.round(each*100)/100});saveSlots();renderSlots()}}
function setDefaultTf(tf){defaultTf=tf;document.querySelectorAll('.tf').forEach(b=>b.classList.toggle('active',b.dataset.tf===tf))}
function markChosen(){document.querySelectorAll('[data-sym]').forEach(b=>{const s=b.dataset.sym;const yes=selected().some(x=>x.p===s);b.classList.toggle('selected',yes);b.textContent=yes?'✓ ВЫБРАНО':'ВЫБРАТЬ'})}
function pick(sym){let i=slots.findIndex(x=>!x.p);if(i<0){alert('Все 10 торговых слотов заняты.');return}slots[i]={p:sym,v:allocMode==='AUTO'?100/(selected().length+1):0,tf:defaultTf,mode:'PAPER'};if(allocMode==='AUTO'){const arr=selected();const each=100/arr.length;arr.forEach(x=>x.v=Math.round(each*100)/100)}saveSlots();renderSlots();markChosen()}
function renderRank(rows){if(!rows.length){$('radarInfo').textContent='Радар временно обновляется; сохранённый рейтинг остаётся на экране.';return} $('radarInfo').textContent='Binance WebSocket • обновлено '+new Date().toLocaleTimeString();$('top').innerHTML=rows.slice(0,10).map((x,i)=>`<div class="pair"><div class="rank"><span>🔥 #${i+1} ${esc(x.symbol)}</span><span class="score">${Number(x.score||0).toFixed(0)}</span></div><div class="meta"><span>Hot: ${Number(x.hot_market_score||0).toFixed(0)}</span><span>Flow: ${Number(x.buy_ratio||.5)*100 .toFixed? (Number(x.buy_ratio||.5)*100).toFixed(0):'—'}%</span><span>1–3m: ${Number(x.change_3m_pct||0).toFixed(3)}%</span><span>$/мин/$100: <b class="green">$${Number(x.expected_pnl_per_min_100||0).toFixed(2)}</b></span></div><div class="price">${Number(x.price||0).toPrecision(9)}</div><div class="muted">Вход → ориентир выхода: ${Number(x.estimated_entry||0).toPrecision(9)} → ${Number(x.estimated_exit||0).toPrecision(9)} • SL ${Number(x.estimated_stop||0).toPrecision(9)}</div><div class="muted">Стенки/поток: ${esc(x.signal||'NORMAL')} • горизонт ${x.hold_seconds||180} сек.</div><button class="pick" data-sym="${esc(x.symbol)}" onclick="pick(this.dataset.sym)">ВЫБРАТЬ</button></div>`).join('');markChosen()}
async function loadRank(){try{const r=await fetch('/api/recommendations?limit=20',{cache:'no-store'});const d=await r.json();if(r.ok&&Array.isArray(d.candidates20)&&d.candidates20.length){lastRank=d.candidates20;localStorage.setItem(RANK_KEY,JSON.stringify(lastRank));renderRank(lastRank)}}catch(e){}} 
function renderPositions(d){const ps=d.positions||d.open_positions||[];if(!Array.isArray(ps)||!ps.length){$('positions').textContent='Нет открытых позиций';return}$('positions').innerHTML=ps.map(p=>`<div class="pos"><b>${esc(p.symbol)}</b> • вход ${Number(p.entry_price||0).toPrecision(9)} • сейчас ${Number(p.current_price||0).toPrecision(9)} • PnL ${Number(p.unrealized_pnl||0).toFixed(4)} USDT • возраст ${Math.floor(Number(p.age_sec||0))}с</div>`).join('')}
function renderReport(d,mode){const running=!!d.running; state[mode]={running,started_at:d.started_at||null}; const sw=$(mode.toLowerCase()+'Switch');sw.classList.toggle('on',running);sw.querySelector('span:last-child').textContent=running?'ON':'OFF';$(mode.toLowerCase()+'Status').textContent=mode+' '+(running?'работает':'остановлен');$(mode.toLowerCase()+'Status').classList.toggle('on',running);const cap=Number(d.initial_balance||0), real=Number(d.realized_pnl||0), un=Number(d.unrealized_pnl||0), net=Number(d.net_pnl||real+un), bal=Number(d.account_balance_usdt||d.equity_usdt||cap);$('balance').textContent=bal.toFixed(4)+' USDT';$('acc').textContent=Math.max(0,bal-cap).toFixed(4);$('realized').textContent=real.toFixed(4)+' USDT';$('unrealized').textContent=un.toFixed(4)+' USDT';$('net').textContent=net.toFixed(4)+' USDT';$('equity').textContent=Number(d.equity_usdt||bal).toFixed(4)+' USDT';$('pnlBig').textContent=real.toFixed(4)+' USDT ('+(cap?((real/cap)*100).toFixed(2):'0.00')+'%)';$('sessionText').textContent=running?'PAPER'===mode?'PAPER сессия активна':'LIVE сессия активна':'Нет активной сессии';renderPositions(d);const tr=(d.trades||[]).slice(-5).reverse();$('recent').innerHTML=tr.length?tr.map(t=>`<div class="pos"><b>${esc(t.symbol||'')}</b> • ${Number(t.entry_price||0).toPrecision(9)} → ${Number(t.exit_price||0).toPrecision(9)} • NET ${Number(t.net_pnl||0).toFixed(4)} USDT • ${esc(t.reason||'')}</div>`).join(''):'Нет сделок'}
async function syncMode(mode){try{const r=await fetch('/api/session/report/'+mode,{cache:'no-store'});if(!r.ok)return;const d=await r.json();renderReport(d,mode)}catch(e){}}
async function toggleMode(mode){const running=state[mode].running;const c=getCfg(mode);let url='/api/'+mode.toLowerCase()+(running?'/stop':'/start');if(running){const r=await fetch(url,{method:'POST'});if(r.ok)await syncMode(mode);return}if(!c.pairs.length){alert('Нет выбранных пар. Выберите позиции из рейтинга.');return}if(Math.abs(c.allocations.reduce((a,b)=>a+b,0)-100)>.01){alert('Распределение выбранных пар должно дать 100%.');return}if(mode==='LIVE'){c.api_key=$('apiKey').value.trim();c.api_secret=$('apiSecret').value.trim();if(!c.api_key||!c.api_secret){alert('Для LIVE нужны API Key и Secret');return}}try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c)});const d=await r.json();if(!r.ok||!d.running){alert(d.detail||'Запуск не выполнен');return}await syncMode(mode)}catch(e){alert('Ошибка запуска: '+e.message)}}
function getCfg(mode){const a=slots.map((x,i)=>({x,i})).filter(z=>z.x.p);return {capital:Number($('capital').value)||0,pairs:a.map(z=>z.x.p),allocations:a.map(z=>Number(z.x.v||0)),timeframes:a.map(z=>z.x.tf||defaultTf),target_usdt:.30,min_usdt:.15,sl_pct:1.2,max_hold:180,fee_pct:.10,risk_mode:'PROFIT_FIRST',mode}}
async function emergency(){await fetch('/api/paper/emergency-stop',{method:'POST'});await fetch('/api/live/emergency-stop',{method:'POST'});await syncMode('PAPER');await syncMode('LIVE')}
function tickTimers(){for(const m of ['PAPER','LIVE']){const tm=$(m.toLowerCase()+'Timer');if(!state[m].running){tm.textContent='00:00:00';continue}const ts=parseTs(state[m].started_at);tm.textContent=ts?fmt((Date.now()-ts)/1000):'00:00:00'}}
renderSlots();if(lastRank.length)renderRank(lastRank);loadRank();syncMode('PAPER');syncMode('LIVE');setInterval(tickTimers,250);setInterval(()=>{syncMode('PAPER');syncMode('LIVE')},1000);setInterval(loadRank,3000);
</script></body></html>'''


def _root(*args, **kwargs):
    return HTMLResponse(CONTROL_HTML, headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0", "Pragma":"no-cache", "Expires":"0"})

app.router.routes.append(type("StableRoute", (), {"path":"/", "endpoint":_root, "methods":{"GET"}, "app":request_response(_root)})())
