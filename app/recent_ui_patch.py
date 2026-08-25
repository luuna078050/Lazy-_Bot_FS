from __future__ import annotations
import inspect
from fastapi.responses import HTMLResponse
from fastapi.routing import request_response


def install(app):
    route=next((r for r in app.router.routes if getattr(r,'path',None)=='/'),None)
    if route is None or not hasattr(route,'endpoint'): return
    original=route.endpoint
    if getattr(original,'_fs_recent_ui_patch',False): return
    def endpoint(*args,**kwargs):
        response=original() if not inspect.signature(original).parameters else original(*args,**kwargs)
        html=response.body.decode('utf-8') if isinstance(response,HTMLResponse) and isinstance(response.body,(bytes,bytearray)) else str(response)
        js=r'''<script id="fs-recent-clean-js">
(function(){
 function clean(){
  const card=document.getElementById('fsRecentWrap'); if(!card||card.dataset.fsRecentClean)return;
  card.dataset.fsRecentClean='1';
  card.innerHTML='<div class="title">📜 ПОСЛЕДНИЕ ЗАКРЫТЫЕ СДЕЛКИ <span style="color:#777">· 15 МИН</span></div><button id="fsRecentToggle" class="fs-recent-toggle">Показать последние 5</button><div id="fsRecentList" style="display:none"></div>';
  const list=document.getElementById('fsRecentList'),btn=document.getElementById('fsRecentToggle'); let open=false;
  async function load(){try{const mode=localStorage.getItem('fsLastReportMode')||'PAPER';const r=await fetch('/api/session/report/'+mode,{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error('report');const since=Date.now()-900000;const rows=(d.trades||[]).filter(x=>{const t=Date.parse(x.closed_at||'');return !Number.isFinite(t)||t>=since}).slice(-5).reverse();list.innerHTML=rows.length?rows.map(x=>'<div class="fs-recent-row"><b>'+String(x.symbol||'—')+'</b> · '+String(x.timeframe||'3m')+' · '+(Number(x.net_pnl||0)>=0?'+':'')+Number(x.net_pnl||0).toFixed(4)+' USDT · '+String(x.reason||'—')+'</div>').join(''):'<div class="muted">Нет закрытых сделок за последние 15 минут.</div>'}catch(e){list.innerHTML='<div class="muted">Нет данных о закрытых сделках.</div>'}}
  btn.onclick=()=>{open=!open;btn.textContent=open?'Скрыть':'Показать последние 5';list.style.display=open?'block':'none';if(open)load()};
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(clean,80));else setTimeout(clean,80);
})();
</script>'''
        html=html.replace('</body>',js+'</body>',1)
        headers=dict(getattr(response,'headers',{}) or {})
        for k in ('content-length','Content-Length','content-type','Content-Type'):headers.pop(k,None)
        headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
        return HTMLResponse(content=html,status_code=getattr(response,'status_code',200),headers=headers,media_type='text/html')
    endpoint._fs_recent_ui_patch=True
    route.endpoint=endpoint;route.app=request_response(endpoint)
