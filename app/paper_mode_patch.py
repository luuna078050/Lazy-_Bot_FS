from __future__ import annotations

from fastapi.responses import HTMLResponse
from fastapi.routing import request_response
import inspect


def install(app):
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
                css = r'''<style>.paper-mode{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:9px 0 0 50px;padding:6px 9px;width:max-content;max-width:calc(100% - 58px);border:1px solid #6b171b;border-radius:9px;background:rgba(0,0,0,.45);box-shadow:0 0 10px rgba(255,0,0,.12)}.pm-label{font-size:11px;font-weight:900;letter-spacing:.8px;color:#ffb300}.pm-toggle{display:inline-flex;align-items:center;gap:6px;width:auto;margin:0;padding:5px 9px;border:1px solid #555;background:#1a1b1e;color:#aaa;border-radius:999px;font-weight:900;cursor:pointer}.pm-toggle.on{border-color:#ffb300;color:#ffd04d;background:#332506}.pm-dot{width:8px;height:8px;border-radius:50%;background:#666}.pm-toggle.on .pm-dot{background:#ffb300;box-shadow:0 0 8px #ffb300}.pm-note{font-size:10px;color:#888}.top-select{float:right;border:1px solid #ffb300;background:#241b05;color:#ffd04d;border-radius:6px;padding:5px 8px;font-size:11px;font-weight:900;cursor:pointer}.top-select.selected{background:#0f6b35;border-color:#22e36f;color:#fff}.top-addbar{display:flex;gap:6px;align-items:center;margin:8px 0;padding:7px;border:1px solid #351014;border-radius:8px;background:#070809}.top-addbar input{flex:1;min-width:0;background:#151619;color:#fff;border:1px solid #5a1418;border-radius:6px;padding:7px}.top-addbar button{border:1px solid #8c1017;background:#671015;color:#fff;border-radius:6px;padding:7px 10px;font-weight:900}.paper-virtual .metric,.paper-virtual .pnl{box-shadow:0 0 12px rgba(255,179,0,.10) inset}.paper-virtual #pnl{color:#ffb300}@media(max-width:500px){.paper-mode{margin-left:0;max-width:100%}.top-select{float:none;display:block;margin-top:5px}}</style>'''
                html = html.replace('</style></head>', css + '</style></head>', 1)
                js = r'''<script>(function(){
const PM_KEY='fastScalperPaperMode';
function pmOn(){return localStorage.getItem(PM_KEY)==='1'}
function applyPaperMode(){const on=pmOn();document.body.classList.toggle('paper-virtual',on);const b=document.getElementById('paperModeToggle'),t=document.getElementById('paperModeText'),n=document.getElementById('paperModeNote');if(b){b.classList.toggle('on',on);b.setAttribute('aria-pressed',String(on));}if(t)t.textContent=on?'ON':'OFF';if(n)n.textContent=on?'ВИРТУАЛЬНЫЕ СРЕДСТВА • реальные котировки':'без реальных активов';
const labels=document.querySelectorAll('.metric small');labels.forEach(el=>{const base=el.dataset.pmBase||(el.dataset.pmBase=el.textContent);if(on&&/БАЛАНС АККАУНТА|БАЛАНС БОТА/.test(base))el.textContent=base.replace('БАЛАНС','ВИРТУАЛЬНЫЙ БАЛАНС');else if(!on)el.textContent=base});
const pnl=document.querySelector('.pnl .title');if(pnl){const base=pnl.dataset.pmBase||(pnl.dataset.pmBase=pnl.textContent);pnl.textContent=on?'PnL • VIRTUAL':base}}
window.togglePaperMode=function(){localStorage.setItem(PM_KEY,pmOn()?'0':'1');applyPaperMode()};
window.selectTopPair=function(symbol){symbol=String(symbol||'').trim().toUpperCase().replace('-', '/');if(!symbol)return;if(typeof slots==='undefined'||typeof render!=='function'){alert('Интерфейс слотов ещё загружается');return}let idx=slots.findIndex(x=>!x.p);if(idx<0){idx=slots.findIndex(x=>x.p===symbol);if(idx>=0){alert(symbol+' уже выбрана');return}alert('Все 5 слотов заняты. Очистите один слот или измените пару.');return}slots[idx].p=symbol;save();render();setTimeout(markTopSelections,20)};
window.addManualPair=function(){const input=document.getElementById('manualPair');if(input)window.selectTopPair(input.value)};
function markTopSelections(){document.querySelectorAll('[data-top-symbol]').forEach(btn=>{const s=btn.getAttribute('data-top-symbol');const chosen=typeof slots!=='undefined'&&slots.some(x=>x.p===s);btn.classList.toggle('selected',chosen);btn.textContent=chosen?'✓ ВЫБРАНО':'ВЫБРАТЬ'})}
function enhanceTop(){const top=document.getElementById('top');if(!top||top.dataset.enhanced==='1')return;if(!top.innerHTML.trim())return;top.dataset.enhanced='1';const boxes=top.querySelectorAll('.pos');boxes.forEach(box=>{const b=box.querySelector('b');if(!b)return;const symbol=b.textContent.replace(/^#\d+\s*/,'').trim();const btn=document.createElement('button');btn.className='top-select';btn.dataset.topSymbol=symbol;btn.textContent='ВЫБРАТЬ';btn.type='button';btn.onclick=()=>window.selectTopPair(symbol);box.insertBefore(btn,box.firstChild);});markTopSelections()}
function addManual(){const top=document.getElementById('top');if(!top||document.getElementById('topManualAdd'))return;const bar=document.createElement('div');bar.className='top-addbar';bar.id='topManualAdd';bar.innerHTML='<input id="manualPair" placeholder="Добавить пару, например BTC/USDT"><button type="button" onclick="addManualPair()">ДОБАВИТЬ</button>';top.prepend(bar);}
window.addEventListener('DOMContentLoaded',function(){applyPaperMode();enhanceTop();addManual();const top=document.getElementById('top');if(top){new MutationObserver(()=>{enhanceTop();markTopSelections();addManual()}).observe(top,{childList:true,subtree:true})}});setTimeout(function(){applyPaperMode();enhanceTop();addManual()},100);
})();</script>'''
                html = html.replace('</body>', js + '</body>', 1)
                # The body was modified after the original HTMLResponse calculated
                # Content-Length. Do not copy that stale header into the new response.
                headers = dict(getattr(response, 'headers', {}) or {})
                headers.pop('content-length', None)
                headers.pop('Content-Length', None)
                headers.pop('content-type', None)
                headers.pop('Content-Type', None)
                return HTMLResponse(content=html, status_code=getattr(response, 'status_code', 200), headers=headers, media_type='text/html')

            endpoint._paper_mode_wrapped = True
            route.endpoint = endpoint
            route.app = request_response(endpoint)
            return
    raise RuntimeError('Fast Scalper root route not found for Paper Mode patch')
