from __future__ import annotations

def install(app):
    from . import ui_v7
    ui_v7.SKIN = ui_v7.SKIN.replace("fsSlotsV2", "fsSlotsV3")
    css = r'''<style id="fs-final-ui">
#slots .slot{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) 112px;grid-template-areas:"pair pair pair" "modes modes value" "total clear clear";gap:6px;padding:9px;margin:7px 0}
#slots .slot>.input:first-child{grid-area:pair;margin:0}
#slots .slot>.mini{grid-area:modes;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:4px;margin:0}
#slots .slot>.mini button:nth-child(1){grid-column:1;grid-row:1}#slots .slot>.mini button:nth-child(2){grid-column:1;grid-row:2}#slots .slot>.mini button:nth-child(3){grid-column:2;grid-row:1}#slots .slot>.mini button:nth-child(4){grid-column:2;grid-row:2}
#slots .slot>input[type=number]{grid-area:value;margin:0;min-width:0}#slots .slot>.muted{grid-area:total;align-self:center;margin:0}#slots .slot>.btn{grid-area:clear;margin:0;padding:8px}
#fsStats{border-top:1px solid #421015;margin-top:9px;padding-top:8px;display:grid;grid-template-columns:repeat(3,1fr);gap:7px}#fsStats .fs-stat{border:1px solid #451015;border-radius:8px;background:#08090a;padding:7px;color:#aaa;font-size:11px}#fsStats b{display:block;color:#fff;font-size:16px;margin-top:3px}
@media(max-width:600px){#slots .slot{grid-template-columns:minmax(0,1fr) 96px;grid-template-areas:"pair pair" "modes value" "total clear"}.slot>.mini{min-height:76px}}
</style>'''
    if 'id="fs-final-ui"' not in ui_v7.SKIN: ui_v7.SKIN=ui_v7.SKIN.replace('</head>',css+'</head>',1)
    js=r'''<script id="fs-final-ui-js">(function(){
const $=id=>document.getElementById(id),starts={PAPER:null,LIVE:null},obs={};
function timerText(m){const ts=starts[m];if(!ts)return'00:00:00';const n=Math.max(0,Math.floor((Date.now()-ts)/1000)),h=Math.floor(n/3600),mi=Math.floor(n%3600/60),s=n%60;return[h,mi,s].map(x=>String(x).padStart(2,'0')).join(':')}
function paintTimer(m){const e=$(m==='PAPER'?'paperTimer':'liveTimer');if(e){const t=timerText(m);if(e.textContent!==t)e.textContent=t}}
function watchTimer(m){const e=$(m==='PAPER'?'paperTimer':'liveTimer');if(!e||obs[m])return;obs[m]=new MutationObserver(()=>paintTimer(m));obs[m].observe(e,{childList:true,characterData:true,subtree:true})}
function ensureStats(){if($('fsStats'))return;const s=document.querySelector('.capital-line');if(!s)return;const b=document.createElement('div');b.id='fsStats';b.innerHTML='<div class="fs-stat">ЗАКЛЮЧЕНО<b id="fsClosed">0</b></div><div class="fs-stat">УСПЕШНЫХ<b id="fsWins">0</b></div><div class="fs-stat">УБЫТОЧНЫХ<b id="fsLosses">0</b></div>';s.appendChild(b)}
function updateStats(d){ensureStats();const t=Array.isArray(d?.trades)?d.trades:[];let w=0,l=0;for(const x of t){const p=Number(x?.pnl??x?.net_pnl??x?.profit??0);if(p>0)w++;else if(p<0)l++}if($('fsClosed'))$('fsClosed').textContent=t.length;if($('fsWins'))$('fsWins').textContent=w;if($('fsLosses'))$('fsLosses').textContent=l}
async function sync(m){try{const r=await fetch('/api/session/report/'+m,{cache:'no-store'});if(!r.ok)return;const d=await r.json();if(d.running){const ts=Number(d.started_at||0)*1000;if(ts>0)starts[m]=ts;else if(!starts[m])starts[m]=Date.now()}else starts[m]=null;paintTimer(m);updateStats(d)}catch(e){}}
async function syncAll(){ensureStats();watchTimer('PAPER');watchTimer('LIVE');await Promise.all([sync('PAPER'),sync('LIVE')])}
async function renderTop(){try{const r=await fetch('/api/recommendations?limit=20',{cache:'no-store'}),d=await r.json();if(!r.ok)throw Error(d.detail||'Ошибка радара');const rows=(d.candidates20||d.top5||[]).slice(0,6),top=$('top');if(!top)return;top.innerHTML=rows.length?'<div class="top-table">'+rows.map((x,i)=>'<div class="top-cell"><div class="top-rank">#'+(i+1)+' <span class="top-symbol">'+String(x.symbol||'—')+'</span><span class="top-score">'+(x.score??'—')+'</span></div><div class="top-meta">'+(x.signal||'WAIT')+' • вход '+(x.estimated_entry??'—')+' → '+(x.estimated_exit??'—')+' • '+(x.hold_seconds||180)+'с</div><button class="top-pick top-select" data-symbol="'+String(x.symbol||'').replace(/"/g,'&quot;')+'">ВЫБРАТЬ</button></div>').join('')+'</div>':'Радар пока не дал рекомендаций';top.querySelectorAll('.top-select').forEach(b=>b.onclick=()=>window.pick&&window.pick(b.dataset.symbol));window.mark&&window.mark()}catch(e){const t=$('top');if(t)t.textContent='Ошибка радара: '+e.message}}
const oldPick=window.pick;window.pick=function(s){const x=oldPick?oldPick(s):undefined;setTimeout(renderTop,50);return x};
try{localStorage.removeItem('fsSlots');localStorage.removeItem('fsSlotsV2')}catch(e){}
document.addEventListener('focusin',e=>{const t=e.target;if(t?.matches('#slots input[type=number]')&&t.value==='0')t.value=''});
const topObserver=new MutationObserver(()=>{const t=$('top');if(t&&!t.querySelector('.top-table')&&!t.dataset.fsRepair){t.dataset.fsRepair='1';setTimeout(()=>{t.dataset.fsRepair='';renderTop()},20)}});
function boot(){ensureStats();const t=$('top');if(t)topObserver.observe(t,{childList:true,subtree:true});renderTop();syncAll();setInterval(syncAll,3000);setInterval(()=>{paintTimer('PAPER');paintTimer('LIVE')},250)}
const oldToggle=window.toggleRun;window.toggleRun=async function(m){const x=oldToggle?await oldToggle(m):false;await sync(m);return x};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();</script>'''
    if 'id="fs-final-ui-js"' not in ui_v7.SKIN: ui_v7.SKIN=ui_v7.SKIN.replace('</body>',js+'</body>',1)
