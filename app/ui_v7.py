from __future__ import annotations

import re
from fastapi.responses import HTMLResponse
from .ui_v6 import app, SKIN as BASE_SKIN

# UI v7: keep the approved Fast Scalper v6 layout, but make the capital line
# exactly: bot balance / accumulated by bot / available to attract.
for route in list(app.router.routes):
    if getattr(route, 'path', None) == '/':
        app.router.routes.remove(route)

SKIN = BASE_SKIN

old = re.search(r'<div class="bot-summary">.*?</div></section>', SKIN, flags=re.S)
if not old:
    raise RuntimeError('Fast Scalper capital summary block not found')

new = '''<div class="bot-summary capital-line">
<div>🤖 БАЛАНС БОТА — <b id="bot">—</b></div>
<div>💰 НАКОПЛЕНО БОТОМ — <b id="accumulated">—</b></div>
<div>➕ ВОЗМОЖНО ПРИВЛЕЧЬ — <b id="extra">—</b></div>
</div></section>'''
SKIN = SKIN[:old.start()] + new + SKIN[old.end():]

SKIN = SKIN.replace(
    '.bot-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;color:#aaa;font-size:11px}',
    '.bot-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;color:#aaa;font-size:11px}.capital-line{align-items:center}.capital-line>div{white-space:nowrap}.capital-line b{display:inline;color:#fff;font-size:16px;margin-left:3px}',
    1,
)

# The base v6 refresh already obtains the report. Wrap it so the new readonly
# accumulated-profit value is displayed without changing the approved report flow.
JS = r'''<script>
(function(){
  const oldRefresh = window.refresh;
  if(!oldRefresh) return;
  window.refresh = async function(){
    await oldRefresh();
    try{
      const modes=['PAPER','LIVE'];
      for(const mode of modes){
        const r=await fetch('/api/session/report/'+mode); if(!r.ok) continue;
        const d=await r.json();
        if(d.running || d.stopped_at || Number(d.account_balance_usdt||0)>0){
          const bot=Number(d.bot_balance_usdt ?? d.initial_balance ?? 0);
          const accumulated=Number(d.accumulated_profit_usdt ?? (Number(d.account_balance_usdt||0)-bot));
          const extra=Number(d.available_to_attract_usdt ?? Math.max(0,Number(d.account_balance_usdt||0)-bot));
          const b=document.getElementById('bot'), a=document.getElementById('accumulated'), e=document.getElementById('extra');
          if(b)b.textContent=(bot||0).toFixed(4)+' USDT';
          if(a)a.textContent=(accumulated||0).toFixed(4)+' USDT';
          if(e)e.textContent=(extra||0).toFixed(4)+' USDT';
        }
      }
    }catch(e){}
  };
})();
</script>'''
SKIN = SKIN.replace('</body>', JS + '</body>', 1)

@app.get('/', response_class=HTMLResponse)
def home():
    return SKIN
