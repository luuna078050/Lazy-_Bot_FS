from __future__ import annotations

import inspect
import re
from fastapi.responses import HTMLResponse


def install(app):
    route = next((r for r in app.router.routes if getattr(r, 'path', None) == '/'), None)
    if route is None or not hasattr(route, 'endpoint'):
        return
    original = route.endpoint
    if getattr(original, '_fs_timer_stability_v16', False):
        return

    TIMER_JS = r'''<script id="fs-timer-stability-v16">
(function(){
  const $=id=>document.getElementById(id);
  const MODES=['PAPER','LIVE'];
  const KEY=m=>'fsTimerV16Start_'+m;
  const VERSION='v16-clean';
  const versionKey='fsTimerV16Version';
  const starts={PAPER:null,LIVE:null};
  const running={PAPER:false,LIVE:false};
  if(localStorage.getItem(versionKey)!==VERSION){
    MODES.forEach(m=>localStorage.removeItem(KEY(m)));
    localStorage.setItem(versionKey,VERSION);
  }

  function fmt(sec){sec=Math.max(0,Math.floor(sec));const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;return [h,m,s].map(x=>String(x).padStart(2,'0')).join(':')}
  function draw(m){
    const tm=$(m.toLowerCase()+'Timer');
    if(!tm)return;
    if(!running[m]||!starts[m]){tm.textContent='00:00:00';return}
    tm.textContent=fmt((Date.now()-starts[m])/1000);
  }
  function setVisual(m,on){
    const low=m.toLowerCase(),sw=$(low+'Switch'),tx=$(low+'SwitchText'),st=$(low+'Status');
    if(sw)sw.classList.toggle('on',on);
    if(tx)tx.textContent=on?'ON':'OFF';
    if(st){st.textContent=m+' '+(on?'работает':'остановлен');st.classList.toggle('on',on)}
    draw(m);
  }
  async function sync(m){
    try{
      const r=await fetch('/api/session/report/'+m,{cache:'no-store'});
      if(!r.ok)return;
      const d=await r.json();
      const on=!!d.running;
      if(on && !running[m]){
        const serverStart=Number(d.started_at||0)*1000;
        const saved=Number(localStorage.getItem(KEY(m))||0);
        starts[m]=serverStart>0?serverStart:(saved>0?saved:Date.now());
        localStorage.setItem(KEY(m),String(starts[m]));
      }else if(!on && running[m]){
        starts[m]=null;
        localStorage.removeItem(KEY(m));
      }else if(on && !starts[m]){
        const serverStart=Number(d.started_at||0)*1000;
        starts[m]=serverStart>0?serverStart:(Number(localStorage.getItem(KEY(m))||0)||Date.now());
      }
      running[m]=on;
      setVisual(m,on);
    }catch(e){}
  }
  window.fsTimerV16Sync=sync;

  // One authoritative display clock. Other legacy scripts may poll status,
  // but they cannot make the displayed elapsed time jump because this clock
  // keeps its own start timestamp until the server reports OFF.
  setInterval(()=>{draw('PAPER');draw('LIVE')},250);
  setInterval(()=>{sync('PAPER');sync('LIVE')},3000);

  // Keep the existing ON/OFF handlers, but synchronize the authoritative clock
  // immediately after a successful state change.
  const oldToggle=window.toggleRun;
  window.toggleRun=async function(mode){
    const result=oldToggle?await oldToggle(mode):false;
    setTimeout(()=>sync(mode),100);
    return result;
  };

  // A clean test build: discard stale browser-side timer/session timestamps.
  // Server-side PAPER state is still the source of truth for whether it runs.
  MODES.forEach(m=>{running[m]=false;starts[m]=null;draw(m)});
  sync('PAPER');sync('LIVE');
})();
</script>'''

    def endpoint(*args, **kwargs):
        response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
        html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)
        # The legacy UI has several timer implementations layered on top of one another.
        # Remove only the explicit final timer scripts; the original ON/OFF handlers remain.
        html = re.sub(r'<script id="fs-ui-v12-js">.*?</script>', '', html, flags=re.S)
        html = re.sub(r'<script id="fs-final-control-js">.*?</script>', '', html, flags=re.S)
        html = html.replace('</body>', TIMER_JS + '</body>', 1)
        return HTMLResponse(content=html, headers={'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0','Pragma':'no-cache','Expires':'0'})

    endpoint._fs_timer_stability_v16 = True
    route.endpoint = endpoint
