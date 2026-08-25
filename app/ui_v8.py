from __future__ import annotations

from fastapi.responses import HTMLResponse
from .ui_v7 import app, SKIN as BASE_SKIN

for route in list(app.router.routes):
    if getattr(route, 'path', None) == '/':
        app.router.routes.remove(route)

SKIN = BASE_SKIN.replace("fsSlotsV2", "fsSlotsV4")

PATCH = r'''<style>
.fs-top10{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:8px}
.fs-top10-card{min-width:0;border:1px solid #451015;border-radius:10px;background:#08090a;padding:8px}
.fs-top10-head{display:flex;align-items:center;justify-content:space-between;gap:5px;min-width:0}
.fs-top10-pair{font-weight:900;color:#fff;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fs-top10-score{flex:0 0 auto;color:#72ff9b;border:1px solid #22c55e;background:#082611;border-radius:5px;padding:2px 5px;font-weight:900;font-size:12px}
.fs-top10-meta{margin-top:5px;color:#aaa;font-size:10px;line-height:1.35;display:grid;grid-template-columns:1fr 1fr;gap:2px 6px}
.fs-top10-pnl{color:#ffd04d;font-weight:900}
.fs-top10-pick{width:100%;margin-top:7px;border:1px solid #ffb300;background:#281d06;color:#ffd04d;border-radius:6px;padding:6px 4px;font-weight:900;font-size:11px;cursor:pointer}
.fs-top10-pick.selected{background:#0e793b;border-color:#22e36f;color:#fff}
@media(max-width:600px){.fs-top10{grid-template-columns:repeat(2,minmax(0,1fr));gap:5px}.fs-top10-card{padding:6px}.fs-top10-pair{font-size:12px}.fs-top10-score{font-size:11px;padding:2px 4px}.fs-top10-meta{font-size:9px}.fs-top10-pick{font-size:10px;padding:5px 2px}}
</style>
<script>
(function(){
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  function num(v,d=2){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—'}
  function rowsFrom(d){return (d.candidates20||d.top10||d.top5||d.top||[]).slice(0,10)}
  function render(rows){
    const top=$('top'); if(!top)return;
    if(!rows.length){top.innerHTML='<div class="muted">Радар пока не дал рекомендаций</div>';return}
    top.innerHTML='<div class="fs-top10">'+rows.map((x,i)=>{
      const symbol=String(x.symbol||'—');
      const signal=String(x.signal||'WAIT');
      const score=Number(x.score);
      const target=Number(x.estimated_target_pct);
      const pnl100=Number(x.estimated_pnl_usdt_100 ?? (target/100*100));
      const velocity=Number(x.expected_pnl_per_min_100);
      const activity=Number(x.trade_velocity_score);
      return '<div class="fs-top10-card">'
        +'<div class="fs-top10-head"><div class="fs-top10-pair">🔥 #'+(i+1)+' '+esc(symbol)+'</div><span class="fs-top10-score">'+(Number.isFinite(score)?score.toFixed(0):'—')+'</span></div>'
        +'<div class="fs-top10-meta">'
        +'<span>Сигнал: '+esc(signal)+'</span>'
        +'<span>Активность: '+(Number.isFinite(activity)?activity.toFixed(0):'—')+'</span>'
        +'<span>Цель: '+(Number.isFinite(target)?target.toFixed(3):'—')+'%</span>'
        +'<span class="fs-top10-pnl">$100: +$'+(Number.isFinite(pnl100)?pnl100.toFixed(2):'—')+'</span>'
        +'<span>$/мин: '+(Number.isFinite(velocity)?velocity.toFixed(2):'—')+'</span>'
        +'</div>'
        +'<button class="fs-top10-pick top-select" data-symbol="'+esc(symbol)+'" onclick="pick(this.dataset.symbol)">ВЫБРАТЬ</button>'
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