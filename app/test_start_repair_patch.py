from __future__ import annotations

from fastapi.responses import HTMLResponse
from fastapi.routing import request_response
import inspect


def install(app):
    route = next((r for r in app.router.routes if getattr(r, 'path', None) == '/'), None)
    if route is None or not hasattr(route, 'endpoint'):
        return
    original = route.endpoint
    if getattr(original, '_test_start_repair', False):
        return

    def endpoint(*args, **kwargs):
        response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
        html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)
        js = r'''<script id="fs-test-start-repair">
(function(){
  function boot(){
    const $=id=>document.getElementById(id);
    function bind(id,mode){
      const old=$(id); if(!old) return;
      const b=old.cloneNode(true); old.replaceWith(b);
      b.addEventListener('click', async function(ev){
        ev.preventDefault(); ev.stopImmediatePropagation();
        const low=mode.toLowerCase();
        if(b.classList.contains('on')){
          try{
            const r=await fetch('/api/'+low+'/stop',{method:'POST',cache:'no-store'});
            if(!r.ok){alert('Не удалось остановить '+mode);return;}
            paint(false);
          }catch(e){alert('Ошибка остановки '+mode+': '+e.message)}
          return;
        }
        if(typeof cfg!=='function' && typeof window.cfg!=='function'){
          // Build a minimal payload directly from the visible slots.
        }
        let pairs=[],allocations=[],timeframes=[];
        try{
          const rows=[...document.querySelectorAll('#slots .slot')];
          rows.forEach(row=>{
            const p=row.querySelector('input[placeholder^="ПАРА"]');
            const n=row.querySelector('input[type="number"]');
            const tf=row.querySelector('.fs-slot-tf');
            if(p && p.value.trim()){
              pairs.push(p.value.trim().toUpperCase().replace('-', '/'));
              allocations.push(Number(n?.value)||0);
              timeframes.push(tf?.value||'3m');
            }
          });
        }catch(e){}
        if(!pairs.length){alert('Нет выбранных PAPER позиций');return;}
        let total=allocations.reduce((a,x)=>a+x,0);
        if(total<=0){const each=100/pairs.length;allocations=allocations.map(()=>each);total=100;}
        if(total>100.0001){alert('Сумма долей не может превышать 100%. Сейчас '+total.toFixed(2)+'%.');return;}
        const capital=Number($('capital')?.value)||0;
        if(capital<=0){alert('Укажи доступный баланс для PAPER.');return;}
        const payload={capital,pairs,allocations,timeframes,target_pnl_per_min_per_100:1.73,target_usdt:0.30,min_usdt:0.15,sl_pct:0.5,max_hold:180,fee_pct:0.10,timeframe:'3m'};
        try{
          b.disabled=true;
          const r=await fetch('/api/'+low+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),cache:'no-store'});
          const text=await r.text(); let d={}; try{d=JSON.parse(text)}catch(e){d={detail:text.slice(0,300)}}
          if(!r.ok || d.running===false){alert(d.detail||('Не удалось запустить '+mode));return;}
          localStorage.setItem('fsLastReportMode',mode); paint(true,d.started_at);
        }catch(e){alert('Ошибка запуска '+mode+': '+e.message)}
        finally{b.disabled=false}
      },true);
      function paint(on,started){
        b.classList.toggle('on',!!on);
        const tx=$(low+'SwitchText'),st=$(low+'Status');
        if(tx)tx.textContent=on?'ON':'OFF';
        if(st){st.textContent=mode+' '+(on?'работает':'остановлен');st.classList.toggle('on',!!on)}
        if(on && started){localStorage.setItem(mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive',String(Number(started)*1000));}
      }
      return {paint};
    }
    bind('paperSwitch','PAPER'); bind('liveSwitch','LIVE');
    const em=$('fsEmergency');
    if(em){const b=em.cloneNode(true);em.replaceWith(b);b.addEventListener('click',async function(ev){ev.preventDefault();ev.stopImmediatePropagation();await fetch('/api/paper/emergency-stop',{method:'POST',cache:'no-store'}).catch(()=>{});await fetch('/api/live/emergency-stop',{method:'POST',cache:'no-store'}).catch(()=>{});location.reload();},true)}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(boot,150));else setTimeout(boot,150);
})();
</script>'''
        html = html.replace('</body>', js + '</body>', 1)
        headers = dict(getattr(response, 'headers', {}) or {})
        for k in ('content-length','Content-Length','content-type','Content-Type'): headers.pop(k,None)
        headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
        return HTMLResponse(content=html,status_code=getattr(response,'status_code',200),headers=headers,media_type='text/html')

    endpoint._test_start_repair = True
    route.endpoint = endpoint
    route.app = request_response(endpoint)
