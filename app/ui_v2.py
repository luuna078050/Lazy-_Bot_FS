from fastapi.responses import HTMLResponse
from .fixed_app import app

for r in list(app.router.routes):
    if getattr(r, 'path', None) == '/' and getattr(r, 'methods', None) and 'GET' in r.methods:
        app.router.routes.remove(r)

HTML = r'''<!doctype html>
<html lang="ru">
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fast Scalper</title>
<style>
:root{--bg:#101827;--card:#202b3b;--field:#3a4658;--muted:#aeb8c7;--blue:#2563eb;--green:#16a34a;--red:#dc2626;--gold:#f5c542;--line:#394659}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:#fff;max-width:820px;margin:auto;padding:10px}.card{background:var(--card);border-radius:18px;padding:14px;margin:10px 0}button,input{border:0;border-radius:10px;padding:11px;font-size:15px}input{background:var(--field);color:#fff;border:1px solid #59677a;width:100%}button{font-weight:800;cursor:pointer;transition:.12s transform,.12s filter}.tap:active{transform:scale(.95);filter:brightness(1.18)}.two{display:grid;grid-template-columns:1fr 1fr;gap:7px}.paper{background:var(--blue);color:#fff}.live{background:var(--green);color:#fff}.stop{background:var(--red);color:#fff}.em{background:#7f1d1d;color:#fff}.ghost{background:#475569;color:#fff;width:100%}.muted{color:var(--muted);font-size:13px}.runbox{border:1px solid var(--line);border-radius:14px;padding:10px}.runbox h4{margin:0 0 6px}.status{font-size:13px;margin:6px 0}.timer{font-variant-numeric:tabular-nums;font-size:20px;font-weight:900;letter-spacing:.5px}.session{font-size:12px;color:var(--muted);min-height:17px}.slot{display:grid;grid-template-columns:66px 1fr 70px;gap:6px;margin:8px 0;align-items:start}.clear{background:#475569;color:#fff;font-size:10px;min-height:48px}.alloc{min-height:48px;text-align:center}.modes{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:4px}.mode{background:#526174;color:#fff}.mode.active{box-shadow:0 0 0 3px var(--gold) inset,0 0 0 1px #fff;transform:scale(1.02)}.amount{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:4px}.amount label{font-size:11px;color:var(--muted);display:flex;align-items:center;gap:5px}.amount input[type=checkbox]{width:21px;height:21px;accent-color:var(--gold);padding:0}.rec{border-bottom:1px solid var(--line);padding:8px 0}.recrow{display:grid;grid-template-columns:1fr auto auto;gap:5px;align-items:center}.line{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px}.line b{font-size:14px}.pick{background:#475569;color:#fff;min-width:80px}.pick.selected{background:var(--gold);color:#111;box-shadow:0 0 0 2px #fff inset}.arrow{background:transparent;color:#fff;font-size:18px;padding:3px}.details{display:none;color:var(--muted);font-size:12px;padding:5px 0}.details.open{display:block}.result{font-size:13px;border-bottom:1px solid var(--line);padding:7px 0}@media(max-width:520px){.slot{grid-template-columns:58px 1fr 62px}.line{font-size:12px}}
</style>
</head>
<body>
<h2>⚡ Fast Scalper</h2>
<p class="muted">Binance Spot • WebSocket radar • PAPER и LIVE независимы</p>

<div class="card">
<b>Запуск</b>
<div class="two" style="margin-top:8px">
  <div class="runbox">
    <h4>PAPER</h4>
    <button class="paper tap" onclick="run('PAPER')">▶ ЗАПУСТИТЬ PAPER</button>
    <button class="stop tap" onclick="stopMode('PAPER')">■ STOP PAPER</button>
    <div id="paperStatus" class="status">⚪ PAPER: остановлен</div>
    <div id="paperTimer" class="timer">00:00:00</div>
    <div id="paperSession" class="session"></div>
  </div>
  <div class="runbox">
    <h4>LIVE</h4>
    <button class="live tap" onclick="run('LIVE')">▶ ЗАПУСТИТЬ LIVE</button>
    <button class="stop tap" onclick="stopMode('LIVE')">■ STOP LIVE</button>
    <button class="em tap" onclick="stopMode('LIVE',true)">⛔ EMERGENCY STOP</button>
    <div id="liveStatus" class="status">⚪ LIVE: остановлен</div>
    <div id="liveTimer" class="timer">00:00:00</div>
    <div id="liveSession" class="session"></div>
  </div>
</div>
<p class="muted">PAPER и LIVE запускаются и останавливаются независимо. Каждый режим имеет собственный таймер сессии.</p>
</div>

<div class="card"><b>Binance API для LIVE</b><input id="key" placeholder="API Key" autocomplete="off"><input id="secret" type="password" placeholder="Secret Key" autocomplete="off"><p class="muted">Ключи только для текущего LIVE-процесса. Withdrawals не используются. Для LIVE — Spot Trading + IP restriction.</p></div>
<div class="card"><b>Бюджет</b><input id="capital" type="number" value="30" min="0.01" step="0.01"><span class="muted"> USDT</span></div>

<div class="card">
<b>5 выбранных пар</b>
<p class="muted">PAPER/LIVE у каждой строки видны постоянно. Доля 0–100%. Объём по умолчанию выключен.</p>
<div id="slots"></div>
</div>

<!-- Top-5 intentionally placed before the long candidate list. -->
<div class="card"><b>Топ-5 Fast Scalper</b><div id="top5">Загрузка…</div></div>

<div class="card"><b>20 кандидатов</b><button class="ghost tap" onclick="recs()">↻ ОБНОВИТЬ СПИСОК</button><div id="r">Загрузка WebSocket-данных…</div></div>

<div class="card"><b>Session Result</b><div id="res">Нет активных сессий</div></div>

<script>
let slots=Array.from({length:5},()=>({p:'',a:0,mode:'PAPER',use:false,amount:0}));
const sessions={PAPER:{start:null,stop:null,elapsed:0,running:false},LIVE:{start:null,stop:null,elapsed:0,running:false}};
const esc=s=>String(s||'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const pad=n=>String(n).padStart(2,'0');
function fmtTime(ms){let sec=Math.max(0,Math.floor(ms/1000)),h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;return `${pad(h)}:${pad(m)}:${pad(s)}`}
function clockText(ts){return ts?new Date(ts).toLocaleTimeString('ru-RU'):'—'}
function saveSessions(){localStorage.setItem('fastScalperSessions',JSON.stringify(sessions))}
function loadSessions(){try{let x=JSON.parse(localStorage.getItem('fastScalperSessions')||'{}');for(const m of ['PAPER','LIVE'])if(x[m])Object.assign(sessions[m],x[m]);}catch(e){}}
function render(){document.getElementById('slots').innerHTML=slots.map((x,i)=>`<div class="slot"><button class="clear tap" onclick="clr(${i})">${i===0?'ОЧИСТИТЬ ВСЁ':'ОЧИСТИТЬ'}</button><div><input value="${esc(x.p)}" placeholder="Пара ${i+1}" oninput="slots[${i}].p=this.value.trim().toUpperCase().replace('-', '/')"><div class="modes"><button class="mode ${x.mode==='PAPER'?'active':''} tap" onclick="mode(${i},'PAPER')">PAPER</button><button class="mode ${x.mode==='LIVE'?'active':''} tap" onclick="mode(${i},'LIVE')">LIVE</button></div><div class="amount"><label><input type="checkbox" ${x.use?'checked':''} onchange="slots[${i}].use=this.checked"> учитывать объём</label><input type="number" min="0" step="0.0001" value="${x.amount}" placeholder="объём ордера" oninput="slots[${i}].amount=+this.value"></div></div><input class="alloc" type="number" min="0" max="100" step="0.01" value="${x.a}" oninput="slots[${i}].a=+this.value"></div>`).join('')}
function clr(i){if(i===0)slots=Array.from({length:5},()=>({p:'',a:0,mode:'PAPER',use:false,amount:0}));else slots[i]={p:'',a:0,mode:'PAPER',use:false,amount:0};render()}
function mode(i,m){slots[i].mode=m;render()}
function selectPair(s,b){let i=slots.findIndex(x=>!x.p);if(i<0){alert('Все 5 строк заняты. Нажми ОЧИСТИТЬ нужной строки.');return}slots[i].p=s;render();b.classList.add('selected');b.textContent='✓ ВЫБРАНО';setTimeout(()=>{b.classList.remove('selected');b.textContent='ВЫБРАТЬ'},900)}
function group(m){return slots.filter(x=>x.p&&x.mode===m)}
function cfg(m){let x=group(m);return {capital:+capital.value,pairs:x.map(v=>v.p),allocations:x.map(v=>v.a),target_usdt:.30,min_usdt:.20,sl_pct:.5,max_hold:180,fee_pct:.1}}
function beginSession(m){let s=sessions[m];if(!s.running){s.start=Date.now();s.stop=null;s.elapsed=0;s.running=true;s.sessionShown=false;saveSessions()}}
function finishSession(m){let s=sessions[m];if(s.running){s.elapsed=Math.max(0,Date.now()-s.start);s.stop=Date.now();s.running=false;saveSessions()}}
function drawSessions(){for(const m of ['PAPER','LIVE']){let s=sessions[m],elapsed=s.running?Date.now()-s.start:s.elapsed;document.getElementById(m==='PAPER'?'paperTimer':'liveTimer').textContent=fmtTime(elapsed);document.getElementById(m==='PAPER'?'paperStatus':'liveStatus').textContent=s.running?'🟢 '+m+': работает':'⚪ '+m+': остановлен';document.getElementById(m==='PAPER'?'paperSession':'liveSession').textContent=s.stop?`Старт ${clockText(s.start)} • стоп ${clockText(s.stop)} • сессия ${fmtTime(s.elapsed)}`:(s.running?`Старт ${clockText(s.start)} • идёт ${fmtTime(elapsed)}`:'');}}
async function run(m){let c=cfg(m),sum=c.allocations.reduce((a,b)=>a+b,0);if(!c.pairs.length){alert('Нет выбранных '+m+' пар');return}if(Math.abs(sum-100)>.01){alert(m+': доли должны дать 100%. Сейчас '+sum.toFixed(2)+'%.');return}if(m==='LIVE'){c.api_key=key.value;c.api_secret=secret.value;if(!c.api_key||!c.api_secret){alert('Для LIVE нужны API Key и Secret');return}}let r=await fetch('/api/'+m.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c)}),d=await r.json();if(!r.ok){alert(d.detail||'Ошибка '+m);return}beginSession(m);drawSessions();refresh()}
async function stopMode(m,em=false){await fetch('/api/'+m.toLowerCase()+'/'+(em?'emergency-stop':'stop'),{method:'POST'});finishSession(m);drawSessions();refresh()}
function fmt(v){return v==null?'—':Number(v).toPrecision(9)}
async function recs(){try{let d=await (await fetch('/api/recommendations?limit=20')).json();if(!d.candidates20?.length){r.textContent=d.radar_error?'Ошибка анализа: '+d.radar_error:'WebSocket подключается…';top5.textContent='WebSocket подключается…';return}top5.innerHTML=(d.top5||[]).map((x,i)=>`<div class="result"><b>#${i+1} ${x.symbol}</b> • ${x.signal} • вход ${fmt(x.estimated_entry)} • выход ${fmt(x.estimated_exit)} • TF ${x.timeframe||'3m'} • ${x.hold_seconds||180}с <button class="pick tap" onclick="selectPair('${x.symbol}',this)">ВЫБРАТЬ</button></div>`).join('');r.innerHTML=d.candidates20.map((x,i)=>`<div class="rec"><div class="recrow"><div class="line"><b>#${i+1} ${x.symbol}</b> • ${x.signal} • вход ${fmt(x.estimated_entry)} • выход ${fmt(x.estimated_exit)} • TF ${x.timeframe||'3m'} • ${x.hold_seconds||180}с</div><button class="arrow tap" onclick="detail(this)">⌄</button><button class="pick tap" onclick="selectPair('${x.symbol}',this)">ВЫБРАТЬ</button></div><div class="details">SL ${fmt(x.estimated_stop)} • score ${Number(x.score||0).toFixed(2)} • 24ч ${Number(x.change_24h_pct||0).toFixed(2)}% • 3m ${Number(x.change_3m_pct||0).toFixed(3)}% • vol ×${Number(x.volume_ratio||1).toFixed(2)} • pumps ${x.pump_events||0}</div></div>`).join('')}catch(e){r.textContent='Ошибка анализа: '+e.message}}
function detail(b){let d=b.closest('.rec').querySelector('.details');d.classList.toggle('open');b.textContent=d.classList.contains('open')?'⌃':'⌄'}
async function refresh(){try{let p=await (await fetch('/api/paper/status')).json(),l=await (await fetch('/api/live/status')).json();if(!sessions.PAPER.running&&!sessions.PAPER.stop&&p.running)beginSession('PAPER');if(!sessions.LIVE.running&&!sessions.LIVE.stop&&l.running)beginSession('LIVE');if(!p.running&&sessions.PAPER.running)finishSession('PAPER');if(!l.running&&sessions.LIVE.running)finishSession('LIVE');drawSessions();res.innerHTML=`<div class="result">PAPER ${p.running?'🟢':''} • старт ${Number(p.initial_balance||0).toFixed(4)} • баланс ${Number(p.balance||0).toFixed(4)} • NET ${Number(p.pnl||0).toFixed(4)} • сделок ${(p.trades||[]).length}</div><div class="result">LIVE ${l.running?'🟢':''} • старт ${Number(l.capital||0).toFixed(4)} • баланс ${Number(l.free_capital||0).toFixed(4)} • NET ${Number(l.realized_pnl||0).toFixed(4)} • сделок ${(l.trades||[]).length}</div>`}catch(e){}}
loadSessions();render();recs();refresh();drawSessions();setInterval(drawSessions,1000);setInterval(refresh,3000);setInterval(recs,15000);
</script>
</body></html>'''

@app.get('/', response_class=HTMLResponse)
def home():
    return HTML
