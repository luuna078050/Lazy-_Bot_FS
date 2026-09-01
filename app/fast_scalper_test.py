from __future__ import annotations
import json, os, subprocess, sys, threading, time
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from .exchange_gateway import gateway
from .market_radar import RADAR
from .profit_first_engine_v4 import start_paper, stop_paper, emergency_stop_paper, snapshot as paper_snapshot
from . import profit_first_engine_v3 as base
from . import fixed_app as live_core

app=FastAPI(title='Fast Scalper',version='test-6slots')
LIVE_PROC=None; LIVE_LOCK=threading.Lock(); LIVE_STATE=live_core.LIVE_STATE; LIVE_CONTROL=live_core.LIVE_CONTROL
CAPITAL=300.0; SLOT_COUNT=6

def pair(v:Any)->str:return str(v or '').strip().upper().replace('-','/').replace('_','/')
def report():
 s=paper_snapshot(); pos=list((s.get('open_positions') or {}).values()); return {**s,'running':bool(s.get('running')),'positions':pos,'open_positions':pos,'orders':list((s.get('orders') or {}).values()),'trades':list(s.get('trades') or [])[-50:],'order_history':list(s.get('order_history') or [])[-50:],'account_balance_usdt':float(s.get('account_balance_usdt',CAPITAL) or 0),'bot_balance_usdt':CAPITAL,'free_usdt':float(s.get('free_usdt',0) or 0),'reinvest':True}

def validate(p):
 pairs=[pair(x) for x in p.get('pairs',[]) if pair(x)]; amounts=[float(x) for x in p.get('amounts',[])]; tf=str(p.get('timeframe','3m')).lower(); profit=float(p.get('profit_target_pct',.30) or .30)
 if not 1<=len(pairs)<=SLOT_COUNT:raise HTTPException(400,f'Выберите от 1 до {SLOT_COUNT} пар')
 if len(amounts)!=len(pairs) or any(x<=0 for x in amounts):raise HTTPException(400,'Сумма позиции должна быть больше 0 USDT')
 if sum(amounts)>CAPITAL+1e-9:raise HTTPException(400,f'Сумма слотов {sum(amounts):.2f} превышает 300 USDT')
 if tf not in {'1m','3m'}:raise HTTPException(400,'Таймфрейм сделки: 1m или 3m')
 if profit<=0 or profit>100:raise HTTPException(400,'Profit / Trade должен быть больше 0%')
 return pairs,amounts,[x/CAPITAL*100 for x in amounts],tf,profit

@app.get('/api/health')
def health():return {'ok':True,'project':'Fast Scalper','engine':'paper','radar':'websocket','rest_market_data':False,'slots':6}
@app.get('/api/recommendations')
def recommendations(limit:int=15):
 try:
  rows=RADAR.snapshot(max(6,min(limit,15)));return {'ok':True,'data_source':'Binance WebSocket','rest_polling':False,'radar_status':RADAR.status(),'top8':rows[:8],'top15':rows[:15]}
 except Exception as e:return {'ok':False,'radar_error':str(e)[:300],'radar_status':RADAR.status(),'top8':[],'top15':[]}
@app.get('/api/paper/status')
def paper_status():return report()
@app.post('/api/paper/start')
def paper_start(p:dict[str,Any]):
 pairs,amounts,alloc,tf,profit=validate(p); cfg=dict(p); cfg.update({'capital':CAPITAL,'pairs':pairs,'amounts':amounts,'allocations':alloc,'timeframes':[tf]*len(pairs),'profit_target_pct':profit,'fee_pct':float(p.get('fee_pct',.10)),'reinvest':True}); out=start_paper(cfg,gateway); base.STATE['config']['profit_target_pct']=profit; base.STATE['config']['reinvest']=True; base.STATE['config']['amounts']=amounts; return {'ok':True,**out}
@app.post('/api/paper/stop')
def paper_stop():return {'ok':True,**stop_paper(gateway)}
@app.post('/api/paper/emergency-stop')
def paper_emergency():return {'ok':True,**emergency_stop_paper(gateway)}
@app.post('/api/paper/reset')
def paper_reset():
 try:stop_paper(gateway)
 except Exception:pass
 return {'ok':True,'reset':True}
@app.get('/api/session/report/{mode}')
def session_report(mode:str):return report() if mode.upper()=='PAPER' else {'mode':'LIVE','running':False}

HTML=r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Cache-Control" content="no-store"><title>Fast Scalper</title><style>
:root{--bg:#070b14;--panel:#111a2d;--line:#2a3a59;--muted:#8e9bb5;--green:#18d887;--red:#ff536b;--gold:#ffc34b}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f4f6fb;font:14px/1.35 system-ui,-apple-system,Roboto,sans-serif}.app{max-width:760px;margin:auto;padding:10px 18px 30px}.card{background:var(--panel);border:1px solid var(--line);border-radius:22px;padding:16px;margin:12px 0}.title{font-size:18px;font-weight:950;margin-bottom:10px}.muted{color:var(--muted)}.top{display:flex;justify-content:space-between;align-items:center}.metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric{background:#0b1325;border-radius:13px;padding:11px}.metric small{display:block;color:var(--muted)}.metric b{font-size:19px}.controls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:9px}.btn{border:1px solid #405172;background:#263b60;color:#fff;border-radius:13px;padding:13px;font-weight:950}.on{background:#07974d;border-color:#20e58b}.danger{background:#ae2e43;border-color:#d95a6b}.session{font-weight:900;margin-top:8px}.pnl{font-size:26px;font-weight:950;color:var(--gold)}.slots{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.slot{background:#0b1325;border:1px solid #30415f;border-radius:15px;padding:10px}.slot.selected{border-color:var(--green);box-shadow:0 0 0 1px #18d88755}.slotHead{display:flex;justify-content:space-between;color:var(--muted);font-size:12px}.slotPair{font-size:17px;font-weight:950;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.slotAmount{width:100%;margin-top:8px;background:#091225;color:#fff;border:1px solid #334665;border-radius:9px;padding:9px}.profit{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:center;margin-top:12px}.profit input{width:100%;background:#091225;color:#fff;border:1px solid #334665;border-radius:9px;padding:10px}.radar{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.cand{border:1px solid #2d3e5d;border-radius:13px;padding:10px;background:#0b1325;cursor:pointer}.score{background:#078d55;border-radius:8px;padding:4px 7px;font-weight:950}.sym{font-weight:950;font-size:16px}.quote{font-size:11px;margin-top:5px}.buy{color:var(--green);font-weight:900}.wait{color:var(--muted);font-weight:900}.pick{width:100%;margin-top:7px;background:#253b5e;color:#fff;border:0;border-radius:9px;padding:7px;font-weight:900}.pos{border:1px solid #1f704c;background:#0b1a15;border-radius:13px;padding:10px}.closed{display:flex;justify-content:space-between;border-bottom:1px solid #24324c;padding:8px 0}.good{color:var(--green)}.bad{color:var(--red)}details summary{cursor:pointer;font-weight:900}.api input{width:100%;margin-top:7px;background:#091225;color:#fff;border:1px solid #334665;border-radius:9px;padding:9px}@media(max-width:560px){.app{padding:8px 10px 25px}.slots{grid-template-columns:repeat(2,1fr)}.radar{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main class="app">
<div class="card"><div class="top"><div class="title">⚡ FAST SCALPER</div><span class="muted" id="feed">WebSocket · PAPER</span></div><div class="metrics"><div class="metric"><small>Account Balance</small><b id="account">300.0000 USDT</b></div><div class="metric"><small>Realized PnL</small><b id="real">0.0000 USDT</b></div><div class="metric"><small>Unrealized PnL</small><b id="unreal">0.0000 USDT</b></div><div class="metric"><small>Net PnL</small><b id="net">0.0000 USDT</b></div></div><div class="metric" style="margin-top:8px"><small>Free Balance / Bot Balance · Reinvest</small><b><span id="free">300.0000</span> / <span id="bot">300.0000</span> USDT · ON</b></div></div>
<div class="card"><div class="controls"><button id="paper" class="btn on">PAPER ON</button><button id="emergency" class="btn danger">EMERGENCY STOP</button><button id="reset" class="btn">RESET</button></div><div class="session"><span id="engine">Engine OFF</span> · Session <span id="timer">00:00:00</span></div></div>
<div class="card"><div class="top"><div class="title">Open Positions</div><span class="muted" id="openCount">0</span></div><div id="positions">No open positions</div></div>
<div class="card"><div class="title">Session Result</div><div class="metrics"><div class="metric"><small>Trades</small><b id="trades">0</b></div><div class="metric"><small>Open</small><b id="orders">0</b></div><div class="metric"><small>Cycle</small><b id="cycle">0</b></div><div class="metric"><small>Profit / Trade</small><b id="profitShow">0.30%</b></div></div></div>
<div class="card"><div class="top"><div class="title">6 Active Slots</div><span class="muted">3×2 · selected pairs trade</span></div><div class="slots" id="slots"></div><div class="profit"><span>Profit / Trade %</span><input id="profit" type="number" min="0.01" step="0.01" value="0.30"></div><div class="muted" style="margin-top:8px;font-size:12px">Одна общая цель применяется ко всем занятым слотам. После закрытия сделки пара остаётся в своём слоте.</div></div>
<div class="card"><div class="top"><div class="title">Top Pairs — Signal Rating</div><span class="muted" id="radarAge">radar connecting</span></div><div id="radar" class="radar">Загрузка радара…</div><label style="display:block;margin-top:10px;font-weight:900"><input id="top15" type="checkbox"> Показать полный TOP-15</label><div id="error" class="bad"></div></div>
<div class="card"><div class="title">Closed Trades — latest 5</div><div id="closed">No closed trades</div></div>
<div class="card api"><details><summary>▶ ▶ Binance API</summary><input id="key" placeholder="API Key"><input id="secret" placeholder="API Secret" type="password"></details></div>
<div class="card"><div class="top"><span class="muted">Trade TF</span><div class="controls" style="width:210px"><button id="tf3" class="btn on" style="padding:8px">3m</button><button id="tf1" class="btn" style="padding:8px">1m</button><button class="btn" style="padding:8px">default</button></div></div><div class="muted" style="margin-top:8px;font-size:12px">По умолчанию 3 минуты. Один таймфрейм сделки применяется ко всем слотам.</div></div>
</main><script>
const N=6,$=x=>document.getElementById(x);let slots=Array.from({length:N},()=>({pair:'',amount:50})),tf='3m',running=false,started=0,rows=[],cycle=0;
function esc(x){return String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}
function renderSlots(){$('slots').innerHTML=slots.map((s,i)=>`<div class="slot ${s.pair?'selected':''}"><div class="slotHead"><span>SLOT ${i+1}</span><span>${s.pair?'✓':''}</span></div><div class="slotPair">${s.pair?esc(s.pair):'EMPTY'}</div>${s.pair?`<input class="slotAmount" type="number" min="1" step="1" value="${s.amount}" onchange="slots[${i}].amount=Number(this.value)||1">`:''}</div>`).join('')}
function choose(p){p=p.toUpperCase();if(slots.some(x=>x.pair===p))return;let i=slots.findIndex(x=>!x.pair);if(i<0){$('error').textContent='Все 6 слотов заняты';return}slots[i].pair=p;renderSlots()}
function viewRows(){return $('top15').checked?rows.slice(0,15):rows.slice(0,6)}
function renderRadar(){let v=viewRows();$('radar').innerHTML=v.map((r,i)=>{let p=r.symbol||'',bid=Number(r.bid||0),ask=Number(r.ask||0),last=Number(r.price||0),sig=r.direction==='LONG'?'BUY':'WAIT';return `<div class="cand" onclick="choose('${esc(p)}')"><div class="top"><span class="sym">${i+1}. ${esc(p)}</span><span class="score">${Number(r.score||0).toFixed(1)}</span></div><div class="quote">BUY ${bid?bid.toPrecision(9):'—'} · SELL ${ask?ask.toPrecision(9):'—'}</div><div class="quote">Last ${last?last.toPrecision(9):'—'} · 24h ${Number(r.change_24h_pct||0).toFixed(2)}%</div><div class="${sig==='BUY'?'buy':'wait'}">${sig} · нажмите для выбора</div><button class="pick" onclick="event.stopPropagation();choose('${esc(p)}')">＋ SLOT</button></div>`}).join('')||'Нет данных'}
async function radar(){try{let d=await (await fetch('/api/recommendations?limit=15',{cache:'no-store'})).json();rows=d.top15||[];renderRadar();let s=d.radar_status||{};$('radarAge').textContent=s.connected?'radar live · '+Number(s.seconds_since_update||0).toFixed(0)+'s':'radar connecting';$('error').textContent=d.radar_error||s.last_error||''}catch(e){$('error').textContent=String(e)}}
$('top15').onchange=renderRadar;
function setTF(v){tf=v;$('tf3').classList.toggle('on',v==='3m');$('tf1').classList.toggle('on',v==='1m')}$('tf3').onclick=()=>setTF('3m');$('tf1').onclick=()=>setTF('1m');
async function start(){let s=slots.filter(x=>x.pair);if(!s.length){$('error').textContent='Сначала выберите пару из радара';return}let amounts=s.map(x=>x.amount),sum=amounts.reduce((a,b)=>a+b,0);if(sum>300){$('error').textContent='Сумма слотов больше 300 USDT';return}let d=await (await fetch('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pairs:s.map(x=>x.pair),amounts,timeframe:tf,profit_target_pct:Number($('profit').value)||.30,reinvest:true})})).json();if(!d.ok){$('error').textContent=d.detail||'Ошибка запуска';return}running=true;started=Date.now();$('paper').textContent='PAPER ON'}
async function stop(){await fetch('/api/paper/stop',{method:'POST'});running=false}async function emergency(){await fetch('/api/paper/emergency-stop',{method:'POST'});running=false}$('paper').onclick=()=>running?stop():start();$('emergency').onclick=emergency;$('reset').onclick=async()=>{await stop();slots=Array.from({length:N},()=>({pair:'',amount:50}));renderSlots();$('profit').value='.30'};
async function state(){try{let d=await (await fetch('/api/paper/status',{cache:'no-store'})).json();running=!!d.running;if(running&&!started)started=Date.now();$('engine').textContent=running?'Engine ON':'Engine OFF';$('account').textContent=Number(d.account_balance_usdt||300).toFixed(4)+' USDT';$('free').textContent=Number(d.free_usdt||0).toFixed(4);$('bot').textContent=Number(d.bot_balance_usdt||300).toFixed(4);$('real').textContent=Number(d.realized_pnl||0).toFixed(4)+' USDT';$('unreal').textContent=Number(d.unrealized_pnl||0).toFixed(4)+' USDT';$('net').textContent=Number(d.net_pnl||0).toFixed(4)+' USDT';$('trades').textContent=(d.trades||[]).length;$('orders').textContent=(d.orders||[]).length;cycle=Number(d.cycle||cycle);$('cycle').textContent=cycle;let pt=Number((d.config||{}).profit_target_pct||$('profit').value||.30);$('profitShow').textContent=pt.toFixed(2)+'%';let p=d.positions||[];$('openCount').textContent=p.length;$('positions').innerHTML=p.length?p.map(x=>`<div class="pos"><b>${esc(x.symbol)}</b><div class="metrics" style="margin-top:7px"><div class="metric"><small>Entry</small><b>${Number(x.entry_price).toPrecision(9)}</b></div><div class="metric"><small>Now</small><b>${Number(x.current_price||x.entry_price).toPrecision(9)}</b></div><div class="metric"><small>PnL</small><b class="${Number(x.unrealized_pnl||0)>=0?'good':'bad'}">${Number(x.unrealized_pnl||0).toFixed(4)}</b></div></div></div>`).join(''):'No open positions';let t=(d.trades||[]).slice(-5).reverse();$('closed').innerHTML=t.length?t.map(x=>`<div class="closed"><span>${esc(x.symbol)} · ${esc(x.reason||'CLOSED')}</span><b class="${Number(x.net_pnl||0)>=0?'good':'bad'}">${Number(x.net_pnl||0).toFixed(4)} USDT</b></div>`).join(''):'No closed trades'}catch(e){$('error').textContent=String(e)}}
setInterval(radar,5000);setInterval(state,1000);setInterval(()=>{if(running&&started){let z=Math.floor((Date.now()-started)/1000),h=Math.floor(z/3600),m=Math.floor(z%3600/60),s=z%60;$('timer').textContent=[h,m,s].map(x=>String(x).padStart(2,'0')).join(':')}},500);renderSlots();radar();state();
</script></body></html>'''

@app.get('/',response_class=HTMLResponse)
def root():return HTMLResponse(HTML)
