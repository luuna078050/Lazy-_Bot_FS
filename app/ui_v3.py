from __future__ import annotations
import json,time,os,threading
from pathlib import Path
from typing import Any
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from . import fixed_app as core
from .fixed_app import app
from .paper_engine_v2 import start_paper, stop_paper, emergency_stop_paper, snapshot as paper_snapshot
from .market_radar import RADAR

# Replace the old dashboard endpoints with the session/portfolio-aware ones.
for r in list(app.router.routes):
    if getattr(r,'path',None) in {'/','/api/paper/start','/api/paper/stop','/api/paper/emergency-stop','/api/paper/status','/api/live/stop','/api/live/emergency-stop','/api/session/report/{mode}'}:
        app.router.routes.remove(r)

def ws_price(symbol: str) -> float:
    key=symbol.replace('/','').upper()
    with RADAR.lock:
        d=RADAR.tickers.get(key) or {}
        return float(d.get('c') or 0)

def paper_report():
    s=paper_snapshot()
    positions=s.get('positions') or []
    assets=[]
    for p in positions:
        base=p['symbol'].split('/')[0]
        assets.append({'asset':base,'amount':p['amount'],'price':p['current_price'],'value_usdt':p['market_value'],'unrealized_pnl':p['unrealized_pnl']})
    return {'mode':'PAPER','running':s.get('running',False),'started_at':s.get('started_at'),'stopped_at':s.get('stopped_at'),'initial_balance':s.get('initial_balance',0),'free_usdt':s.get('free_usdt',s.get('balance',0)),'equity_usdt':s.get('equity_usdt',s.get('balance',0)),'realized_pnl':s.get('realized_pnl',s.get('pnl',0)),'unrealized_pnl':s.get('unrealized_pnl',0),'net_pnl':s.get('net_pnl',0),'assets':assets,'positions':positions,'orders':list((s.get('orders') or {}).values()),'order_history':s.get('order_history',[])[-30:],'trades':s.get('trades',[])[-50:],'config':s.get('config') or {},'stop_type':s.get('stop_type'),'error':s.get('error')}

def live_report():
    try: state=json.loads(core.LIVE_STATE.read_text()) if core.LIVE_STATE.exists() else {}
    except Exception: state={}
    positions=[]; assets=[]
    for symbol,p in (state.get('positions') or {}).items():
        px=ws_price(symbol); qty=float(p.get('amount') or 0); cap=float(p.get('capital') or 0); value=qty*px if px else cap; upnl=value-cap
        positions.append({**p,'symbol':symbol,'current_price':px,'market_value':value,'unrealized_pnl':upnl,'age_sec':max(0,time.time()-float(p.get('opened') or time.time())),'stage':'OPEN'})
        assets.append({'asset':symbol.split('/')[0],'amount':qty,'price':px,'value_usdt':value,'unrealized_pnl':upnl})
    free=float(state.get('free_capital') or 0); initial=float(state.get('capital') or 0); equity=free+sum(float(x['market_value']) for x in positions); realized=float(state.get('realized_pnl') or 0)
    running=bool(core.LIVE_PROC and core.LIVE_PROC.poll() is None)
    return {'mode':'LIVE','running':running,'started_at':state.get('started_at'),'stopped_at':state.get('stopped_at'),'initial_balance':initial,'free_usdt':free,'equity_usdt':equity,'realized_pnl':realized,'unrealized_pnl':equity-initial-realized,'net_pnl':equity-initial,'assets':assets,'positions':positions,'orders':list((state.get('orders') or {}).values()),'order_history':[],'trades':list(state.get('trades') or [])[-50:],'config':state.get('config') or {},'stop_type':state.get('stop_type'),'error':state.get('error')}

@app.post('/api/paper/start')
def pstart(payload:dict[str,Any]): return start_paper(payload)
@app.post('/api/paper/stop')
def pstop(): return stop_paper()
@app.post('/api/paper/emergency-stop')
def pemergency(): return emergency_stop_paper()
@app.get('/api/paper/status')
def pstatus(): return paper_snapshot()

@app.post('/api/live/stop')
def lstop():
    core.LIVE_CONTROL.write_text(json.dumps({'command':'STOP'}))
    deadline=time.time()+8
    while time.time()<deadline:
        with core.LIVE_LOCK: proc=core.LIVE_PROC
        if not proc or proc.poll() is not None: break
        time.sleep(.25)
    with core.LIVE_LOCK: proc=core.LIVE_PROC; core.LIVE_PROC=None
    if proc and proc.poll() is None: proc.terminate()
    return {'ok':True,'running':False,'stop_type':'STOP'}

@app.post('/api/live/emergency-stop')
def lemergency():
    core.LIVE_CONTROL.write_text(json.dumps({'command':'EMERGENCY_STOP'}))
    deadline=time.time()+12
    while time.time()<deadline:
        with core.LIVE_LOCK: proc=core.LIVE_PROC
        if not proc or proc.poll() is not None: break
        time.sleep(.25)
    with core.LIVE_LOCK: proc=core.LIVE_PROC; core.LIVE_PROC=None
    if proc and proc.poll() is None: proc.terminate()
    return {'ok':True,'running':False,'stop_type':'EMERGENCY_STOP'}

@app.get('/api/session/report/{mode}')
def session_report(mode:str):
    if mode.upper()=='PAPER': return paper_report()
    if mode.upper()=='LIVE': return live_report()
    raise HTTPException(400,'Unknown mode')

HTML=r'''<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper</title><style>:root{--bg:#101827;--card:#202b3b;--field:#3a4658;--muted:#aeb8c7;--line:#394659;--blue:#2563eb;--green:#16a34a;--red:#dc2626;--gold:#f5c542}*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:#fff;max-width:820px;margin:auto;padding:10px}.card{background:var(--card);border-radius:18px;padding:14px;margin:10px 0}button,input{border:0;border-radius:10px;padding:11px;font-size:15px}input{background:var(--field);color:#fff;border:1px solid #59677a;width:100%}button{font-weight:800;color:#fff;width:100%;cursor:pointer}.two{display:grid;grid-template-columns:1fr 1fr;gap:7px}.paper{background:var(--blue)}.live{background:var(--green)}.stop{background:var(--red)}.em{background:#7f1d1d}.ghost{background:#475569}.muted,.small{color:var(--muted);font-size:12px}.timer{font-size:20px;font-weight:900}.slot{display:grid;grid-template-columns:62px 1fr 72px;gap:6px;margin:8px 0}.modes{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:4px}.mode{background:#526174}.active{box-shadow:0 0 0 3px var(--gold) inset}.summary{display:grid;grid-template-columns:1fr 1fr;gap:6px}.metric{background:#182234;border-radius:10px;padding:8px}.metric b{display:block;font-size:16px}.pos,.row{border:1px solid var(--line);border-radius:10px;padding:8px;margin:6px 0}.green{color:#86efac}.red{color:#fca5a5}.stage{background:#475569;border-radius:7px;padding:2px 6px;font-size:11px}.rec{padding:8px 0;border-bottom:1px solid var(--line)}@media(max-width:520px){.slot{grid-template-columns:56px 1fr 64px}}</style></head><body><h2>⚡ Fast Scalper</h2><p class="muted">Binance Spot • WebSocket radar • PAPER и LIVE независимы</p>
<div class="card"><b>Запуск</b><div class="two"><div><h4>PAPER</h4><button class="paper" onclick="run('PAPER')">▶ ЗАПУСТИТЬ PAPER</button><button class="stop" onclick="stopMode('PAPER')">■ STOP PAPER</button><div id="ps">⚪ остановлен</div><div id="pt" class="timer">00:00:00</div></div><div><h4>LIVE</h4><button class="live" onclick="run('LIVE')">▶ ЗАПУСТИТЬ LIVE</button><button class="stop" onclick="stopMode('LIVE')">■ STOP LIVE</button><button class="em" onclick="stopMode('LIVE',true)">⛔ EMERGENCY STOP</button><div id="ls">⚪ остановлен</div><div id="lt" class="timer">00:00:00</div></div></div><p class="muted">STOP = остановить новые входы. Активные позиции НЕ ликвидируются: они остаются в портфеле и входят в конечную стоимость. EMERGENCY = закрыть открытые позиции.</p></div>
<div class="card"><b>Binance API для LIVE</b><input id="key" placeholder="API Key" autocomplete="off"><input id="secret" type="password" placeholder="Secret Key" autocomplete="off"><p class="muted">Withdrawals не используются. Только Spot Trading + IP restriction.</p></div>
<div class="card"><b>Бюджет</b><input id="capital" type="number" value="30" min="0.01" step="0.01"><span class="muted"> USDT</span></div>
<div class="card"><b>5 выбранных пар</b><p class="muted">Можно распределить пары отдельно для PAPER и LIVE. Доли внутри каждого режима должны дать 100%.</p><div id="slots"></div></div>
<div class="card"><b>Топ-5 Fast Scalper</b><div id="top5">Загрузка…</div></div><div class="card"><b>20 кандидатов</b><button class="ghost" onclick="recs()">↻ ОБНОВИТЬ СПИСОК</button><div id="r">Загрузка WebSocket…</div></div>
<div class="card"><b>Session Result — полный итог</b><div id="res">Нет активной сессии</div></div>
<script>let slots=JSON.parse(localStorage.getItem('fsSlotsV3')||'null')||Array.from({length:5},()=>({p:'',a:20,mode:'PAPER'}));const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');const f=v=>v==null?'—':Number(v).toFixed(6);const pad=n=>String(n).padStart(2,'0');function save(){localStorage.setItem('fsSlotsV3',JSON.stringify(slots))}function render(){document.getElementById('slots').innerHTML=slots.map((x,i)=>`<div class="slot"><button class="ghost" onclick="clearSlot(${i})">ОЧИСТИТЬ</button><div><input value="${esc(x.p)}" placeholder="Пара ${i+1}" oninput="slots[${i}].p=this.value.trim().toUpperCase().replace('-', '/');save()"><div class="modes"><button class="mode ${x.mode==='PAPER'?'active':''}" onclick="setMode(${i},'PAPER')">PAPER</button><button class="mode ${x.mode==='LIVE'?'active':''}" onclick="setMode(${i},'LIVE')">LIVE</button></div></div><input type="number" min="0.01" max="100" step="0.01" value="${x.a}" oninput="slots[${i}].a=+this.value;save()"></div>`).join('')}function clearSlot(i){slots[i]={p:'',a:20,mode:'PAPER'};save();render()}function setMode(i,m){slots[i].mode=m;save();render()}function cfg(m){let a=slots.filter(x=>x.p&&x.mode===m);return {capital:+document.getElementById('capital').value,pairs:a.map(x=>x.p),allocations:a.map(x=>x.a),target_usdt:.30,min_usdt:.20,sl_pct:.5,max_hold:180,fee_pct:.1}}async function run(m){let c=cfg(m),sum=c.allocations.reduce((a,b)=>a+b,0);if(!c.pairs.length)return alert('Нет выбранных '+m+' пар.');if(Math.abs(sum-100)>.01)return alert(m+': доли должны дать 100%. Сейчас '+sum.toFixed(2)+'%.');if(m==='LIVE'){c.api_key=key.value;c.api_secret=secret.value;if(!c.api_key||!c.api_secret)return alert('Для LIVE нужны API Key и Secret')}let q=await fetch('/api/'+m.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c)}),d=await q.json();if(!q.ok)return alert(d.detail||'Ошибка запуска');refresh()}async function stopMode(m,em=false){let q=await fetch('/api/'+m.toLowerCase()+'/'+(em?'emergency-stop':'stop'),{method:'POST'}),d=await q.json();if(!q.ok)alert(d.detail||'Ошибка остановки');refresh()}function timer(id,started){let t=started?(Date.now()-new Date(started).getTime())/1000:0;document.getElementById(id).textContent=started?`${pad(Math.floor(t/3600))}:${pad(Math.floor(t%3600/60))}:${pad(Math.floor(t%60))}`:'00:00:00'}function report(d){const cls=v=>Number(v)>=0?'green':'red';let assets=(d.assets||[]).map(a=>`<div class="row"><b>${esc(a.asset)}</b> • ${Number(a.amount).toFixed(8)} • цена ${f(a.price)} • стоимость ${f(a.value_usdt)} USDT • P/L <b class="${cls(a.unrealized_pnl)}">${f(a.unrealized_pnl)}</b></div>`).join('')||'<span class="small">Нет активов</span>';let pos=(d.positions||[]).map(p=>`<div class="pos"><b>${esc(p.symbol)}</b> <span class="stage">${esc(p.stage||'OPEN')}</span><br><span class="small">вход ${f(p.entry_price??p.entry)} → текущая ${f(p.current_price)} • qty ${Number(p.amount||0).toFixed(8)}</span><br><span class="small">стоимость ${f(p.market_value)} USDT • нереализованный P/L <b class="${cls(p.unrealized_pnl)}">${f(p.unrealized_pnl)}</b> • стадия ${esc(p.signal||'—')}</span></div>`).join('')||'<span class="small">Нет открытых позиций</span>';let ord=(d.orders||[]).map(o=>`<div class="row"><b>${esc(o.symbol)}</b> • ${esc(o.side||'—')} • ${esc(o.status||'—')} • fills ${(o.fills||[]).length}</div>`).join('')||'<span class="small">Нет активных заявок</span>';let hist=(d.order_history||[]).slice().reverse().slice(0,10).map(o=>`<div class="row"><b>${esc(o.symbol)}</b> • ${esc(o.side||'—')} • ${esc(o.status||'—')} • цена ${f(o.price)} • ${esc(o.reason||'')}</div>`).join('')||'<span class="small">Нет fills</span>';let tr=(d.trades||[]).slice().reverse().slice(0,10).map(t=>`<div class="row"><b>${esc(t.symbol)}</b> • ${f(t.entry_price??t.entry)} → ${f(t.exit_price??t.exit)} • P/L <b class="${cls(t.net_pnl??t.pnl)}">${f(t.net_pnl??t.pnl)}</b> • ${esc(t.reason||'—')}</div>`).join('')||'<span class="small">Сделок пока нет</span>';document.getElementById('res').innerHTML=`<div class="summary"><div class="metric">Старт<b>${f(d.initial_balance)} USDT</b></div><div class="metric">Свободно<b>${f(d.free_usdt)} USDT</b></div><div class="metric">Стоимость<b>${f(d.equity_usdt)} USDT</b></div><div class="metric">NET<b class="${cls(d.net_pnl)}">${f(d.net_pnl)} USDT</b></div><div class="metric">Реализовано<b class="${cls(d.realized_pnl)}">${f(d.realized_pnl)}</b></div><div class="metric">Нереализовано<b class="${cls(d.unrealized_pnl)}">${f(d.unrealized_pnl)}</b></div></div><h4>Портфель на конец сессии</h4>${assets}<h4>Открытые позиции (${(d.positions||[]).length})</h4>${pos}<h4>Активные ордера (${(d.orders||[]).length})</h4>${ord}<h4>Последние fills</h4>${hist}<h4>Последние закрытые сделки</h4>${tr}${d.error?`<p class="red">Ошибка: ${esc(d.error)}</p>`:''}${d.stop_type?`<p class="small">Стоп: ${esc(d.stop_type)}</p>`:''}`}async function refresh(){for(const m of ['PAPER','LIVE']){let d=await (await fetch('/api/session/report/'+m)).json();timer(m==='PAPER'?'pt':'lt',d.started_at);document.getElementById(m==='PAPER'?'ps':'ls').textContent=d.running?'🟢 работает':'⚪ остановлен';if(m==='PAPER'||d.running)report(d)}let p=await (await fetch('/api/session/report/PAPER')).json();report(p)}async function recs(){try{let d=await (await fetch('/api/recommendations?limit=20')).json();if(!d.candidates20?.length){r.textContent='WebSocket подключается…';return}r.innerHTML=d.candidates20.map((x,i)=>`<div class="rec"><b>${i+1}. ${esc(x.symbol)}</b> • ${esc(x.signal)} • score ${x.score}<br><span class="small">цена ${f(x.price)} • 24ч ${Number(x.change_24h_pct).toFixed(2)}% • 3m ${Number(x.change_3m_pct).toFixed(3)}% • vol ×${Number(x.volume_ratio).toFixed(2)} • вход ${f(x.estimated_entry)} → выход ${f(x.estimated_exit)}</span><button class="ghost" onclick="selectPair('${esc(x.symbol)}')">ВЫБРАТЬ</button></div>`).join('');top5.innerHTML=d.top5.map((x,i)=>`<div class="rec"><b>#${i+1} ${esc(x.symbol)}</b> • ${esc(x.signal)} • score ${x.score}<br><span class="small">${f(x.estimated_entry)} → ${f(x.estimated_exit)} • удержание ${x.hold_seconds}с</span></div>`).join('')}catch(e){r.textContent='Ошибка анализа: '+e.message}}function selectPair(s){let i=slots.findIndex(x=>!x.p);if(i<0)return alert('Все 5 строк заняты.');slots[i].p=s;save();render()}render();recs();refresh();setInterval(refresh,1000);setInterval(recs,5000)</script></body></html>'''

@app.get('/',response_class=HTMLResponse)
def home(): return HTML
