from __future__ import annotations

from fastapi.responses import HTMLResponse
from .ui_v9 import app, SKIN as BASE_SKIN

for route in list(app.router.routes):
    if getattr(route, 'path', None) == '/':
        app.router.routes.remove(route)

PATCH = r'''<style>
.fs-top10-final{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:8px}
.fs-top10-final .fs-card{border:1px solid #451015;border-radius:10px;background:#08090a;padding:8px;min-width:0}
.fs-top10-final .rank{display:flex;justify-content:space-between;gap:6px;font-weight:900;color:#fff}.fs-top10-final .score{color:#65f28d;border:1px solid #1d8d46;background:#082514;border-radius:5px;padding:2px 5px}
.fs-top10-final .meta{display:grid;grid-template-columns:1fr 1fr;gap:2px 6px;margin-top:5px;color:#aaa;font-size:10px}.fs-top10-final .profit{color:#65f28d;font-weight:900}
.fs-top10-final select{width:100%;margin-top:5px;background:#151719;color:#fff;border:1px solid #3b3c40;border-radius:5px;padding:4px;font-weight:800;font-size:10px}.fs-top10-final button{width:100%;margin-top:6px;border:1px solid #ffb300;background:#281d06;color:#ffd04d;border-radius:6px;padding:6px;font-weight:900;font-size:10px}
@media(max-width:600px){.fs-top10-final{gap:5px}.fs-top10-final .fs-card{padding:6px}.fs-top10-final .meta{font-size:9px}.fs-top10-final select,.fs-top10-final button{font-size:9px}}
</style>
<script>
(function(){
  const $=id=>document.getElementById(id), esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  // Expand the existing selector from 5 to 10 persistent slots without replacing the established UI logic.
  while(slots.length<10) slots.push({p:'',v:0,input:'pct',mode:'PAPER'});
  save(); render();

  const tfKey='fsRecommendationTimeframes';
  const tfState=JSON.parse(localStorage.getItem(tfKey)||'{}');
  function rows(d){return (d.candidates20||d.top10||d.top5||d.top||[]).slice(0,10)}
  function estimate(x,tf){
    const explicit=Number(x.expected_pnl_per_min_100);
    if(Number.isFinite(explicit)&&explicit>0){const mult=tf==='1m'?0.85:tf==='5m'?1.10:1;const v=explicit*mult;return {pnl:v,low:v*0.65,high:v*1.25}}
    const entry=Number(x.estimated_entry||x.price||0), exit=Number(x.estimated_exit||0);
    if(!(entry>0&&exit>0))return null; const move=Math.abs(exit-entry)/entry; const scale=Math.sqrt((Number(tf[0])||3)/3); const gross=100*move*scale; const fee=0.20; return {pnl:Math.max(0,gross-fee),low:Math.max(0,gross*.65-fee),high:Math.max(0,gross*1.25-fee)};
  }
  function render10(rs){
    const top=$('top');if(!top)return;
    top.innerHTML='<div class="fs-top10-final">'+rs.map((x,i)=>{const s=String(x.symbol||'—'),tf=String(tfState[s]||'3m'),e=estimate(x,tf);const p=e?`+$${e.low.toFixed(2)}–$${e.high.toFixed(2)}`:'—';return `<div class="fs-card"><div class="rank"><span>🔥 #${i+1} ${esc(s)}</span><span class="score">${Number.isFinite(Number(x.score))?Number(x.score).toFixed(0):'—'}</span></div><div class="meta"><span>Hot: ${Number.isFinite(Number(x.hot_market_score))?Number(x.hot_market_score).toFixed(0):'—'}</span><span>Flow: ${Number.isFinite(Number(x.buy_ratio))?(Number(x.buy_ratio)*100).toFixed(0)+'%':'—'}</span><span>1–3m: ${Number.isFinite(Number(x.change_3m_pct))?Number(x.change_3m_pct).toFixed(3)+'%':'—'}</span><span>$/мин/$100: <b class="profit">${Number.isFinite(Number(x.expected_pnl_per_min_100))?'$'+Number(x.expected_pnl_per_min_100).toFixed(2):'—'}</b></span></div><div class="profit">Прогноз $100: ${p}</div><select data-symbol="${esc(s)}" onchange="window.fsTF(this)"><option value="1m" ${tf==='1m'?'selected':''}>1 мин</option><option value="3m" ${tf==='3m'?'selected':''}>3 мин</option><option value="5m" ${tf==='5m'?'selected':''}>5 мин</option></select><button class="top-select" data-symbol="${esc(s)}" onclick="pick(this.dataset.symbol)">ДОБАВИТЬ</button></div>`}).join('')+'</div>'; if(window.mark)window.mark();
  }
  window.fsTF=function(el){tfState[el.dataset.symbol]=el.value;localStorage.setItem(tfKey,JSON.stringify(tfState));window.recs()};
  window.recs=async function(){try{const r=await fetch('/api/recommendations?limit=20',{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Ошибка радара');render10(rows(d))}catch(e){if($('top'))$('top').innerHTML='<div class="error">Ошибка радара: '+esc(e.message)+'</div>'}};
  window.recs();

  window.pick=function(symbol){let i=slots.findIndex(x=>!x.p);if(i<0){alert('Все 10 торговых слотов заняты.');return}slots[i].p=String(symbol).trim().toUpperCase();slots[i].mode='PAPER';slots[i].input='pct';if(localStorage.getItem('fsAllocationMode')==='AUTO'){const a=slots.map((x,j)=>({x,j})).filter(z=>z.x.p&&z.x.mode==='PAPER');const each=100/a.length;a.forEach(z=>z.x.v=Math.round(each*100)/100)}save();render();if(window.recs)window.recs()};

  // Per-pair timeframe is sent to the engine. It is an analysis/exit horizon, never a forced hold.
  window.start=async function(mode){try{const a=slots.map((x,i)=>({x,i})).filter(z=>z.x.p&&z.x.mode===mode);const allocations=a.map(z=>pct(z.i));const total=allocations.reduce((s,v)=>s+Number(v||0),0);if(!a.length){alert('Нет выбранных '+mode+' пар');return false}if(total<=0||total>100.0001){alert(mode+': общая доля должна быть от 0.01% до 100%. Сейчас '+total.toFixed(2)+'%.');return false}const c={capital:cap(),pairs:a.map(z=>z.x.p),allocations,timeframes:a.map(z=>tfState[z.x.p]||'3m'),target_pnl_per_min_per_100:1.73,target_usdt:0.30,min_usdt:0.15,fee_pct:0.10,timeframe:'3m'};if(mode==='LIVE'){c.api_key=$('key')?.value||'';c.api_secret=$('secret')?.value||'';if(!c.api_key||!c.api_secret){alert('Для LIVE нужны API Key и Secret');return false}}const r=await fetch('/api/'+mode.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c),cache:'no-store'});const raw=await r.text();let d={};try{d=JSON.parse(raw)}catch(e){d={detail:raw.slice(0,400)}}if(!r.ok||!d.running){alert(d.detail||('Ошибка запуска '+mode));return false}if(window.fsForceRun)window.fsForceRun(mode,d);return true}catch(e){alert('Ошибка запуска '+mode+': '+e.message);return false}};

  // Keep the existing status renderer, but make the position capacity 10.
  const fixCapacity=()=>{if($('used')){const p=(document.querySelectorAll('#positions .pos')||[]).length;$('used').textContent=p+' / 10'}if($('usedbar')){const p=(document.querySelectorAll('#positions .pos')||[]).length;$('usedbar').style.width=Math.min(100,p*10)+'%'}};
  setInterval(fixCapacity,500);setTimeout(fixCapacity,100);
})();
</script>'''

SKIN = BASE_SKIN.replace('</body>', PATCH + '</body>', 1)

@app.get('/', response_class=HTMLResponse)
def home():
    return HTMLResponse(content=SKIN,headers={'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0','Pragma':'no-cache','Expires':'0'})
