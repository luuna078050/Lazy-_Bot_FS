from __future__ import annotations

from fastapi.responses import HTMLResponse
from fastapi.routing import request_response
import inspect


def install(app):
    for route in list(app.router.routes):
        if getattr(route, 'path', None) != '/' or not hasattr(route, 'endpoint'):
            continue
        original = route.endpoint
        if getattr(original, '_allocation_fix_wrapped', False):
            return

        def endpoint(*args, **kwargs):
            response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
            html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)

            old = "if(Math.abs(s-100)>.01)return alert(m+': нужно 100%, сейчас '+s.toFixed(2)+'%');"
            new = "if(Math.abs(s-100)>.01){if(s>100){const k=100/s;slots.forEach(x=>{if(x.p&&x.mode===m)x.v=+(x.v*k).toFixed(8)});save();render();c=cfg(m);s=c.allocations.reduce((a,b)=>a+b,0)}if(Math.abs(s-100)>.01)return alert(m+': нужно 100%, сейчас '+s.toFixed(2)+'%');}"
            if old in html:
                html = html.replace(old, new, 1)

            # Make the allocation state visible immediately, so an accidental
            # over-allocation cannot silently block PAPER/LIVE launch.
            css = "<style>.allocation-fix-note{margin-top:6px;color:#aaa;font-size:11px}</style>"
            html = html.replace('</head>', css + '</head>', 1)
            js = "<script>(function(){document.addEventListener('DOMContentLoaded',function(){var t=document.getElementById('total');if(t){t.insertAdjacentHTML('afterend','<div class=\"allocation-fix-note\">Если сумма выше 100%, запуск автоматически нормализует доли до 100% с сохранением пропорций.</div>')}})})();</script>"
            html = html.replace('</body>', js + '</body>', 1)

            route_response = HTMLResponse(content=html, status_code=getattr(response, 'status_code', 200), headers=dict(getattr(response, 'headers', {}) or {}), media_type='text/html')
            return route_response

        endpoint._allocation_fix_wrapped = True
        route.endpoint = endpoint
        route.app = request_response(endpoint)
        return
    raise RuntimeError('Fast Scalper root route not found for allocation fix patch')
