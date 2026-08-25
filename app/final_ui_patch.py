from __future__ import annotations

import inspect
import re
from fastapi.responses import HTMLResponse
from fastapi.routing import request_response


def install(app):
    route = next((r for r in app.router.routes if getattr(r, 'path', None) == '/'), None)
    if route is None or not hasattr(route, 'endpoint'):
        return
    original = route.endpoint
    if getattr(original, '_fs_ui_final_v11', False):
        return

    def endpoint(*args, **kwargs):
        response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
        html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)

        # The hero is no longer useful on the working dashboard. Remove it completely;
        # the compact PAPER/LIVE command block takes its place at the very top.
        html = re.sub(r'<section class="hero">.*?</section>', '', html, count=1, flags=re.S)
        html = re.sub(r'<section class="card run-card">.*?</section>', '', html, count=1, flags=re.S)

        command_card = r'''<section class="card fs-command-card" id="fsCommandCard">
<div class="title">⚡ УПРАВЛЕНИЕ БОТОМ</div>
<div class="fs-command-grid">
  <div class="fs-command-mode">
    <div class="fs-command-label">PAPER</div>
    <button id="paperSwitch" class="run-switch" type="button" onclick="toggleRun('PAPER')"><span class="run-dot"></span><b id="paperSwitchText">OFF</b></button>
    <div id="paperStatus" class="run-status">PAPER остановлен</div>
    <div id="paperTimer" class="run-timer">00:00:00</div>
  </div>
  <div class="fs-command-mode">
    <div class="fs-command-label">LIVE</div>
    <button id="liveSwitch" class="run-switch" type="button" onclick="toggleRun('LIVE')"><span class="run-dot"></span><b id="liveSwitchText">OFF</b></button>
    <div id="liveStatus" class="run-status">LIVE остановлен</div>
    <div id="liveTimer" class="run-timer">00:00:00</div>
    <button id="fsEmergency" class="fs-emergency" type="button" onclick="emergency()">⛔ EMERGENCY STOP</button>
  </div>
</div>
</section>'''
        html = html.replace('<main class="wrap">', '<main class="wrap">' + command_card, 1)

        css = r'''<style id="fs-ui-v11-css">
/* Compact command block: two equal horizontal modes. */
.fs-command-card{padding:8px 10px;margin:7px 0}.fs-command-card>.title{font-size:14px;margin-bottom:5px}
.fs-command-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}.fs-command-mode{border:1px solid #451015;border-radius:9px;background:#08090a;padding:7px;text-align:center;min-width:0}
.fs-command-label{font-size:11px;font-weight:900;color:#ddd;margin-bottom:3px}.fs-command-mode .run-switch{display:inline-flex;align-items:center;justify-content:center;gap:6px;width:auto;min-width:70px;padding:5px 10px;margin:0;border:1px solid #555;background:#18191b;color:#aaa;border-radius:999px;font-weight:900;cursor:pointer;touch-action:manipulation}
.fs-command-mode .run-switch.on{background:#0e793b;border-color:#22e36f;color:#fff;box-shadow:0 0 8px rgba(34,227,111,.22)}.fs-command-mode .run-dot{width:8px;height:8px;border-radius:50%;background:#666}.fs-command-mode .run-switch.on .run-dot{background:#22e36f;box-shadow:0 0 7px #22e36f}
.fs-command-mode .run-status{margin-top:3px;color:#888;font-size:10px;line-height:1.1}.fs-command-mode .run-status.on{color:#22e36f;font-weight:900}.fs-command-mode .run-timer{font-variant-numeric:tabular-nums;font-size:15px;font-weight:900;color:#fff;margin:3px 0 0}
.fs-emergency{width:100%;border:0;border-radius:7px;background:#292a2d;color:#fff;font-weight:900;font-size:10px;padding:5px 4px;margin-top:4px;cursor:pointer}
/* PnL: add the hypothetical net projection without changing realized/unrealized/net accounting. */
.pnl-card .pnlrow{grid-template-columns:repeat(4,minmax(0,1fr))!important}.fs-hypo-label{color:#aaa}.fs-hypo-value{display:block;color:#65f28d;font-weight:900;margin-top:3px}
/* One compact line for bot balance / attractable / accumulated profit. */
.bot-summary{grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:5px!important;align-items:center}.bot-summary>div{white-space:nowrap;font-size:10px}.bot-summary b{display:inline!important;font-size:14px!important;margin-left:3px!important}
/* Ten selected trading slots: 2 columns x 5 rows. Per-slot PAPER/LIVE controls are intentionally removed. */
#slots{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:6px}.slot{padding:6px!important}.slot .mini{display:none!important}.slot .input{padding:7px!important;margin:2px 0!important;font-size:12px}.slot .btn{padding:6px!important;font-size:10px;margin-top:4px}.slot .muted{font-size:9px}.fs-slot-row{display:grid;grid-template-columns:1fr 54px;gap:5px;align-items:center}.fs-slot-tf{width:100%;background:#151719;color:#ffd04d;border:1px solid #3b3c40;border-radius:6px;padding:5px 3px;font-size:10px;font-weight:900}
/* Keep the ten radar cards in compact blocks. */
.fs-top10-final,.fs-top10{grid-template-columns:repeat(2,minmax(0,1fr))!important}
@media(max-width:600px){.fs-command-grid{grid-template-columns:1fr 1fr}.fs-command-mode{padding:6px 4px}.fs-command-label{font-size:10px}.fs-command-mode .run-switch{min-width:62px;padding:5px 7px;font-size:11px}.fs-command-mode .run-timer{font-size:14px}.fs-emergency{font-size:9px;padding:5px 2px}.pnl-card .pnlrow{grid-template-columns:repeat(4,minmax(0,1fr))!important}.bot-summary>div{font-size:8px}.bot-summary b{font-size:12px!important}.slot .input{font-size:11px!important}.fs-slot-tf{font-size:9px}}
</style>'''
        html = html.replace('</style></head>', css + '</style></head>', 1)

        js = r'''<script id="fs-ui-v11-js">
(function(){
  const $=id=>document.getElementById(id);
  const TF_KEY='fsRecommendationTimeframes';
  const tfState=JSON.parse(localStorage.getItem(TF_KEY)||'{}');
  const timer={PAPER:null,LIVE:null};

  function normalizeSlots(){
    if(typeof slots==='undefined') return;
    while(slots.length<10) slots.push({p:'',v:0,input:'pct',mode:'LIVE',tf:'3m'});
    if(slots.length>10) slots.length=10;
    slots.forEach(x=>{x.mode='LIVE';x.tf=x.tf||tfState[x.p]||'3m'});
  }

  function decorateSlots(){
    normalizeSlots();
    document.querySelectorAll('#slots .slot').forEach((row,i)=>{
      if(row.querySelector('.fs-slot-row')) return;
      const pair=row.querySelector('input[placeholder^="ПАРА"]');
      const number=row.querySelector('input[type="number"]');
      if(!pair||!number) return;
      const pairWrap=document.createElement('div');pairWrap.className='fs-slot-row';
      pair.parentNode.insertBefore(pairWrap,pair);pairWrap.appendChild(pair);
      const select=document.createElement('select');select.className='fs-slot-tf';select.title='Таймфрейм этой позиции';
      select.innerHTML='<option value="1m">1 мин</option><option value="3m">3 мин</option><option value="5m">5 мин</option>';
      select.value=slots[i]?.tf||'3m';
      select.onchange=function(){if(slots[i]){slots[i].tf=this.value;tfState[slots[i].p]=this.value;localStorage.setItem(TF_KEY,JSON.stringify(tfState));save()}};
      pairWrap.appendChild(select);
    });
  }

  if(typeof window.render==='function'){
    const oldRender=window.render;
    window.render=function(){oldRender();normalizeSlots();decorateSlots();if(window.mark)window.mark();};
  }

  window.pick=function(symbol){
    normalizeSlots();
    symbol=String(symbol||'').trim().toUpperCase().replace('-', '/');
    if(!symbol) return;
    const chosenTf=String(tfState[symbol]||'3m');
    const same=slots.map((x,i)=>({x,i})).filter(z=>z.x.p===symbol);
    if(same.length){
      const list=same.map(z=>z.x.tf||'3m').join(', ');
      const ok=window.confirm(symbol+' уже выбрана на таймфрейме '+list+'.\nВыбрать ту же пару ещё раз на '+chosenTf+'?');
      if(!ok)return;
    }
    const idx=slots.findIndex(x=>!x.p);
    if(idx<0){alert('Все 10 торговых слотов заняты.');return}
    slots[idx].p=symbol;slots[idx].mode='LIVE';slots[idx].input='pct';slots[idx].tf=chosenTf;
    const selected=slots.filter(x=>x.p);
    const each=Math.round((100/selected.length)*100)/100;
    selected.forEach(x=>x.v=each);
    save();render();setTimeout(decorateSlots,20);
  };

  // Replace the old start wrapper so ten slots and per-slot timeframes are sent to the backend.
  window.start=async function(mode){
    normalizeSlots();
    const selected=slots.map((x,i)=>({x,i})).filter(z=>z.x.p);
    const allocations=selected.map(z=>pct(z.i));
    const total=allocations.reduce((a,b)=>a+Number(b||0),0);
    if(!selected.length){alert('Нет выбранных пар');return false}
    if(total<=0||total>100.0001){alert(mode+': общая доля должна быть от 0.01% до 100%. Сейчас '+total.toFixed(2)+'%.');return false}
    const c={capital:cap(),pairs:selected.map(z=>z.x.p),allocations,timeframes:selected.map(z=>z.x.tf||'3m'),target_pnl_per_min_per_100:1.73,target_usdt:.30,min_usdt:.15,sl_pct:.5,max_hold:180,fee_pct:.10,timeframe:'3m'};
    if(mode==='LIVE'){
      c.api_key=$('key')?.value||'';c.api_secret=$('secret')?.value||'';
      if(!c.api_key||!c.api_secret){alert('Для LIVE нужны Binance API Key и Secret');return false}
    }
    try{
      const r=await fetch('/api/'+mode.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c),cache:'no-store'});
      const raw=await r.text();let d={};try{d=JSON.parse(raw)}catch(e){d={detail:raw.slice(0,400)}}
      if(!r.ok||!d.running){alert(d.detail||('Ошибка запуска '+mode));return false}
      paint(mode,true,d.started_at?Number(d.started_at)*1000:Date.now());return true;
    }catch(e){alert('Ошибка запуска '+mode+': '+e.message);return false}
  };

  window.stop=async function(mode){
    try{const r=await fetch('/api/'+mode.toLowerCase()+'/stop',{method:'POST',cache:'no-store'});paint(mode,false);return r.ok}catch(e){paint(mode,false);return false}
  };

  window.emergency=async function(){
    await Promise.all(['PAPER','LIVE'].map(m=>fetch('/api/'+m.toLowerCase()+'/emergency-stop',{method:'POST',cache:'no-store'}).catch(()=>null)));
    paint('PAPER',false);paint('LIVE',false);
  };

  window.toggleRun=async function(mode){const sw=$(mode.toLowerCase()+'Switch');if(sw?.classList.contains('on'))return window.stop(mode);return window.start(mode)};

  function paint(mode,on,startTs){
    const low=mode.toLowerCase(),sw=$(low+'Switch'),tx=$(low+'SwitchText'),st=$(low+'Status'),tm=$(low+'Timer');
    if(sw)sw.classList.toggle('on',!!on);if(tx)tx.textContent=on?'ON':'OFF';if(st){st.textContent=mode+' '+(on?'работает':'остановлен');st.classList.toggle('on',!!on)}
    clearInterval(timer[mode]);if(!on){if(tm)tm.textContent='00:00:00';localStorage.removeItem(mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive');return}
    const key=mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive';const ts=Number(startTs)||Number(localStorage.getItem(key))||Date.now();localStorage.setItem(key,String(ts));
    const tick=()=>{const sec=Math.max(0,Math.floor((Date.now()-ts)/1000)),h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;if(tm)tm.textContent=[h,m,s].map(x=>String(x).padStart(2,'0')).join(':')};tick();timer[mode]=setInterval(tick,1000);
  }

  async function sync(mode){try{const r=await fetch('/api/session/report/'+mode,{cache:'no-store'});if(!r.ok)return;const d=await r.json();paint(mode,!!d.running,d.started_at?Number(d.started_at)*1000:null);return d}catch(e){return null}}

  function compactMetrics(){
    const bs=document.querySelector('.bot-summary');
    if(bs){bs.innerHTML='<div>🤖 БАЛАНС БОТА <b id="bot">—</b></div><div>➕ ВОЗМОЖНО ПРИВЛЕЧЬ <b id="extra">—</b></div><div>💰 НАКОПЛЕНО <b id="accumulated">—</b></div>'}
    const row=document.querySelector('.pnl-card .pnlrow');
    if(row&&!$('hypo')){const d=document.createElement('div');d.className='fs-hypo-label';d.innerHTML='Hypothetical Net<br><b id="hypo" class="fs-hypo-value">0.0000 USDT</b>';row.appendChild(d)}
  }

  async function hypothetical(){
    try{
      normalizeSlots();
      const r=await fetch('/api/recommendations?limit=20',{cache:'no-store'});const d=await r.json();const rows=d.candidates20||d.top10||d.top5||[];const by=Object.fromEntries(rows.map(x=>[String(x.symbol||'').toUpperCase(),x]));
      let v=0;for(const x of slots.filter(s=>s.p)){const row=by[String(x.p).toUpperCase()];if(!row)continue;const mins=x.tf==='1m'?1:x.tf==='5m'?5:3;const rate=Number(row.expected_pnl_per_min_100||0);const capital=cap()*Number(x.v||0)/100;v+=rate*mins*capital/100}
      if($('hypo'))$('hypo').textContent=(v>=0?'+':'')+v.toFixed(4)+' USDT';
      const acc=document.getElementById('accumulated');if(acc){const mode=localStorage.getItem('fsLastReportMode')||'PAPER';const rep=await fetch('/api/session/report/'+mode,{cache:'no-store'}).then(x=>x.json()).catch(()=>({}));acc.textContent=(Number(rep.accumulated_profit_usdt||0)).toFixed(4)+' USDT'}
    }catch(e){}
  }

  function boot(){
    normalizeSlots();
    if(typeof window.render==='function')window.render();
    compactMetrics();decorateSlots();
    sync('PAPER');sync('LIVE');hypothetical();
    setInterval(()=>{sync('PAPER');sync('LIVE');hypothetical()},3000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else setTimeout(boot,0);
})();
</script>'''
        html = html.replace('</body>', js + '</body>', 1)

        headers = dict(getattr(response, 'headers', {}) or {})
        headers.pop('content-length', None);headers.pop('Content-Length', None)
        headers.pop('content-type', None);headers.pop('Content-Type', None)
        return HTMLResponse(content=html,status_code=getattr(response,'status_code',200),headers=headers,media_type='text/html')

    endpoint._fs_ui_final_v11 = True
    route.endpoint = endpoint
    route.app = request_response(endpoint)
