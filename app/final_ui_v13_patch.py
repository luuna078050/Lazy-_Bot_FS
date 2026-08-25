from __future__ import annotations

import inspect
import os
import threading
import time
import urllib.request

from fastapi.responses import HTMLResponse
from fastapi.routing import request_response


def _self_keepalive():
    """Internal watchdog: call the app itself so the Render service stays active."""
    while True:
        try:
            base = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
            urls = []
            if base:
                urls.append(base + "/api/health?ka=1")
            urls.append(f"http://127.0.0.1:{os.getenv('PORT', '8000')}/api/health?ka=1")
            for url in urls:
                try:
                    with urllib.request.urlopen(url, timeout=8) as r:
                        r.read(64)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(180)


def install(app):
    route = next((r for r in app.router.routes if getattr(r, "path", None) == "/"), None)
    if route is None or not hasattr(route, "endpoint"):
        return
    original = route.endpoint
    if getattr(original, "_fs_ui_final_v13", False):
        return

    def endpoint(*args, **kwargs):
        response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
        html = response.body.decode("utf-8") if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)

        css = '''<style id="fs-ui-v13-css">
.fs-command-card{padding:5px 7px!important;margin:5px 0!important}.fs-command-card>.title{font-size:12px!important;margin:0 0 3px!important}.fs-command-grid{gap:5px!important}.fs-command-mode{padding:4px!important;border-radius:7px!important}.fs-command-label{font-size:9px!important;margin-bottom:2px!important}.fs-command-mode .run-switch{min-width:54px!important;padding:3px 7px!important;font-size:10px!important}.fs-command-mode .run-dot{width:7px!important;height:7px!important}.fs-command-mode .run-status{font-size:8px!important;margin-top:2px!important}.fs-command-mode .run-timer{font-size:12px!important;margin:2px 0 0!important}.fs-emergency{font-size:8px!important;padding:3px!important;margin-top:2px!important}
.pnl-card{padding:8px!important}.pnl-card .pnlbig{font-size:28px!important;line-height:1!important}.pnl-card .pnl-head .title{font-size:12px!important}.account-box{padding:5px 7px!important}.account-box span{font-size:8px!important}.account-box b{font-size:14px!important;margin-top:2px!important}.pnl-card .pnlrow{gap:4px!important}.pnl-card .pnlrow>div{font-size:9px!important;line-height:1.05!important}.pnl-card .pnlrow b{font-size:12px!important}.fs-hypo-label{font-size:9px!important}.fs-hypo-value{font-size:12px!important}.bot-summary{display:none!important}
#fsFeedback{display:block;width:100%;margin:6px 0 0;padding:5px;border:1px solid #3b3c40;border-radius:6px;background:#17181a;color:#777;font-size:9px;font-weight:800}
#fsRecentWrap{margin-top:6px}#fsRecentWrap .fs-recent-head{display:flex;justify-content:space-between;align-items:center;gap:5px}#fsRecentWrap .fs-recent-toggle{border:1px solid #3b3c40;background:#17181a;color:#bbb;border-radius:6px;padding:4px 7px;font-size:9px;font-weight:800}#fsRecentList{font-size:9px;color:#aaa;margin-top:5px}.fs-recent-row{padding:4px 0;border-bottom:1px solid #2c1115}.fs-recent-row b{color:#fff}
.fs-settings-top{display:grid;grid-template-columns:1fr auto;gap:6px;align-items:end}.fs-settings-top #capital{height:30px!important;padding:5px 8px!important;font-size:12px!important}.fs-reinvest{display:flex;align-items:center;gap:4px;height:30px;padding:0 7px;border:1px solid #3b3c40;border-radius:7px;background:#151719;color:#bbb;font-size:9px;font-weight:900;white-space:nowrap}.fs-reinvest input{width:13px;height:13px;margin:0}.settings-note{display:none!important}
#slots{gap:5px!important}#slots .slot{padding:5px!important}#slots .slot .input{padding:5px!important;font-size:11px!important}#slots .slot .btn{padding:5px!important;font-size:9px!important;margin-top:3px!important}#slots .slot .muted{font-size:8px!important;line-height:1!important}.fs-slot-row{grid-template-columns:1fr 48px!important}.fs-slot-tf{font-size:8px!important;padding:4px 2px!important}
.fs-top10-final{gap:5px!important}.fs-top10-final .fs-card{padding:6px!important}.fs-top10-final .rank{font-size:11px!important}.fs-top10-final .score{font-size:10px!important}.fs-top10-final .meta{font-size:8px!important}.fs-top10-final .profit{font-size:9px!important}.fs-top10-final .fs-price-red{font-size:10px!important}.fs-sell-band{font-size:8px!important}.fs-top10-final select{font-size:8px!important;padding:3px!important}.fs-top10-final button{font-size:8px!important;padding:5px!important}.fs-selected-green{border-color:#22e36f!important;box-shadow:0 0 7px rgba(34,227,111,.18)!important}
@media(max-width:600px){.fs-settings-top{grid-template-columns:1fr 1fr}.fs-settings-top #capital{height:28px!important}.fs-reinvest{font-size:8px!important}}
</style>'''
        html = html.replace("</style></head>", css + "</style></head>", 1)

        js = r'''<script id="fs-ui-v13-js">
(function(){
 const $=id=>document.getElementById(id), esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
 const TFKEY='fsRecommendationTimeframes',REKEY='fsReinvestProfit'; let tfState={}; try{tfState=JSON.parse(localStorage.getItem(TFKEY)||'{}')}catch(e){}
 const slotsNow=()=>typeof slots!=='undefined'&&Array.isArray(slots)?slots:[];
 function installReinvest(){const cap=$('capital');if(!cap||$('reinvestProfit'))return;const wrap=document.createElement('div');wrap.className='fs-settings-top';cap.parentNode.insertBefore(wrap,cap);wrap.appendChild(cap);const lab=document.createElement('label');lab.className='fs-reinvest';lab.innerHTML='<input id="reinvestProfit" type="checkbox"> Реинвестировать прибыль';wrap.appendChild(lab);$('reinvestProfit').checked=localStorage.getItem(REKEY)==='1';$('reinvestProfit').onchange=()=>localStorage.setItem(REKEY,$('reinvestProfit').checked?'1':'0');}
 function compactPnl(){const card=document.querySelector('.pnl-card');if(!card)return;const title=card.querySelector('.pnl-head .title');if(title)title.innerHTML='PnL <span style="color:#aaa">СЕГОДНЯ</span> <span style="color:#65f28d">/ ACCUMULATED</span>';const acct=card.querySelector('.account-box');if(acct)acct.innerHTML='<span>💼 BALANCE ACCOUNT</span><b id="acct">—</b><div id="acctAccum" style="font-size:8px;color:#65f28d;margin-top:2px">(including bot accumulated: 0.0000 USDT)</div>';const row=card.querySelector('.pnlrow');if(row){if(row.children[0])row.children[0].innerHTML='Realized PnL<br><b id="real">0.00</b>';if(row.children[1])row.children[1].innerHTML='Unrealized PnL<br><b id="unreal">0.00</b>';if(row.children[2])row.children[2].innerHTML='Net PnL<br><b id="net">0.00</b>';if(!$('hypo')){const d=document.createElement('div');d.className='fs-hypo-label';d.innerHTML='Hypothetical Net<br><b id="hypo" class="fs-hypo-value">0.0000 USDT</b>';row.appendChild(d)}}const bs=card.querySelector('.bot-summary');if(bs)bs.remove();}
 function moveSessionCards(){const pnl=document.querySelector('.pnl-card');if(!pnl)return;const cards=[...document.querySelectorAll('.card')];const session=cards.find(c=>/SESSION RESULT/i.test(c.textContent||''));const closed=cards.find(c=>/ПОСЛЕДНИЕ ЗАКРЫТЫЕ СДЕЛКИ/i.test(c.textContent||''));if(session)pnl.parentNode.insertBefore(session,pnl.nextSibling);if(closed){pnl.parentNode.insertBefore(closed,session?session.nextSibling:pnl.nextSibling);closed.id='fsRecentWrap';if(!closed.dataset.fsV13)enhanceRecent(closed);}}
 function enhanceRecent(card){card.dataset.fsV13='1';const title=card.querySelector('.title');const body=title?.parentNode;if(!body)return;if(title)title.innerHTML='📜 ПОСЛЕДНИЕ ЗАКРЫТЫЕ СДЕЛКИ <span style="color:#777">· 15 МИН</span>';const head=document.createElement('div');head.className='fs-recent-head';const toggle=document.createElement('button');toggle.className='fs-recent-toggle';toggle.textContent='Показать последние 5';if(title){body.removeChild(title);head.appendChild(title);head.appendChild(toggle);body.insertBefore(head,body.firstChild)}const list=document.createElement('div');list.id='fsRecentList';list.style.display='none';body.appendChild(list);let open=false;async function load(){try{const mode=localStorage.getItem('fsLastReportMode')||'PAPER';const d=await fetch('/api/session/report/'+mode,{cache:'no-store'}).then(r=>r.json());const since=Date.now()-15*60*1000;const ts=v=>{const n=Date.parse(v||'');return Number.isFinite(n)?n:0};const rows=(d.trades||[]).filter(x=>!ts(x.closed_at)||ts(x.closed_at)>=since).slice(-5).reverse();list.innerHTML=rows.length?rows.map(x=>'<div class="fs-recent-row"><b>'+esc(x.symbol||'—')+'</b> · '+esc(x.timeframe||'3m')+' · '+(Number(x.net_pnl||0)>=0?'+':'')+Number(x.net_pnl||0).toFixed(4)+' USDT · '+esc(x.reason||'—')+'</div>').join(''):'<div class="muted">Нет закрытых сделок за последние 15 минут.</div>'}catch(e){list.innerHTML='<div class="muted">Ошибка получения истории.</div>'}}toggle.onclick=()=>{open=!open;toggle.textContent=open?'Скрыть':'Показать последние 5';list.style.display=open?'block':'none';if(open)load();}}
 function cleanTop(){const top=$('top');if(!top)return;const parent=top.parentElement;const add=parent?.querySelector('input[placeholder*="Добавить пару"]');if(add){const box=add.closest('div');if(box)box.remove()}const heading=parent?.querySelector('.title');if(heading)heading.innerHTML='🚀 ТОП ПАРЫ · РЕЙТИНГ СИГНАЛОВ';let fb=$('fsFeedback');if(!fb){fb=document.createElement('button');fb.id='fsFeedback';fb.disabled=true;fb.textContent='💬 ОБРАТНАЯ СВЯЗЬ — СКОРО';parent?.appendChild(fb)}}
 async function refreshTop(){try{const d=await fetch('/api/recommendations?limit=20',{cache:'no-store'}).then(r=>r.json());const rs=(d.candidates20||d.top10||d.top5||[]).slice(0,10),top=$('top');if(!top)return;top.innerHTML='<div class="fs-top10-final">'+rs.map((x,i)=>{const s=String(x.symbol||'—'),price=Number(x.price||0),score=Number(x.score),tf=String(tfState[s]||'3m'),lo=price*.90,hi=price*1.20,chosen=slotsNow().some(z=>String(z.p||'').toUpperCase()===s.toUpperCase());return '<div class="fs-card '+(chosen?'fs-selected-green':'')+'"><div class="rank"><span>🔥 #'+(i+1)+' '+esc(s)+'</span><span class="score">'+(Number.isFinite(score)?score.toFixed(0):'—')+'</span></div><div class="meta"><span>Hot: '+(Number(x.hot_market_score)||0).toFixed(0)+'</span><span>Flow: '+((Number(x.buy_ratio)||0)*100).toFixed(0)+'%</span><span>1–3m: '+(Number(x.change_3m_pct)||0).toFixed(3)+'%</span><span>$/мин/$100: <b class="profit">$'+(Number(x.expected_pnl_per_min_100)||0).toFixed(2)+'</b></span><span>SELL @ NOW: <b class="fs-price-red">'+(price?price.toPrecision(9):'—')+'</b></span><span>Signal: '+esc(x.signal||'WAIT')+'</span></div><div class="fs-sell-band">Ориентир −10%: '+(price?lo.toPrecision(8):'—')+' · +20%: '+(price?hi.toPrecision(8):'—')+'</div><select data-symbol="'+esc(s)+'" class="fs-radar-tf"><option value="1m" '+(tf==='1m'?'selected':'')+'>1 мин</option><option value="3m" '+(tf==='3m'?'selected':'')+'>3 мин</option><option value="5m" '+(tf==='5m'?'selected':'')+'>5 мин</option></select><button class="top-select '+(chosen?'selected':'')+'" data-symbol="'+esc(s)+'">'+(chosen?'✓ ВЫБРАНО':'ВЫБРАТЬ')+'</button></div>'}).join('')+'</div>';top.querySelectorAll('.fs-radar-tf').forEach(el=>el.onchange=()=>{tfState[el.dataset.symbol]=el.value;localStorage.setItem(TFKEY,JSON.stringify(tfState));refreshTop()});top.querySelectorAll('.top-select').forEach(b=>b.onclick=()=>{if(typeof window.pick==='function')window.pick(b.dataset.symbol);setTimeout(refreshTop,250)});cleanTop();}catch(e){}}
 async function updatePnl(){try{const mode=localStorage.getItem('fsLastReportMode')||'PAPER',d=await fetch('/api/session/report/'+mode,{cache:'no-store'}).then(r=>r.json());const set=(id,v)=>{if($(id))$(id).textContent=Number(v||0).toFixed(4)+' USDT'};set('acct',d.account_balance_usdt);set('real',d.realized_pnl);set('unreal',d.unrealized_pnl);set('net',d.net_pnl);if($('hypo'))$('hypo').textContent=Number(d.hypothetical_net_pnl??d.net_pnl??0).toFixed(4)+' USDT';if($('acctAccum'))$('acctAccum').textContent='(including bot accumulated: '+Number(d.accumulated_profit_usdt||0).toFixed(4)+' USDT)';if($('reinvestProfit'))$('reinvestProfit').checked=localStorage.getItem(REKEY)==='1';}catch(e){}}
 function sendReinvest(){const r=$('reinvestProfit');if(!r)return;window.fsReinvestProfit=!!r.checked;localStorage.setItem(REKEY,r.checked?'1':'0');}
 const oldStart=window.start;if(oldStart){window.start=async function(mode){const r=await oldStart(mode);sendReinvest();return r;}}
 function boot(){installReinvest();compactPnl();moveSessionCards();cleanTop();refreshTop();updatePnl();setInterval(()=>{moveSessionCards();refreshTop();updatePnl()},5000)}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else setTimeout(boot,20);
})();
</script>'''
        html = html.replace("</body>", js + "</body>", 1)
        headers = dict(getattr(response, "headers", {}) or {})
        for k in ("content-length", "Content-Length", "content-type", "Content-Type"):
            headers.pop(k, None)
        headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return HTMLResponse(content=html, status_code=getattr(response, "status_code", 200), headers=headers, media_type="text/html")

    endpoint._fs_ui_final_v13 = True
    route.endpoint = endpoint
    route.app = request_response(endpoint)

    if not getattr(app, "_fs_self_keepalive_started", False):
        app._fs_self_keepalive_started = True
        threading.Thread(target=_self_keepalive, daemon=True, name="fs-self-keepalive").start()
