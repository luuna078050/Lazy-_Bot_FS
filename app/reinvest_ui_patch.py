from __future__ import annotations
import inspect
from fastapi.responses import HTMLResponse
from fastapi.routing import request_response


def install(app):
    route = next((r for r in app.router.routes if getattr(r, 'path', None) == '/'), None)
    if route is None or not hasattr(route, 'endpoint'):
        return
    original = route.endpoint
    if getattr(original, '_fs_reinvest_ui_patch', False):
        return

    def endpoint(*args, **kwargs):
        response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
        html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)
        js = r'''<script id="fs-reinvest-ui-js">
(function(){
  const oldStart=window.start;
  if(typeof oldStart!=='function')return;
  window.start=async function(mode){
    const cb=document.getElementById('reinvestProfit');
    const originalFetch=window.fetch;
    if(cb){
      window.fetch=function(input,init){
        try{
          const url=String(input||'');
          if(url.includes('/api/'+mode.toLowerCase()+'/start') && init && init.body){
            const p=JSON.parse(init.body);p.reinvest_profit=!!cb.checked;init.body=JSON.stringify(p);
          }
        }catch(e){}
        return originalFetch(input,init);
      };
    }
    try{return await oldStart(mode)}finally{window.fetch=originalFetch}
  };
})();
</script>'''
        html = html.replace('</body>', js + '</body>', 1)
        headers = dict(getattr(response, 'headers', {}) or {})
        for k in ('content-length','Content-Length','content-type','Content-Type'):
            headers.pop(k, None)
        headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
        return HTMLResponse(content=html,status_code=getattr(response,'status_code',200),headers=headers,media_type='text/html')
    endpoint._fs_reinvest_ui_patch=True
    route.endpoint=endpoint
    route.app=request_response(endpoint)
