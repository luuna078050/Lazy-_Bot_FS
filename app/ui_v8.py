from __future__ import annotations

from fastapi.responses import HTMLResponse
from .ui_v7 import app, SKIN as BASE_SKIN

for route in list(app.router.routes):
    if getattr(route, 'path', None) == '/':
        app.router.routes.remove(route)

SKIN = BASE_SKIN.replace("fsSlotsV2", "fsSlotsV3")

PATCH = r'''<style>
.fs-top6{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:8px}
.fs-top6-card{min-width:0;border:1px solid #451015;border-radius:10px;background:#08090a;padding:8px}
.fs-top6-head{display:flex;align-items:center;justify-content:space-between;gap:5px;min-width:0}
.fs-top6-pair{font-weight:900;color:#fff;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fs-top6-score{flex:0 0 auto;color:#ffd04d;border:1px solid #ffb300;background:#281d06;border-radius:5px;padding:2px 5px;font-weight:900;font-size:12px}
.fs-top6-meta{margin-top:5px;color:#aaa;font-size:10px;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fs-top6-pick{width:100%;margin-top:7px;border:1px solid #ffb300;background:#281d06;color:#ffd04d;border-radius:6px;padding:6px 4px;font-weight:900;font-size:11px;cursor:pointer}
.fs-top6-pick.selected{background:#0e793b;border-color:#22e36f;color:#fff}
@media(max-width:600px){.fs-top6{grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}.fs-top6-card{padding:6px}.fs-top6-pair{font-size:12px}.fs-top6-score{font-size:11px;padding:2px 4px}.fs-top6-meta{font-size:9px}.fs-top6-pick{font-size:10px;padding:5px 2px}}
</style>
<script>
(function(){
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  function price(v){
    const n=Number(v);
    if(!Number.isFinite(n)) return '—';
    if(n>=1000) return n.toFixed(2);
    if(n>=1) return n.toFixed(4).replace(/0+$/,'').replace(/\.$/,'');
    if(n>=0.01) return n.toFixed(5).replace(/0+$/,'').replace(/\.$/,'');
    if(n>=0.0001) return n.toFixed(6).replace(/0+$/,'').replace(/\.$/,'');
    return n.toPrecision(6);
  }
  function score(v){const n=Number(v);return Number.isFinite(n)?n.toFixed(0):'—'}
  function rowsFrom(d){return (d.candidates20||d.top5||d.top||[]).slice(0,6)}
  function render(rows){
    const top=$('top'); if(!top)return;
    if(!rows.length){top.innerHTML='<div class="muted">Радар пока не дал рекомендаций</div>';return}
    top.innerHTML='<div class="fs-top6">'+rows.map((x,i)=>{
      const symbol=String(x.symbol||'—');
      const signal=String(x.signal||'WAIT');
      const entry=price(x.estimated_entry);
      const exit=price(x.estimated_exit);
      const hold=Number(x.hold_seconds)||180;
      return '<div class="fs-top6-card">'
        +'<div class="fs-top6-head"><div class="fs-top6-pair">#'+(i+1)+' '+esc(symbol)+'</div><span class="fs-top6-score">'+score(x.score)+'</span></div>'
        +'<div class="fs-top6-meta">'+esc(signal)+' · '+entry+' → '+exit+' · '+hold+'с</div>'
        +'<button class="fs-top6-pick top-select" data-symbol="'+esc(symbol)+'" onclick="pick(this.dataset.symbol)">ВЫБРАТЬ</button>'
        +'</div>'
    }).join('')+'</div>';
    if(window.mark)window.mark();
  }
  window.recs=async function(){
    try{
      const r=await fetch('/api/recommendations?limit=20',{cache:'no-store'});
      const d=await r.json();
      if(!r.ok) throw new Error(d.detail||'Ошибка радара');
      render(rowsFrom(d));
    }catch(e){
      const top=$('top'); if(top)top.innerHTML='<div class="error">Ошибка радара: '+esc(e.message)+'</div>';
    }
  };
  window.recs();
})();
</script>'''

SKIN = SKIN.replace('</body>', PATCH + '</body>', 1)

@app.get('/', response_class=HTMLResponse)
def home():
    return HTMLResponse(content=SKIN, headers={'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0','Pragma':'no-cache','Expires':'0'})
