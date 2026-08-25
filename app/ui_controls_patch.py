from __future__ import annotations

# Final mobile control patch for Fast Scalper.
# PAPER may use partial bot capital; LIVE may also use any total <=100%.

def install(app):
    route = next((r for r in app.router.routes if getattr(r, "path", None) == "/"), None)
    if route is None:
        return
    from . import ui_v7

    css = r'''<style id="fs-final-controls">
.run-grid{grid-template-columns:repeat(2,minmax(0,1fr)) !important;gap:10px !important}
.run-mode{min-width:0}.run-switch{cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent}.run-switch:active{transform:scale(.98)}
@media(max-width:600px){.run-grid{grid-template-columns:repeat(2,minmax(0,1fr)) !important}.run-mode{padding:8px 5px}.run-label{font-size:12px}.run-switch{min-width:72px;padding:7px 9px}.run-timer{font-size:15px}}
</style>'''
    if 'id="fs-final-controls"' not in ui_v7.SKIN:
        ui_v7.SKIN = ui_v7.SKIN.replace('</head>', css + '</head>', 1)

    js = r'''<script id="fs-final-control-js">
(function(){
  const $=id=>document.getElementById(id),timers={PAPER:null,LIVE:null};
  function paint(mode,on,startedAt){const low=mode.toLowerCase(),sw=$(low+'Switch'),tx=$(low+'SwitchText'),st=$(low+'Status'),tm=$(low+'Timer');if(sw)sw.classList.toggle('on',!!on);if(tx)tx.textContent=on?'ON':'OFF';if(st){st.textContent=mode+' '+(on?'работает':'остановлен');st.classList.toggle('on',!!on)}clearInterval(timers[mode]);const tick=()=>{if(!tm)return;if(!on){tm.textContent='00:00:00';return}const sec=Math.max(0,Math.floor((Date.now()-(Number(startedAt)||Date.now()))/1000)),h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;tm.textContent=[h,m,s].map(x=>String(x).padStart(2,'0')).join(':')};tick();if(on)timers[mode]=setInterval(tick,1000)}
  async function report(mode){const r=await fetch('/api/session/report/'+mode,{cache:'no-store'});if(!r.ok)throw new Error('Сервис отчёта недоступен');return await r.json()}
  async function sync(mode){try{const d=await report(mode);paint(mode,!!d.running,d.started_at?Number(d.started_at)*1000:Date.now());return d}catch(e){return null}}
  async function run(mode){try{if(typeof cfg!=='function')throw new Error('Конфигурация интерфейса не загружена');const c=cfg(mode),total=(c.allocations||[]).reduce((a,b)=>a+(Number(b)||0),0);if(!(c.pairs||[]).length){alert('Нет выбранных '+mode+' пар');return false}if(total<=0||total>100.01){alert(mode+': сумма долей должна быть от 0 до 100%. Сейчас '+total.toFixed(2)+'%.');return false}if(mode==='LIVE'){c.api_key=$('key')?.value||'';c.api_secret=$('secret')?.value||'';if(!c.api_key||!c.api_secret){alert('Для LIVE нужны API Key и Secret');return false}}const r=await fetch('/api/'+mode.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c),cache:'no-store'});let d={};try{d=await r.json()}catch(e){}if(!r.ok||d.running===false){alert(d.detail||('Не удалось запустить '+mode));await sync(mode);return false}await sync(mode);return true}catch(e){alert('Ошибка запуска '+mode+': '+e.message);return false}}
  async function halt(mode){try{const r=await fetch('/api/'+mode.toLowerCase()+'/stop',{method:'POST',cache:'no-store'});await sync(mode);return r.ok}catch(e){await sync(mode);return false}}
  window.toggleRun=async function(mode){const sw=$(mode.toLowerCase()+'Switch'),on=!!(sw&&sw.classList.contains('on'));if(on){await halt(mode);return}await run(mode)};
  function bind(){for(const mode of ['PAPER','LIVE']){const b=$(mode.toLowerCase()+'Switch');if(!b||b.dataset.fsBound)return;b.dataset.fsBound='1';b.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();window.toggleRun(mode)})}sync('PAPER');sync('LIVE')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind);else bind();
})();
</script>'''
    if 'id="fs-final-control-js"' not in ui_v7.SKIN:
        ui_v7.SKIN = ui_v7.SKIN.replace('</body>', js + '</body>', 1)
