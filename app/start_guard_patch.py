from __future__ import annotations
from fastapi.responses import HTMLResponse
from fastapi.routing import request_response


def install(app):
    for route in list(app.router.routes):
        if getattr(route, 'path', None) != '/' or not hasattr(route, 'endpoint'):
            continue
        original = route.endpoint
        if getattr(original, '_start_guard_v1', False):
            return
        def endpoint(*args, **kwargs):
            response = original() if not args and not kwargs else original(*args, **kwargs)
            html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)
            js = r'''<script>
(function(){
  const q=id=>document.getElementById(id);
  const timer={PAPER:null,LIVE:null};
  function paint(mode,on,startTs){
    const low=mode.toLowerCase(), sw=q(low+'Switch'), tx=q(low+'SwitchText'), st=q(low+'Status'), tm=q(low+'Timer');
    if(sw) sw.classList.toggle('on',!!on);
    if(tx) tx.textContent=on?'ON':'OFF';
    if(st){st.textContent=mode+' '+(on?'работает':'остановлен');st.classList.toggle('on',!!on)}
    clearInterval(timer[mode]);
    if(!on){localStorage.removeItem(mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive');if(tm)tm.textContent='00:00:00';return}
    const ts=Number(startTs)||Date.now(); localStorage.setItem(mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive',String(ts));
    const tick=()=>{let n=Math.max(0,Math.floor((Date.now()-ts)/1000));let h=Math.floor(n/3600),m=Math.floor((n%3600)/60),s=n%60;if(tm)tm.textContent=[h,m,s].map(x=>String(x).padStart(2,'0')).join(':')};
    tick(); timer[mode]=setInterval(tick,1000);
  }
  async function sync(mode){
    try{
      const r=await fetch('/api/session/report/'+mode,{cache:'no-store'}); if(!r.ok)return false;
      const d=await r.json();
      paint(mode,!!d.running,d.started_at?Number(d.started_at)*1000:Date.now());
      if(window.fsV6Report) window.fsV6Report(d);
      return !!d.running;
    }catch(e){return false}
  }
  window.start=async function(mode){
    try{
      const c=cfg(mode), total=c.allocations.reduce((a,b)=>a+b,0);
      if(!c.pairs.length){alert('Нет выбранных '+mode+' пар');paint(mode,false);return false}
      if(Math.abs(total-100)>.01){alert(mode+': нужно 100%, сейчас '+total.toFixed(2)+'%');paint(mode,false);return false}
      if(mode==='LIVE'){
        c.api_key=q('key')?.value||''; c.api_secret=q('secret')?.value||'';
        if(!c.api_key||!c.api_secret){alert('Для LIVE нужны API Key и Secret');paint(mode,false);return false}
      }
      const r=await fetch('/api/'+mode.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c),cache:'no-store'});
      let d={}; try{d=await r.json()}catch(e){}
      if(!r.ok || !d.running){alert(d.detail||'Ошибка запуска '+mode);paint(mode,false);return false}
      await sync(mode);
      return true;
    }catch(e){alert('Ошибка запуска '+mode+': '+e.message);paint(mode,false);return false}
  };
  window.stop=async function(mode){
    try{const r=await fetch('/api/'+mode.toLowerCase()+'/stop',{method:'POST',cache:'no-store'});paint(mode,false);await sync(mode);return r.ok}catch(e){paint(mode,false);return false}
  };
  window.toggleRun=async function(mode){
    const sw=q(mode.toLowerCase()+'Switch');
    if(sw&&sw.classList.contains('on')) return window.stop(mode);
    return window.start(mode);
  };
  window.emergency=async function(){
    try{await Promise.all(['PAPER','LIVE'].map(m=>fetch('/api/'+m.toLowerCase()+'/emergency-stop',{method:'POST',cache:'no-store'})))}finally{paint('PAPER',false);paint('LIVE',false);await sync('PAPER');await sync('LIVE')}
  };
  async function boot(){await sync('PAPER');await sync('LIVE')}
  boot(); setInterval(()=>{sync('PAPER');sync('LIVE')},1500);
})();
</script>'''
            return HTMLResponse(content=html.replace('</body>',js+'</body>',1),status_code=getattr(response,'status_code',200),headers=dict(getattr(response,'headers',{}) or {}),media_type='text/html')
        endpoint._start_guard_v1=True
        route.endpoint=endpoint
        route.app=request_response(endpoint)
        return
    raise RuntimeError('Fast Scalper root route not found for start guard patch')
