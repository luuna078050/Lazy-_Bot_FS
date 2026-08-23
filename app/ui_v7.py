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
REPORT_JS = r'''<script>
(function(){
  const oldRefresh = window.refresh;
  if(!oldRefresh) return;
  window.refresh = async function(){
    await oldRefresh();
    try{
      const modes=['PAPER','LIVE'];
      for(const mode of modes){
        const r=await fetch('/api/session/report/'+mode,{cache:'no-store'}); if(!r.ok) continue;
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
SKIN = SKIN.replace('</body>', REPORT_JS + '</body>', 1)

# Do not wrap the FastAPI root route. The previous start-guard wrapper caused
# Render 502s. Install the authoritative PAPER/LIVE controls directly in the
# page instead: timers start only after a successful API response and stop only
# after the stop API call completes.
RUN_JS = r'''<script>
(function(){
  const $=id=>document.getElementById(id);
  const timers={PAPER:null,LIVE:null};
  const starts={PAPER:null,LIVE:null};
  function storageKey(mode){return mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive'}
  function paint(mode,on,startTs){
    const low=mode.toLowerCase(), sw=$(low+'Switch'), tx=$(low+'SwitchText'), st=$(low+'Status'), tm=$(low+'Timer');
    if(sw)sw.classList.toggle('on',!!on);
    if(tx)tx.textContent=on?'ON':'OFF';
    if(st){st.textContent=mode+' '+(on?'работает':'остановлен');st.classList.toggle('on',!!on)}
    clearInterval(timers[mode]);
    if(!on){
      starts[mode]=null;
      localStorage.removeItem(storageKey(mode));
      if(tm)tm.textContent='00:00:00';
      return;
    }
    const ts=Number(startTs)||Date.now();
    starts[mode]=ts;
    localStorage.setItem(storageKey(mode),String(ts));
    const tick=()=>{
      const n=Math.max(0,Math.floor((Date.now()-ts)/1000));
      const h=Math.floor(n/3600),m=Math.floor((n%3600)/60),s=n%60;
      if(tm)tm.textContent=[h,m,s].map(x=>String(x).padStart(2,'0')).join(':');
    };
    tick();
    timers[mode]=setInterval(tick,1000);
  }
  async function sync(mode){
    try{
      const r=await fetch('/api/session/report/'+mode,{cache:'no-store'});
      if(!r.ok){paint(mode,false);return false}
      const d=await r.json();
      paint(mode,!!d.running,d.started_at?Number(d.started_at)*1000:null);
      if(window.fsV6Report)window.fsV6Report(d);
      return !!d.running;
    }catch(e){return false}
  }
  window.start=async function(mode){
    try{
      const c=cfg(mode);
      const total=(c.allocations||[]).reduce((a,b)=>a+b,0);
      if(!(c.pairs||[]).length){alert('Нет выбранных '+mode+' пар');paint(mode,false);return false}
      if(Math.abs(total-100)>.01){alert(mode+': нужно 100%, сейчас '+total.toFixed(2)+'%');paint(mode,false);return false}
      if(mode==='LIVE'){
        c.api_key=$('key')?.value||'';
        c.api_secret=$('secret')?.value||'';
        if(!c.api_key||!c.api_secret){alert('Для LIVE нужны API Key и Secret');paint(mode,false);return false}
      }
      const r=await fetch('/api/'+mode.toLowerCase()+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c),cache:'no-store'});
      let d={};
      try{d=await r.json()}catch(e){}
      if(!r.ok||!d.running){alert(d.detail||'Ошибка запуска '+mode);paint(mode,false);return false}
      await sync(mode);
      return true;
    }catch(e){alert('Ошибка запуска '+mode+': '+e.message);paint(mode,false);return false}
  };
  window.stop=async function(mode){
    try{
      const r=await fetch('/api/'+mode.toLowerCase()+'/stop',{method:'POST',cache:'no-store'});
      await sync(mode);
      if(r.ok)paint(mode,false);
      return r.ok;
    }catch(e){paint(mode,false);return false}
  };
  window.toggleRun=async function(mode){
    const sw=$(mode.toLowerCase()+'Switch');
    if(sw&&sw.classList.contains('on'))return window.stop(mode);
    return window.start(mode);
  };
  window.emergency=async function(){
    try{
      await Promise.all(['PAPER','LIVE'].map(m=>fetch('/api/'+m.toLowerCase()+'/emergency-stop',{method:'POST',cache:'no-store'})));
    }finally{
      paint('PAPER',false);paint('LIVE',false);
      await sync('PAPER');await sync('LIVE');
    }
  };
  async function boot(){
    await sync('PAPER');
    await sync('LIVE');
    const p=localStorage.getItem(storageKey('PAPER')), l=localStorage.getItem(storageKey('LIVE'));
    if(p&&!$('paperSwitch')?.classList.contains('on'))localStorage.removeItem(storageKey('PAPER'));
    if(l&&!$('liveSwitch')?.classList.contains('on'))localStorage.removeItem(storageKey('LIVE'));
  }
  boot();
  setInterval(()=>{sync('PAPER');sync('LIVE')},3000);
})();
</script>'''
SKIN = SKIN.replace('</body>', RUN_JS + '</body>', 1)

@app.get('/', response_class=HTMLResponse)
def home():
    return SKIN
