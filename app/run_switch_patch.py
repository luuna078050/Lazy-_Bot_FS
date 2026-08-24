from __future__ import annotations
from fastapi.responses import HTMLResponse
from fastapi.routing import request_response
import inspect


def install(app):
    for route in list(app.router.routes):
        if getattr(route, 'path', None) != '/' or not hasattr(route, 'endpoint'):
            continue
        original = route.endpoint
        if getattr(original, '_run_switch_v6_wrapped', False):
            return
        def endpoint(*args, **kwargs):
            response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
            html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)
            js = r'''<script>
(function(){
  async function sync(){
    for(const mode of ['PAPER','LIVE']){
      try{const d=await (await fetch('/api/session/report/'+mode,{cache:'no-store'})).json(); if(window.fsV6Report)window.fsV6Report(d);}catch(e){}
    }
  }
  sync(); setInterval(sync,1500);
})();
</script>'''
            # The HTML body is changed after the previous response calculated
            # Content-Length. Remove the stale header before sending the new body.
            headers = dict(getattr(response, 'headers', {}) or {})
            headers.pop('content-length', None)
            headers.pop('Content-Length', None)
            headers.pop('content-type', None)
            headers.pop('Content-Type', None)
            return HTMLResponse(content=html.replace('</body>',js+'</body>',1),status_code=getattr(response,'status_code',200),headers=headers,media_type='text/html')
        endpoint._run_switch_v6_wrapped = True
        route.endpoint = endpoint
        route.app = request_response(endpoint)
        return
    raise RuntimeError('Fast Scalper root route not found for run switch patch')
