from __future__ import annotations

from fastapi.responses import HTMLResponse
from fastapi.routing import request_response
import inspect


def install(app):
    # Wrap only the visual root. All trading/report endpoints stay untouched.
    for route in list(app.router.routes):
        if getattr(route, 'path', None) == '/' and hasattr(route, 'endpoint'):
            original = route.endpoint
            if getattr(original, '_paper_mode_wrapped', False):
                return

            def endpoint(*args, **kwargs):
                response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
                html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)
                marker = '<div class="tag">ЛОВИМ РАКЕТЫ НА ВЗЛЁТЕ</div>'
                inject = r'''<div class="paper-mode" id="paperModeBox"><span class="pm-label">PAPER MODE</span><button id="paperModeToggle" class="pm-toggle" type="button" aria-pressed="false" onclick="togglePaperMode()"><span class="pm-dot"></span><span id="paperModeText">OFF</span></button><span class="pm-note" id="paperModeNote">без реальных активов</span></div>'''
                html = html.replace(marker, marker + inject, 1)
                css = r'''<style>.paper-mode{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:9px 0 0 50px;padding:6px 9px;width:max-content;max-width:calc(100% - 58px);border:1px solid #6b171b;border-radius:9px;background:rgba(0,0,0,.45);box-shadow:0 0 10px rgba(255,0,0,.12)}.pm-label{font-size:11px;font-weight:900;letter-spacing:.8px;color:#ffb300}.pm-toggle{display:inline-flex;align-items:center;gap:6px;width:auto;margin:0;padding:5px 9px;border:1px solid #555;background:#1a1b1e;color:#aaa;border-radius:999px;font-weight:900;cursor:pointer}.pm-toggle.on{border-color:#ffb300;color:#ffd04d;background:#332506}.pm-dot{width:8px;height:8px;border-radius:50%;background:#666}.pm-toggle.on .pm-dot{background:#ffb300;box-shadow:0 0 8px #ffb300}.pm-note{font-size:10px;color:#888}.virtual-mark{color:#ffb300;font-size:.8em;font-weight:900;margin-left:4px}.paper-virtual .metric,.paper-virtual .pnl{box-shadow:0 0 12px rgba(255,179,0,.10) inset}.paper-virtual #pnl{color:#ffb300}.paper-virtual .pm-hidden-live{opacity:.65}@media(max-width:500px){.paper-mode{margin-left:0;max-width:100%}}</style>'''
                html = html.replace('</style></head>', css + '</style></head>', 1)
                js = r'''<script>(function(){
const PM_KEY='fastScalperPaperMode';
function pmOn(){return localStorage.getItem(PM_KEY)==='1'}
function applyPaperMode(){const on=pmOn();document.body.classList.toggle('paper-virtual',on);const b=document.getElementById('paperModeToggle'),t=document.getElementById('paperModeText'),n=document.getElementById('paperModeNote');if(b){b.classList.toggle('on',on);b.setAttribute('aria-pressed',String(on));}if(t)t.textContent=on?'ON':'OFF';if(n)n.textContent=on?'ВИРТУАЛЬНЫЕ СРЕДСТВА • реальные котировки':'без реальных активов';
const labels=document.querySelectorAll('.metric small');labels.forEach(el=>{const base=el.dataset.pmBase||(el.dataset.pmBase=el.textContent);if(on){if(/БАЛАНС АККАУНТА|БАЛАНС БОТА/.test(base))el.textContent=base.replace('БАЛАНС','ВИРТУАЛЬНЫЙ БАЛАНС');}else el.textContent=base});
const pnl=document.querySelector('.pnl .title');if(pnl){const base=pnl.dataset.pmBase||(pnl.dataset.pmBase=pnl.textContent);pnl.textContent=on?'PnL • VIRTUAL':base}
const result=document.getElementById('result');if(result&&!result.dataset.pmPatched){result.dataset.pmPatched='1';const obs=new MutationObserver(()=>{if(!pmOn())return;result.querySelectorAll('b').forEach(b=>{if(!b.previousSibling||!String(b.previousSibling.textContent||'').includes('VIRTUAL')){}})});obs.observe(result,{childList:true,subtree:true})}}
window.togglePaperMode=function(){const next=!pmOn();localStorage.setItem(PM_KEY,next?'1':'0');applyPaperMode();};
window.addEventListener('DOMContentLoaded',function(){applyPaperMode();const realStart=window.start;if(typeof realStart==='function'&&!window.__paperStartWrapped){window.__paperStartWrapped=true;window.start=function(mode){if(pmOn()&&mode==='LIVE'){return realStart('PAPER')}return realStart(mode)}}});setTimeout(applyPaperMode,50);})();</script>'''
                html = html.replace('</body>', js + '</body>', 1)
                return HTMLResponse(content=html, status_code=getattr(response, 'status_code', 200), headers=dict(getattr(response, 'headers', {}) or {}), media_type='text/html')

            endpoint._paper_mode_wrapped = True
            route.endpoint = endpoint
            route.app = request_response(endpoint)
            return
    # If root route isn't present yet, fail loudly rather than silently changing nothing.
    raise RuntimeError('Fast Scalper root route not found for Paper Mode patch')
