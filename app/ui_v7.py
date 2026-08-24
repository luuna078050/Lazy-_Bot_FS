from __future__ import annotations

import re
from fastapi.responses import HTMLResponse
from .ui_v6 import app, SKIN as BASE_SKIN

for route in list(app.router.routes):
    if getattr(route, 'path', None) == '/':
        app.router.routes.remove(route)

SKIN = BASE_SKIN

# Start clean: old five-pair presets must never reappear after the UI update.
SKIN = SKIN.replace("localStorage.getItem('fsSlots')", "localStorage.getItem('fsSlotsV2')")
SKIN = SKIN.replace("localStorage.setItem('fsSlots',", "localStorage.setItem('fsSlotsV2',")
SKIN = SKIN.replace("Array.from({length:5}", "Array.from({length:6}")
SKIN = SKIN.replace("Все 5 слотов заняты", "Все 6 слотов заняты")
SKIN = SKIN.replace("0 / 5", "0 / 6")
SKIN = SKIN.replace("p.length*20", "p.length*16.6667")
SKIN = SKIN.replace("value=\"${x.v}\" oninput=", "value=\"${x.v}\" onfocus=\"if(this.value==='0')this.value=''\" oninput=")

old = re.search(r'<div class="bot-summary">.*?</div></section>', SKIN, flags=re.S)
if not old:
    raise RuntimeError('Fast Scalper capital summary block not found')
new = '''<div class="bot-summary capital-line">
<div>🤖 БАЛАНС БОТА — <b id="bot">—</b></div>
<div>💰 НАКОПЛЕНО БОТОМ — <b id="accumulated">—</b></div>
<div>➕ ВОЗМОЖНО ПРИВЛЕЧЬ — <b id="extra">—</b></div>
</div></section>'''
SKIN = SKIN[:old.start()] + new + SKIN[old.end():]

SKIN = SKIN.replace(
    '.bot-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;color:#aaa;font-size:11px}',
    '.bot-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;color:#aaa;font-size:11px}.capital-line{align-items:center}.capital-line>div{white-space:nowrap}.capital-line b{display:inline;color:#fff;font-size:16px;margin-left:3px}',
    1,
)

REPORT_JS = r'''<script>
(function(){
  const oldRefresh=window.refresh;if(!oldRefresh)return;
  window.refresh=async function(){await oldRefresh();try{for(const mode of ['PAPER','LIVE']){const r=await fetch('/api/session/report/'+mode,{cache:'no-store'});if(!r.ok)continue;const d=await r.json();if(d.running||d.stopped_at||Number(d.account_balance_usdt||0)>0){const bot=Number(d.bot_balance_usdt??d.initial_balance??0),accumulated=Number(d.accumulated_profit_usdt??((Number(d.account_balance_usdt||0))-bot)),extra=Number(d.available_to_attract_usdt??Math.max(0,Number(d.account_balance_usdt||0)-bot));const b=document.getElementById('bot'),a=document.getElementById('accumulated'),e=document.getElementById('extra');if(b)b.textContent=(bot||0).toFixed(4)+' USDT';if(a)a.textContent=(accumulated||0).toFixed(4)+' USDT';if(e)e.textContent=(extra||0).toFixed(4)+' USDT'}}}catch(e){}};
})();
</script>'''
SKIN = SKIN.replace('</body>', REPORT_JS + '</body>', 1)

RUN_JS = r'''<script>
(function(){
 const $=id=>document.getElementById(id),timers={PAPER:null,LIVE:null},starts={PAPER:null,LIVE:null};
 function storageKey(m){return m==='PAPER'?'fsRunStartPaper':'fsRunStartLive'}
 function paint(m,on,startTs){const low=m.toLowerCase(),sw=$(low+'Switch'),tx=$(low+'SwitchText'),st=$(low+'Status'),tm=$(low+'Timer');if(sw)sw.classList.toggle('on',!!on);if(tx)tx.textContent=on?'ON':'OFF';if(st){st.textContent=m+' '+(on?'работает':'остановлен');st.classList.toggle('on',!!on)}clearInterval(timers[m]);if(!on){starts[m]=null;localStorage.removeItem(storageKey(m));if(tm)tm.textContent='00:00:00';return}const ts=Number(startTs)||Date.now();starts[m]=ts;localStorage.setItem(storageKey(m),String(ts));const tick=()=>{const n=Math.max(0,Math.floor((Date.now()-ts)/1000)),h=Math.floor(n/3600),mi=Math.floor((n%3600)/60),s=n%60;if(tm)tm.textContent=[h,mi,s].map(x=>String(x).padStart(2,'0')).join(':')};tick();timers[m]=setInterval(tick,1000)}
 async function sync(m){try{const r=await fetch('/api/session/report/'+m,{cache:'no-store'});if(!r.ok){paint(m,false);return false}const d=await r.json();paint(m,!!d.running,d.started_at?Number(d.started_at)*1000:null);if(window.fsV6Report)window.fsV6Report(d);return !!d.running}catch(e){return false}}
 window.start=async function(m){try{const c=cfg(m);const total=(c.allocations||[]).reduce((a,b)=>a+b,0);if(!(c.pairs||[]).length){alert('Нет выбранных '+m+' пар');paint(m,false);return false}if(Math.abs(total-100)>.01){alert(m+': доли автоматически распределяются при выборе пар. Сейчас '+total.toFixed(2)+'%. Выбери пару ещё раз или проверь значения.');paint(m,false);return false}if(m==='LIVE'){c.api_key=$('key')?.value||'';c.api_secret=$('secret')?.value||'';if(!c.api_key||!c.api_secret){alert('Для LIVE нужны API Key и Secret');paint(m,false);return false}}const r=await fetch('/api/'+m.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c),cache:'no-store'});const raw=await r.text();let d={};try{d=JSON.parse(raw)}catch(e){d={detail:raw.slice(0,300)}}if(!r.ok||!d.running){alert(d.detail||'Ошибка запуска '+m);paint(m,false);return false}await sync(m);return true}catch(e){alert('Ошибка запуска '+m+': '+e.message);paint(m,false);return false}};
 window.stop=async function(m){try{const r=await fetch('/api/'+m.toLowerCase()+'/stop',{method:'POST',cache:'no-store'});await sync(m);if(r.ok)paint(m,false);return r.ok}catch(e){paint(m,false);return false}};
 window.toggleRun=async function(m){const sw=$(m.toLowerCase()+'Switch');if(sw&&sw.classList.contains('on'))return window.stop(m);return window.start(m)};
 window.emergency=async function(){try{await Promise.all(['PAPER','LIVE'].map(m=>fetch('/api/'+m.toLowerCase()+'/emergency-stop',{method:'POST',cache:'no-store'})))}finally{paint('PAPER',false);paint('LIVE',false);await sync('PAPER');await sync('LIVE')}};
 async function boot(){await sync('PAPER');await sync('LIVE')}boot();setInterval(()=>{sync('PAPER');sync('LIVE')},3000);
})();
</script>'''
SKIN = SKIN.replace('</body>', RUN_JS + '</body>', 1)

TOP6 = r'''<style>
.top-table{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:8px}.top-cell{border:1px solid #451015;border-radius:10px;background:#08090a;padding:9px;min-width:0}.top-rank{font-weight:900;color:#fff;font-size:15px}.top-symbol{font-weight:900;color:#fff;font-size:15px}.top-score{color:#22e36f;font-weight:900;font-size:18px;float:right}.top-meta{color:#aaa;font-size:11px;line-height:1.35;margin-top:4px}.top-pick{width:100%;border:1px solid #22e36f;background:#0e793b;color:#fff;border-radius:7px;padding:7px;font-weight:900;margin-top:7px}.top-pick.selected{background:#16a34a;box-shadow:0 0 8px rgba(34,227,111,.22)}@media(max-width:700px){.top-table{grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}.top-cell{padding:7px}.top-symbol,.top-rank{font-size:13px}.top-score{font-size:15px}.top-meta{font-size:10px}}
</style>
<script>
(function(){
 const oldRecs=window.recs;if(!oldRecs)return;
 window.recs=async function(){try{const r=await fetch('/api/recommendations?limit=20',{cache:'no-store'}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Ошибка радара');const rows=(d.candidates20||[]).slice(0,6),top=document.getElementById('top');if(!top)return;if(!rows.length){top.textContent='Радар пока не дал рекомендаций';return}top.innerHTML='<div class="top-table">'+rows.map((x,i)=>'<div class="top-cell"><div class="top-rank">#'+(i+1)+' <span class="top-symbol">'+String(x.symbol||'—')+'</span><span class="top-score">'+(x.score??'—')+'</span></div><div class="top-meta">'+(x.signal||'WAIT')+' • вход '+(x.estimated_entry??'—')+' → '+(x.estimated_exit??'—')+' • '+(x.hold_seconds||180)+'с</div><button class="top-pick top-select" data-symbol="'+String(x.symbol||'').replace(/"/g,'&quot;')+'" onclick="pick(this.dataset.symbol)">ВЫБРАТЬ</button></div>').join('')+'</div>';if(window.mark)window.mark()}catch(e){const top=document.getElementById('top');if(top)top.textContent='Ошибка радара: '+e.message}};
 const oldPick=window.pick;
 window.pick=function(s){
   const pairInputs=[...document.querySelectorAll('#slots .slot input[placeholder^="ПАРА"]')];
   const count=pairInputs.filter(x=>x.value.trim()).length;
   if(count>=5){alert('Для торговли можно выбрать максимум 5 пар. Шестая остаётся в рейтинге.');return}
   oldPick(s);
   const rows=[...document.querySelectorAll('#slots .slot')];
   const selected=rows.filter(row=>row.querySelector('input[placeholder^="ПАРА"]')?.value.trim());
   const share=100/selected.length;
   selected.forEach(row=>{
     const modeBtn=row.querySelector('.mini button:nth-child(1), .mini button:nth-child(2)');
     const input=row.querySelector('input[type="number"]');
     if(input){input.value=share.toFixed(2);input.dispatchEvent(new Event('input',{bubbles:true}))}
   });
   window.recs();
 };
 window.recs();
})();
</script>'''
SKIN = SKIN.replace('</body>', TOP6 + '</body>', 1)

@app.get('/', response_class=HTMLResponse)
def home():
    return HTMLResponse(content=SKIN,headers={'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0','Pragma':'no-cache','Expires':'0'})
