from __future__ import annotations

from fastapi.responses import HTMLResponse
from fastapi.routing import request_response
import inspect


def install(app):
    for route in list(app.router.routes):
        if getattr(route, 'path', None) != '/' or not hasattr(route, 'endpoint'):
            continue
        original = route.endpoint
        if getattr(original, '_final_ui_patch_wrapped', False):
            return

        def endpoint(*args, **kwargs):
            response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
            html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)

            css = r'''<style id="fs-final-ui">
.fs-top6{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:8px}
.fs-top6-card{min-width:0;border:1px solid #451015;border-radius:10px;background:#08090a;padding:9px}
.fs-top6-head{display:flex;align-items:center;justify-content:space-between;gap:6px}
.fs-top6-rank{font-weight:900;color:#fff;font-size:14px}.fs-top6-score{color:#ffd04d;font-weight:900;font-size:16px}
.fs-top6-meta{color:#aaa;font-size:10px;line-height:1.35;margin-top:4px}.fs-top6-pick{width:100%;margin-top:7px;border:1px solid #ffb300;background:#281d06;color:#ffd04d;border-radius:7px;padding:6px;font-weight:900}
.fs-top6-pick.selected{background:#0e793b;border-color:#22e36f;color:#fff}
.fs-hidden-fix{display:none!important}
@media(max-width:520px){.fs-top6{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.fs-top6-card{padding:7px}.fs-top6-rank{font-size:12px}.fs-top6-score{font-size:14px}.fs-top6-meta{font-size:9px}}
</style>'''
            html = html.replace('</style></head>', css + '</style></head>', 1)

            js = r'''<script id="fs-final-ui-js">
(function(){
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');

  // v6 refresh still expects these two legacy nodes. Keep them harmlessly in DOM
  // so the report cannot abort with "Cannot set properties of null".
  function addLegacyNodes(){
    if(!$('free')){const x=document.createElement('span');x.id='free';x.className='fs-hidden-fix';document.body.appendChild(x)}
    if(!$('usedbar')){const x=document.createElement('span');x.id='usedbar';x.className='fs-hidden-fix';document.body.appendChild(x)}
  }

  // Exactly six radar cards: two columns x three rows. Trading slots remain six
  // in the UI, while the active trading engine can still use up to five pairs.
  window.renderFastTop6=function(rows){
    const top=$('top'); if(!top)return;
    rows=(rows||[]).slice(0,6);
    if(!rows.length){top.innerHTML='<div class="muted">Радар пока не дал рекомендаций</div>';return}
    top.innerHTML='<div class="fs-top6">'+rows.map((x,i)=>{
      const s=String(x.symbol||'—');
      const score=Number.isFinite(Number(x.score))?Number(x.score).toFixed(2):'—';
      return '<div class="fs-top6-card">'
        +'<div class="fs-top6-head"><span class="fs-top6-rank">#'+(i+1)+' '+esc(s)+'</span><span class="fs-top6-score">'+score+'</span></div>'
        +'<div class="fs-top6-meta">'+esc(x.signal||'WAIT')+' • вход '+esc(x.estimated_entry??'—')+' → '+esc(x.estimated_exit??'—')+' • '+(x.hold_seconds||180)+'с</div>'
        +'<button class="fs-top6-pick top-select" data-symbol="'+esc(s)+'" onclick="pick(this.dataset.symbol)">ВЫБРАТЬ</button>'
        +'</div>';
    }).join('')+'</div>';
    if(window.mark)window.mark();
  };

  window.recs=async function(){
    try{
      const r=await fetch('/api/recommendations?limit=20',{cache:'no-store'});
      const d=await r.json(); if(!r.ok)throw new Error(d.detail||'Ошибка радара');
      window.renderFastTop6(d.candidates20||d.top5||[]);
    }catch(e){if($('top'))$('top').innerHTML='<div class="error">Ошибка радара: '+esc(e.message)+'</div>'}
  };

  // Automatic allocation: in AUTO mode, changing one selected pair redistributes
  // the remaining 100% proportionally among the other selected pairs. MANUAL mode
  // leaves the entered values untouched and allows totals below 100%.
  let adjusting=false;
  function autoMode(){
    const buttons=[...document.querySelectorAll('button')];
    const auto=buttons.find(b=>/АВТОРАСПРЕДЕЛЕНИЕ/i.test((b.textContent||'')));
    return !!(auto && (auto.classList.contains('on')||auto.classList.contains('active')||auto.getAttribute('aria-pressed')==='true'));
  }
  function redistribute(changedIndex){
    if(adjusting || !autoMode() || typeof slots==='undefined')return;
    const chosen=slots.map((x,i)=>({x,i})).filter(z=>z.x.p && z.x.mode==='PAPER');
    if(chosen.length<2)return;
    const changed=chosen.find(z=>z.i===changedIndex); if(!changed)return;
    const target=Math.max(0,Math.min(100,Number(changed.x.v)||0));
    const others=chosen.filter(z=>z.i!==changedIndex); if(!others.length)return;
    const oldSum=others.reduce((a,z)=>a+(Number(z.x.v)||0),0);
    const rest=100-target;
    adjusting=true;
    others.forEach((z,n)=>{
      const base=oldSum>0?(Number(z.x.v)||0)/oldSum:1/others.length;
      z.x.v=n===others.length-1?+(rest-others.slice(0,-1).reduce((a,q)=>a+(Number(q.x.v)||0),0)).toFixed(8):+(rest*base).toFixed(8);
    });
    if(typeof save==='function')save(); if(typeof render==='function')render();
    adjusting=false;
  }
  function bindAllocation(){
    const box=$('slots'); if(!box||box.dataset.fsAutoBound==='1')return;
    box.dataset.fsAutoBound='1';
    box.addEventListener('input',ev=>{
      const el=ev.target; if(!(el instanceof HTMLInputElement)||el.type!=='number')return;
      const slot=el.closest('.slot'); if(!slot||typeof slots==='undefined')return;
      const all=[...box.querySelectorAll('.slot')]; const idx=all.indexOf(slot);
      if(idx>=0)setTimeout(()=>redistribute(idx),0);
    });
  }

  function safeReport(){
    addLegacyNodes();
    // Existing refresh/report code is retained; this only makes its DOM contract safe.
    if(typeof window.refresh==='function'){
      try{const r=window.refresh();if(r&&typeof r.catch==='function')r.catch(()=>{})}catch(e){}
    }
  }

  function boot(){addLegacyNodes();bindAllocation();window.recs();safeReport();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
  setInterval(()=>{bindAllocation();},1000);
  setInterval(()=>{window.recs();},10000);
})();
</script>'''
            html = html.replace('</body>', js + '</body>', 1)

            headers = dict(getattr(response, 'headers', {}) or {})
            for k in ('content-length','Content-Length','content-type','Content-Type'):
                headers.pop(k, None)
            headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
            return HTMLResponse(content=html,status_code=getattr(response,'status_code',200),headers=headers,media_type='text/html')

        endpoint._final_ui_patch_wrapped=True
        route.endpoint=endpoint
        route.app=request_response(endpoint)
        return
    raise RuntimeError('Fast Scalper root route not found for final UI patch')
