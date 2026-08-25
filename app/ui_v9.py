from __future__ import annotations

from fastapi.responses import HTMLResponse
from .ui_v8 import app, SKIN as BASE_SKIN

for route in list(app.router.routes):
    if getattr(route, 'path', None) == '/':
        app.router.routes.remove(route)

SKIN = BASE_SKIN

PATCH = r'''<style>
.alloc-mode{display:flex;gap:6px;margin:8px 0}.alloc-mode button{flex:1;border:1px solid #3b3c40;border-radius:7px;background:#18191b;color:#bbb;padding:8px;font-weight:900}.alloc-mode button.on{border-color:#22e36f;background:#0e793b;color:#fff}.alloc-help{font-size:11px;color:#aaa;margin:5px 0 8px}
</style>
<script>
(function(){
  const $=id=>document.getElementById(id);
  const key='fsAllocationMode';
  let allocationMode=localStorage.getItem(key)||'AUTO';
  const cap=()=>Number($('capital')?.value)||0;
  function saveMode(){localStorage.setItem(key,allocationMode)}
  function selected(mode){return slots.map((x,i)=>({x,i})).filter(z=>z.x.p&&z.x.mode===mode)}
  function setValue(i,v){slots[i].v=Math.max(0,Math.round(v*100)/100)}
  function rebalance(mode,changedIndex){
    if(allocationMode!=='AUTO') return;
    const arr=selected(mode); if(!arr.length)return;
    let changed=arr.find(z=>z.i===changedIndex);
    if(!changed) return;
    let fixed=Math.max(0,Math.min(100,Number(changed.x.v)||0));
    setValue(changed.i,fixed);
    const others=arr.filter(z=>z.i!==changedIndex);
    const remain=Math.max(0,100-fixed);
    if(!others.length)return;
    const each=remain/others.length;
    others.forEach(z=>setValue(z.i,each));
  }
  function normalizeExisting(mode){
    if(allocationMode!=='AUTO')return;
    const arr=selected(mode); if(!arr.length)return;
    const total=arr.reduce((s,z)=>s+(Number(z.x.v)||0),0);
    if(total<=0){const each=100/arr.length;arr.forEach(z=>setValue(z.i,each));return}
    const factor=100/total;arr.forEach(z=>setValue(z.i,(Number(z.x.v)||0)*factor));
  }
  function addModeUI(){
    const total=$('total'); if(!total||document.getElementById('allocMode'))return;
    const box=document.createElement('div'); box.id='allocMode'; box.className='alloc-mode';
    box.innerHTML='<button id="allocAuto" type="button">АВТОРАСПРЕДЕЛЕНИЕ</button><button id="allocManual" type="button">ВРУЧНУЮ</button>';
    total.parentNode.insertBefore(box,total);
    const help=document.createElement('div');help.className='alloc-help';help.id='allocHelp';total.parentNode.insertBefore(help,total);
    const paint=()=>{ $('allocAuto')?.classList.toggle('on',allocationMode==='AUTO'); $('allocManual')?.classList.toggle('on',allocationMode==='MANUAL'); if($('allocHelp'))$('allocHelp').textContent=allocationMode==='AUTO'?'Изменяешь одну долю — остальные выбранные пары автоматически получают остаток. Можно использовать меньше 100% капитала.':'Ручной режим: каждая доля задаётся отдельно. Общая сумма может быть меньше 100%.' };
    $('allocAuto').onclick=()=>{allocationMode='AUTO';saveMode();normalizeExisting('PAPER');normalizeExisting('LIVE');save();render();paint()};
    $('allocManual').onclick=()=>{allocationMode='MANUAL';saveMode();render();paint()};
    paint();
  }
  const oldRender=window.render;
  if(typeof oldRender==='function'){
    window.render=function(){oldRender();addModeUI();};
  }
  const oldPick=window.pick;
  window.pick=function(symbol){
    const idx=slots.findIndex(x=>!x.p);
    if(idx<0){alert('Все 5 торговых слотов заняты. Шестая пара остаётся в рейтинге.');return}
    slots[idx].p=String(symbol).trim().toUpperCase();
    slots[idx].mode='PAPER';
    slots[idx].input='pct';
    if(allocationMode==='AUTO'){
      const arr=selected('PAPER');const each=100/arr.length;arr.forEach(z=>setValue(z.i,each));
    }
    save();render();if(window.recs)window.recs();
  };
  function hookInputs(){
    const box=$('slots');if(!box||box.dataset.allocHook)return;box.dataset.allocHook='1';
    box.addEventListener('input',function(e){
      const el=e.target;if(!(el instanceof HTMLInputElement)||el.type!=='number')return;
      const rows=[...box.querySelectorAll('.slot')];const row=el.closest('.slot');const i=rows.indexOf(row);if(i<0)return;
      if(allocationMode==='AUTO'){
        const mode=slots[i]?.mode||'PAPER';rebalance(mode,i);save();render();
      }
      tot();
    });
  }
  function paintMode(){
    addModeUI();hookInputs();
    if($('allocAuto'))$('allocAuto').classList.toggle('on',allocationMode==='AUTO');
    if($('allocManual'))$('allocManual').classList.toggle('on',allocationMode==='MANUAL');
  }
  window.setInterval(paintMode,1000);
  setTimeout(paintMode,0);

  // Replace the old 100%-only launcher. A session may deliberately use 10..100%.
  window.start=async function(mode){
    try{
      const c=cfg(mode);const total=(c.allocations||[]).reduce((a,b)=>a+Number(b||0),0);
      if(!(c.pairs||[]).length){alert('Нет выбранных '+mode+' пар');return false}
      if(total<=0 || total>100.0001){alert(mode+': общая доля должна быть от 0.01% до 100%. Сейчас '+total.toFixed(2)+'%.');return false}
      if(mode==='LIVE'){
        c.api_key=$('key')?.value||'';c.api_secret=$('secret')?.value||'';
        if(!c.api_key||!c.api_secret){alert('Для LIVE нужны API Key и Secret');return false}
      }
      const r=await fetch('/api/'+mode.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c),cache:'no-store'});
      const raw=await r.text();let d={};try{d=JSON.parse(raw)}catch(e){d={detail:raw.slice(0,400)}}
      if(!r.ok||!d.running){alert(d.detail||('Ошибка запуска '+mode));return false}
      if(typeof window.fsForceRun==='function')window.fsForceRun(mode,d);
      return true;
    }catch(e){alert('Ошибка запуска '+mode+': '+e.message);return false}
  };
  window.stop=async function(mode){
    try{const r=await fetch('/api/'+mode.toLowerCase()+'/stop',{method:'POST',cache:'no-store'});if(typeof window.fsForceStop==='function')window.fsForceStop(mode);return r.ok}catch(e){return false}
  };

  // Stable controls: never flash OFF on a transient report error.
  window.fsForceRun=function(mode,d){
    const low=mode.toLowerCase(),sw=$(low+'Switch'),tx=$(low+'SwitchText'),st=$(low+'Status');
    if(sw)sw.classList.add('on');if(tx)tx.textContent='ON';if(st){st.textContent=mode+' работает';st.classList.add('on')}
    if(d?.started_at)localStorage.setItem(mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive',String(Number(d.started_at)*1000));
  };
  window.fsForceStop=function(mode){
    const low=mode.toLowerCase(),sw=$(low+'Switch'),tx=$(low+'SwitchText'),st=$(low+'Status');
    if(sw)sw.classList.remove('on');if(tx)tx.textContent='OFF';if(st){st.textContent=mode+' остановлен';st.classList.remove('on')}
    localStorage.removeItem(mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive');
  };
  window.toggleRun=async function(mode){
    const sw=$(mode.toLowerCase()+'Switch');
    if(sw?.classList.contains('on'))return window.stop(mode);
    return window.start(mode);
  };
})();
</script>'''

SKIN = SKIN.replace('</body>', PATCH + '</body>', 1)

@app.get('/', response_class=HTMLResponse)
def home():
    return HTMLResponse(content=SKIN,headers={'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0','Pragma':'no-cache','Expires':'0'})
