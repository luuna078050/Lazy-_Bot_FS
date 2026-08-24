from __future__ import annotations

from fastapi.responses import HTMLResponse
from fastapi.routing import request_response
import inspect


def install(app):
    for route in list(app.router.routes):
        if getattr(route, 'path', None) != '/' or not hasattr(route, 'endpoint'):
            continue
        original = route.endpoint
        if getattr(original, '_pair_fix_wrapped', False):
            return

        def endpoint(*args, **kwargs):
            response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
            html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)
            js = r'''<script>
(function(){
  function installPairPicker(){
    const top=document.getElementById('top');
    if(!top || top.dataset.pairFix==='1') return;
    top.dataset.pairFix='1';
    top.addEventListener('click', function(ev){
      const btn=ev.target.closest('.top-select,[data-top-symbol]');
      if(!btn) return;
      const symbol=String(btn.dataset.symbol||btn.dataset.topSymbol||'').trim().toUpperCase().replace('-', '/');
      if(!symbol) return;
      ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation();
      if(typeof slots==='undefined' || typeof save!=='function' || typeof render!=='function'){
        alert('Слоты ещё загружаются. Нажми ВЫБРАТЬ ещё раз через секунду.'); return;
      }
      if(slots.some(x=>x.p===symbol)){ btn.textContent='✓ ВЫБРАНО'; btn.classList.add('selected'); return; }
      let idx=slots.findIndex(x=>!x.p);
      if(idx<0){ alert('Все 5 слотов заняты. Очисти один слот.'); return; }
      slots[idx].p=symbol;
      const chosen=slots.filter(x=>x.p && x.mode==='PAPER');
      if(chosen.length && chosen.every(x=>x.input==='pct')){
        const share=+(100/chosen.length).toFixed(8);
        chosen.forEach(x=>x.v=share);
      }
      save(); render();
    }, true);
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',installPairPicker); else installPairPicker();
  setTimeout(installPairPicker,250);
})();
</script>'''
            html = html.replace('</body>', js + '</body>', 1)
            headers = dict(getattr(response, 'headers', {}) or {})
            headers.pop('content-length', None); headers.pop('Content-Length', None)
            headers.pop('content-type', None); headers.pop('Content-Type', None)
            headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
            return HTMLResponse(content=html, status_code=getattr(response,'status_code',200), headers=headers, media_type='text/html')

        endpoint._pair_fix_wrapped=True
        route.endpoint=endpoint
        route.app=request_response(endpoint)
        return
    raise RuntimeError('Fast Scalper root route not found for pair picker patch')
