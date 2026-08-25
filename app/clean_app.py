from __future__ import annotations
import json, os, subprocess, sys, threading, time
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from .exchange_gateway import gateway
from .market_radar import RADAR
from .profit_first_engine_v4 import start_paper, stop_paper, emergency_stop_paper, snapshot as paper_snapshot
from . import fixed_app as live_core

app=FastAPI(title='Fast Scalper',version='clean-1')
LIVE_PROC=None; LIVE_LOCK=threading.Lock(); LIVE_STATE=live_core.LIVE_STATE; LIVE_CONTROL=live_core.LIVE_CONTROL

def pair(v:Any)->str:return str(v or '').strip().upper().replace('-','/')
def cfg(p):
    capital=float(p.get('capital',0) or 0); pairs=[pair(x) for x in p.get('pairs',[]) if pair(x)]; alloc=[float(x) for x in p.get('allocations',[])]; tfs=[str(x).lower() for x in p.get('timeframes',[])] or ['3m']*len(pairs)
    if not 1<=len(pairs)<=10:raise HTTPException(400,'Можно выбрать от 1 до 10 пар')
    if len(alloc)!=len(pairs) or any(x<=0 for x in alloc) or sum(alloc)>100.0001:raise HTTPException(400,'Доли должны быть >0% и в сумме не превышать 100%')
    if capital<=0:raise HTTPException(400,'Бюджет должен быть больше 0 USDT')
    if len(tfs)!=len(pairs) or any(x not in {'1m','3m','5m'} for x in tfs):raise HTTPException(400,'Допустимые таймфреймы: 1m, 3m, 5m')
    return capital,pairs,alloc,tfs

def paper_report():
    s=paper_snapshot(); pos=list((s.get('open_positions') or {}).values())
    return {'mode':'PAPER','running':bool(s.get('running')),'started_at':s.get('started_at'),'stopped_at':s.get('stopped_at'),'initial_balance':float(s.get('initial_balance',0) or 0),'account_balance_usdt':float(s.get('account_balance_usdt',0) or 0),'free_usdt':float(s.get('free_usdt',0) or 0),'equity_usdt':float(s.get('equity_usdt',0) or 0),'realized_pnl':float(s.get('realized_pnl',0) or 0),'unrealized_pnl':float(s.get('unrealized_pnl',0) or 0),'net_pnl':float(s.get('net_pnl',0) or 0),'positions':pos,'open_positions':pos,'orders':list((s.get('orders') or {}).values()),'order_history':list(s.get('order_history') or [])[-50:],'trades':list(s.get('trades') or [])[-50:],'config':s.get('config') or {},'error':s.get('error')}

def live_report():
    try:s=json.loads(LIVE_STATE.read_text()) if LIVE_STATE.exists() else {}
    except Exception:s={}
    with LIVE_LOCK:r=bool(LIVE_PROC and LIVE_PROC.poll() is None)
    s['running']=r;s['mode']='LIVE';s.setdefault('positions',[]);s.setdefault('trades',[]);s.setdefault('orders',{});return s

@app.get('/api/health')
def health():return {'ok':True,'project':'Fast Scalper','workspace':'Fast Skalper','market_data':'Binance public WebSocket'}
@app.get('/api/recommendations')
def recommendations(limit:int=20):
    try:
        rows=RADAR.snapshot(max(10,min(int(limit),20)));return {'ok':True,'generated_at':time.time(),'data_source':'Binance WebSocket','rest_polling':False,'radar_error':RADAR.last_error,'radar_status':RADAR.status(),'candidates20':rows[:20],'top5':rows[:5]}
    except Exception as e:return {'ok':True,'generated_at':time.time(),'data_source':'Binance WebSocket','rest_polling':False,'radar_error':str(e)[:300],'candidates20':[],'top5':[]}
@app.post('/api/paper/start')
def paper_start(p:dict[str,Any]):return {'ok':True,**start_paper(p,gateway)}
@app.post('/api/paper/stop')
def paper_stop():return {'ok':True,**stop_paper(gateway)}
@app.post('/api/paper/emergency-stop')
def paper_emergency():return {'ok':True,**emergency_stop_paper(gateway)}
@app.get('/api/paper/status')
def paper_status():return paper_report()
@app.get('/api/session/report/{mode}')
def report(mode:str):
    if mode.upper()=='PAPER':return paper_report()
    if mode.upper()=='LIVE':return live_report()
    raise HTTPException(400,'Unknown mode')
@app.post('/api/live/start')
def live_start(p:dict[str,Any]):
    global LIVE_PROC
    capital,pairs,alloc,tfs=cfg(p);key=str(p.get('api_key','')).strip();secret=str(p.get('api_secret','')).strip()
    if not key or not secret:raise HTTPException(400,'Для LIVE нужны Binance API Key и Secret')
    with LIVE_LOCK:
        if LIVE_PROC and LIVE_PROC.poll() is None:raise HTTPException(409,'LIVE уже запущен')
    try:
        g=gateway('binance');g.exchange.apiKey=key;g.exchange.secret=secret;g.load_markets();b=g.exchange.fetch_balance();free=float((b.get('free') or {}).get('USDT') or 0)
        if capital>free+1e-9:raise HTTPException(400,f'Бюджет {capital:.4f} USDT превышает свободный USDT-баланс {free:.4f} USDT')
        for x in pairs:
            if x not in g.exchange.markets or not g.exchange.markets[x].get('spot'):raise HTTPException(400,f'Пара недоступна на Binance Spot: {x}')
    except HTTPException:raise
    except Exception as e:raise HTTPException(400,f'Binance preflight не пройден: {str(e)[:240]}')
    LIVE_CONTROL.write_text(json.dumps({'command':'RUN'}));env=os.environ.copy();env.update({'BINANCE_API_KEY':key,'BINANCE_API_SECRET':secret,'FAST_SCALPER_CAPITAL_USDT':str(capital),'FAST_SCALPER_PAIRS':','.join(pairs),'FAST_SCALPER_ALLOCATIONS':','.join(map(str,alloc)),'FAST_SCALPER_TIMEFRAMES':','.join(tfs),'FAST_SCALPER_LIVE':'true','LIVE_TRADING':'true','LIVE_TRADING_ARMED':'true','TRADING_MODE':'live','FAST_SCALPER_STATE_FILE':str(LIVE_STATE),'FAST_SCALPER_CONTROL_FILE':str(LIVE_CONTROL)})
    try:proc=subprocess.Popen([sys.executable,'-m','scripts.fast_scalper_3m'],cwd=os.getcwd(),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,text=True)
    except Exception as e:raise HTTPException(500,f'Не удалось запустить LIVE: {e}')
    with LIVE_LOCK:LIVE_PROC=proc
    return {'ok':True,'running':True,'mode':'LIVE','capital':capital,'pairs':pairs,'allocations':alloc,'timeframes':tfs}
@app.post('/api/live/stop')
def live_stop():
    global LIVE_PROC
    with LIVE_LOCK:proc=LIVE_PROC
    if proc and proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=8)
        except subprocess.TimeoutExpired:proc.kill()
    with LIVE_LOCK:LIVE_PROC=None
    return {'ok':True,'running':False}
@app.post('/api/live/emergency-stop')
def live_emergency():
    global LIVE_PROC
    LIVE_CONTROL.write_text(json.dumps({'command':'EMERGENCY_STOP'}));deadline=time.time()+10
    while time.time()<deadline:
        with LIVE_LOCK:proc=LIVE_PROC
        if not proc or proc.poll() is not None:break
        time.sleep(.25)
    with LIVE_LOCK:proc=LIVE_PROC
    if proc and proc.poll() is None:proc.terminate()
    with LIVE_LOCK:LIVE_PROC=None
    return {'ok':True,'running':False,'stop_type':'EMERGENCY_STOP'}

HTML=r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper</title><style>
*{box-sizing:border-box}body{margin:0;background:#08090a;color:#eee;font-family:Arial,system-ui,sans-serif}.wrap{max-width:760px;margin:auto;padding:14px 18px 40px}.card{border:1px solid #5b0b13;border-radius:20px;background:#090a0b;margin:12px 0;padding:12px}.title{color:#ff303b;font-weight:900;font-size:21px;margin:0 0 8px}.grid2,.top,.slots{display:grid;grid-template-columns:1fr 1fr;gap:8px}.mode{border:1px solid #541018;border-radius:14px;padding:8px;text-align:center}.label{font-weight:900}.switch{min-width:100px;border:1px solid #555;background:#1c1d20;color:#aaa;border-radius:22px;padding:8px 15px;font-weight:900;cursor:pointer}.switch.on{background:#0a8d40;border-color:#20ef76;color:#fff}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#777}.switch.on .dot{background:#2dff7c}.status{font-size:13px;color:#777;margin-top:4px}.status.on{color:#21ed71}.timer{font-size:22px;font-weight:900;margin-top:4px;font-variant-numeric:tabular-nums}.em{width:100%;border:0;border-radius:18px;background:#2b2c30;color:#eee;padding:8px;font-weight:900;margin-top:8px}.big{font-size:44px;font-weight:900;color:#ffb300}.balance{border:1px solid #7d5b00;border-radius:18px;padding:12px}.muted{color:#aaa}.row4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;border-top:1px solid #4b151a;margin-top:12px;padding-top:10px}.metric b{display:block}.metric small{color:#aaa}.pair,.pos,.slot{border:1px solid #53101a;border-radius:14px;padding:9px;background:#08090a}.rank{display:flex;justify-content:space-between;font-weight:900}.score{color:#65ef8a;border:1px solid #1d8d46;border-radius:6px;padding:2px 6px}.meta{display:grid;grid-template-columns:1fr 1fr;gap:3px;color:#aaa;font-size:11px}.price{color:#ff4050;font-weight:900}.green{color:#65ef8a}.pair button,.slot button{width:100%;border:1px solid #ffb300;background:#211804;color:#ffd04d;border-radius:8px;padding:7px;font-weight:900;margin-top:7px}.pair button.selected{background:#078b40;color:#fff}.controls{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.tf,.alloc button{border:1px solid #444;background:#191a1c;color:#bbb;border-radius:9px;padding:10px;font-weight:900}.tf.active,.alloc button.active{border-color:#ffb300;color:#ffd04d}.slot input,.slot select,.api input,#capital{width:100%;background:#151619;color:#eee;border:1px solid #4e1018;border-radius:8px;padding:9px;margin-bottom:6px}.alloc{display:flex;gap:7px}.alloc button{flex:1}.error{color:#ff5962}@media(max-width:560px){.row4{grid-template-columns:1fr 1fr}.big{font-size:39px}}
</style></head><body><div class="wrap">
<div class="card"><div class="title">⚡ УПРАВЛЕНИЕ БОТОМ</div><div class="grid2"><div class="mode"><div class="label">PAPER</div><button id="ps" class="switch" onclick="toggle('PAPER')"><span class="dot"></span> <b id="pl">OFF</b></button><div id="pst" class="status">PAPER остановлен</div><div id="pt" class="timer">00:00:00</div></div><div class="mode"><div class="label">LIVE</div><button id="ls" class="switch" onclick="toggle('LIVE')"><span class="dot"></span> <b id="ll">OFF</b></button><div id="lst" class="status">LIVE остановлен</div><div id="lt" class="timer">00:00:00</div></div></div><button class="em" onclick="emergency()">⛔ EMERGENCY STOP</button></div>
<div class="card"><div class="title">PnL СЕГОДНЯ / ACCUMULATED</div><div id="pnl" class="big">0.0000 USDT (0.00%)</div><div class="balance">💼 BALANCE ACCOUNT <b id="bal" style="font-size:25px;display:block">100.0000 USDT</b><span class="muted">Свободно: <span id="free">100.0000</span> • Нереализовано: <span id="unreal">0.0000</span></span><div class="row4"><div class="metric"><small>Realized</small><b id="real">0.0000</b></div><div class="metric"><small>Unrealized</small><b id="u2">0.0000</b></div><div class="metric"><small>Net</small><b id="net">0.0000</b></div><div class="metric"><small>Equity</small><b id="eq">100.0000</b></div></div></div></div>
<div class="card"><div class="title">📋 SESSION RESULT</div><div id="session">Нет активной сессии</div></div><div class="card"><div class="title">📜 ПОСЛЕДНИЕ ЗАКРЫТЫЕ СДЕЛКИ</div><div id="trades">Нет сделок</div></div><div class="card"><div class="title">🚀 ТОП ПАРЫ · РЕЙТИНГ СИГНАЛОВ</div><div id="radar" class="muted">Подключение радара…</div><div id="top" class="top"></div></div><div class="card"><div class="title">🔴 ОТКРЫТЫЕ ПОЗИЦИИ</div><div id="positions">Нет открытых позиций</div></div>
<div class="card"><div class="title">⚙ РЕЖИМ РАБОТЫ</div><div class="controls"><button class="tf active" data-tf="3m" onclick="defTf('3m')">3m</button><button class="tf" data-tf="1m" onclick="defTf('1m')">1m</button><button class="tf" data-tf="5m" onclick="defTf('5m')">5m</button></div></div><div class="card"><div class="title">⚙ НАСТРОЙКИ СЕССИИ</div><input id="capital" value="100" type="number" min="0.01" step="0.01"><div class="alloc"><button id="ab" class="active" onclick="allocMode('AUTO')">АВТОРАСПРЕДЕЛЕНИЕ</button><button id="mb" onclick="allocMode('MANUAL')">ВРУЧНУЮ</button></div><div id="slots" class="slots"></div><div id="total" class="muted">ВСЕГО 0%</div><div class="api"><input id="key" placeholder="Binance API Key"><input id="secret" placeholder="Binance Secret Key" type="password"></div></div>
</div><script>
const K='fsCleanSlots',R='fsCleanRank';let slots=JSON.parse(localStorage.getItem(K)||'[]');while(slots.length<10)slots.push({p:'',v:0,tf:'3m'});let mode='AUTO',dTf='3m',rank=JSON.parse(localStorage.getItem(R)||'[]'),sess={PAPER:{run:false,t:0},LIVE:{run:false,t:0}},busy=false;$=x=>document.getElementById(x);esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));ts=x=>{if(typeof x==='number')return x<1e12?x*1000:x;let n=Number(x);if(Number.isFinite(n)&&n)return n<1e12?n*1000:n;let d=Date.parse(x);return Number.isFinite(d)?d:0};fmt=x=>{x=Math.max(0,Math.floor(x));return [Math.floor(x/3600),Math.floor(x%3600/60),x%60].map(v=>String(v).padStart(2,'0')).join(':')};price=x=>x==null?'—':Number(x).toPrecision(9);save=()=>localStorage.setItem(K,JSON.stringify(slots));sel=()=>slots.filter(x=>x.p);
function drawSlots(){$('slots').innerHTML=slots.map((x,i)=>`<div class=slot><input value="${esc(x.p)}" placeholder="ПАРА ${i+1}" onchange="sp(${i},this.value)"><select onchange="st(${i},this.value)"><option ${x.tf==='1m'?'selected':''}>1m</option><option ${x.tf==='3m'?'selected':''}>3m</option><option ${x.tf==='5m'?'selected':''}>5m</option></select><input type=number min=0 max=100 step=.01 value="${x.v||0}" onchange="sv(${i},this.value)"><button onclick="cl(${i})">ОЧИСТИТЬ</button></div>`).join('');$('total').textContent='ВСЕГО '+sel().reduce((a,x)=>a+Number(x.v||0),0).toFixed(2)+'%'}
function sp(i,v){slots[i].p=v.trim().toUpperCase().replace('-','/');save();drawSlots()}function st(i,v){slots[i].tf=v;save()}function sv(i,v){slots[i].v=Math.max(0,Number(v)||0);if(mode==='AUTO'){let a=sel(),e=100/Math.max(1,a.length);a.forEach(x=>x.v=Math.round(e*100)/100)}save();drawSlots()}function cl(i){slots[i]={p:'',v:0,tf:dTf};save();drawSlots()}function defTf(v){dTf=v;document.querySelectorAll('.tf').forEach(x=>x.classList.toggle('active',x.dataset.tf===v))}function allocMode(v){mode=v;$('ab').classList.toggle('active',v==='AUTO');$('mb').classList.toggle('active',v==='MANUAL');if(v==='AUTO'&&sel().length){let e=100/sel().length;sel().forEach(x=>x.v=Math.round(e*100)/100);save();drawSlots()}}
function rankDraw(rows){if(rows?.length){rank=rows;localStorage.setItem(R,JSON.stringify(rank))}$('radar').textContent=rank.length?'Binance WebSocket • рейтинг сохраняется':'Радар подключается…';$('top').innerHTML=rank.slice(0,10).map((x,i)=>`<div class=pair><div class=rank><span>🔥 #${i+1} ${esc(x.symbol)}</span><span class=score>${Number(x.score||0).toFixed(0)}</span></div><div class=meta><span>Hot ${Number(x.hot_market_score||0).toFixed(0)}</span><span>Flow ${(Number(x.buy_ratio||.5)*100).toFixed(0)}%</span><span>1–3m ${Number(x.change_3m_pct||0).toFixed(3)}%</span><span>$/мин/$100 <b class=green>$${Number(x.expected_pnl_per_min_100||0).toFixed(2)}</b></span></div><div class=price>${price(x.price)}</div><div class=muted>Вход ${price(x.estimated_entry)} → выход ${price(x.estimated_exit)} • SL ${price(x.estimated_stop)}</div><button data-s="${esc(x.symbol)}" onclick="choose('${esc(x.symbol)}')">ВЫБРАТЬ</button></div>`).join('');document.querySelectorAll('[data-s]').forEach(b=>{let y=sel().some(x=>x.p===b.dataset.s);b.classList.toggle('selected',y);b.textContent=y?'✓ ВЫБРАНО':'ВЫБРАТЬ'})}
function choose(s){let x=slots.find(x=>x.p===s);if(x){x.p='';x.v=0}else{let i=slots.findIndex(x=>!x.p);if(i<0)return alert('Все 10 слотов заняты');slots[i]={p:s,v:0,tf:dTf}}if(mode==='AUTO'&&sel().length){let e=100/sel().length;sel().forEach(x=>x.v=Math.round(e*100)/100)}save();drawSlots();rankDraw()}
function m(mode,d){let run=!!d.running,b=$(mode==='PAPER'?'ps':'ls'),l=$(mode==='PAPER'?'pl':'ll'),s=$(mode==='PAPER'?'pst':'lst');b.classList.toggle('on',run);l.textContent=run?'ON':'OFF';s.className='status '+(run?'on':'');s.textContent=run?mode+': РАБОТАЕТ':mode+' остановлен';if(run){let t=ts(d.started_at);if(t&&(!sess[mode].run||Math.abs(t-sess[mode].t)>1500))sess[mode].t=t;sess[mode].run=true}else{sess[mode].run=false;sess[mode].t=0}$((mode==='PAPER'?'pt':'lt')).textContent=fmt(sess[mode].run?(Date.now()-sess[mode].t)/1000:0)}
function paper(d){let n=Number(d.net_pnl||0),c=Number(d.initial_balance||0),pct=c?n/c*100:0;$('bal').textContent=Number(d.account_balance_usdt||0).toFixed(4)+' USDT';$('free').textContent=Number(d.free_usdt||0).toFixed(4);$('unreal').textContent=Number(d.unrealized_pnl||0).toFixed(4);$('real').textContent=Number(d.realized_pnl||0).toFixed(4);$('u2').textContent=Number(d.unrealized_pnl||0).toFixed(4);$('net').textContent=n.toFixed(4);$('eq').textContent=Number(d.equity_usdt||c).toFixed(4);$('pnl').textContent=n.toFixed(4)+' USDT ('+pct.toFixed(2)+'%)';let p=d.positions||[];$('positions').innerHTML=p.length?p.map(x=>`<div class=pos><b>${esc(x.symbol)}</b> • ${x.timeframe||'3m'} • ${x.signal||''}<br>Вход ${price(x.entry_price)} • Сейчас ${price(x.current_price)} • PnL ${Number(x.unrealized_pnl||0).toFixed(4)} USDT • ${Math.floor(Number(x.age_sec||0))} сек.</div>`).join(''):'Нет открытых позиций';let tr=d.trades||[];$('trades').innerHTML=tr.length?tr.slice(-5).reverse().map(x=>`<div class=pos><b>${esc(x.symbol)}</b> • ${Number(x.net_pnl||0)>=0?'+':''}${Number(x.net_pnl||0).toFixed(4)} USDT • ${esc(x.reason||'')}</div>`).join(''):'Нет сделок';$('session').textContent=d.running?'Активна • старт '+new Date(ts(d.started_at)).toLocaleTimeString():'Нет активной сессии'}
async function refresh(){if(busy)return;busy=true;try{let [p,r,l]=await Promise.all([fetch('/api/session/report/PAPER',{cache:'no-store'}),fetch('/api/recommendations?limit=20',{cache:'no-store'}),fetch('/api/session/report/LIVE',{cache:'no-store'})]);let pd=await p.json(),rd=await r.json(),ld=await l.json();m('PAPER',pd);m('LIVE',ld);paper(pd);if(rd.candidates20?.length)rankDraw(rd.candidates20);else rankDraw()}catch(e){}busy=false}
async function toggle(md){try{let rr=await fetch('/api/session/report/'+md,{cache:'no-store'}),d=await rr.json();if(d.running){await fetch('/api/'+md.toLowerCase()+'/stop',{method:'POST'})}else{let a=sel();if(!a.length)return alert('Выбери хотя бы одну пару');let c=Number($('capital').value||0),al=a.map(x=>Number(x.v||0)),pa=a.map(x=>x.p),tf=a.map(x=>x.tf);if(Math.abs(al.reduce((x,y)=>x+y,0)-100)>.01)return alert('Распредели ровно 100%');let body={capital:c,pairs:pa,allocations:al,timeframes:tf};if(md==='LIVE'){body.api_key=$('key').value;body.api_secret=$('secret').value}let res=await fetch('/api/'+md.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!res.ok){let z=await res.json();return alert(z.detail||'Ошибка запуска')}}await refresh()}catch(e){alert(e.message)}}
async function emergency(){await fetch('/api/paper/emergency-stop',{method:'POST'});await fetch('/api/live/emergency-stop',{method:'POST'});await refresh()}
drawSlots();rankDraw();refresh();setInterval(refresh,1000);setInterval(()=>{for(let md of ['PAPER','LIVE'])if(sess[md].run&&sess[md].t)$($(md==='PAPER'?'pt':'lt')).textContent=fmt((Date.now()-sess[md].t)/1000)},250);
</script></body></html>'''
@app.get('/',response_class=HTMLResponse)
def root():return HTMLResponse(HTML,headers={'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0','Pragma':'no-cache','Expires':'0'})
