from __future__ import annotations


def install(app):
    html = getattr(app, '_CONTROL_HTML', '')
    if not html or 'fsPreviousSessionBanner' in html:
        return
    css = '''<style>
#fsPreviousSessionBanner{display:none;position:sticky;top:8px;z-index:20;background:#0b3d24;border:1px solid #20d66b;color:#fff;border-radius:14px;padding:11px 13px;margin:8px 0;font-weight:800;box-shadow:0 0 14px rgba(32,214,107,.2)}
#fsPreviousSessionBanner .star{font-size:20px;margin-right:7px}#fsPreviousSessionBanner button{width:auto;margin:7px 0 0;padding:8px 12px;background:#374151;color:#fff}
.fs-auto{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;padding:10px;border:1px solid #394659;border-radius:10px;background:#151c27}.fs-auto label{font-size:13px}.fs-auto select{background:#374151;color:#fff;border:1px solid #526174;border-radius:8px;padding:7px}
</style>'''
    banner = '''<div id="fsPreviousSessionBanner"><span class="star">★</span>Сохранены позиции с предыдущей сессии.<br><span style="font-weight:500">Если хотите изменить их вручную — выберите новые позиции и нажмите «Изменить предыдущую сессию».</span><br><button type="button" onclick="fsManualReplace()">Изменить предыдущую сессию</button></div>'''
    controls = '''<div class="fs-auto"><label><input id="fsAutoReplace" type="checkbox"> Автозамена горячих позиций при выгорании / утрате актуальности</label><label>Позиция замены: <select id="fsPreferredSlot"><option value="1">#1</option><option value="2">#2</option><option value="3">#3</option><option value="4">#4</option><option value="5">#5</option></select></label></div>'''
    js = '''<script>
let fsManualReplaceFlag=false;
function fsManualReplace(){fsManualReplaceFlag=true;document.getElementById('fsPreviousSessionBanner').style.display='none';alert('Режим изменения предыдущей сессии включён. Выберите новые пары вручную.');}
async function fsSessionStatus(){try{const r=await fetch('/api/paper/status');const s=await r.json();const b=document.getElementById('fsPreviousSessionBanner');if(b&&!s.running&&s.previous_session_available&&Object.keys(s.open_positions||{}).length)b.style.display='block';if(s.running)document.getElementById('status').innerHTML='🟢 PAPER работает';}catch(e){}}
const fsOldStartPaper=window.startPaper;
window.startPaper=async function(){
  if(!fsOldStartPaper)return;
  const oldFetch=window.fetch;
  const oldJson=Response.prototype.json;
  // Use the existing UI validation and request, but inject session/slot controls into its payload.
  let c=typeof getCfg==='function'?getCfg():{};
  if(!c.pairs||!c.pairs.length){return fsOldStartPaper()}
  if(Math.abs(c.allocations.reduce((a,b)=>a+b,0)-100)>.01){return fsOldStartPaper()}
  const slots=c.pairs.map((p,i)=>({pair:p,allocation:c.allocations[i]}));
  const payload={...c,slots,auto_replace_hot:!!document.getElementById('fsAutoReplace')?.checked,preferred_slot:+(document.getElementById('fsPreferredSlot')?.value||1),replace_previous_session:fsManualReplaceFlag,target_usdt:.30,min_usdt:.20,sl_pct:.5,max_hold:180,fee_pct:.1};
  const r=await oldFetch('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok){alert(d.detail||'Ошибка запуска');return;}fsManualReplaceFlag=false;document.getElementById('status').innerHTML='🟢 PAPER работает';if(typeof refresh==='function')refresh();fsSessionStatus();
};
window.addEventListener('DOMContentLoaded',()=>{const box=document.querySelector('.card:nth-of-type(4)');if(box&&!document.querySelector('.fs-auto'))box.insertAdjacentHTML('beforeend',controls);fsSessionStatus();setInterval(fsSessionStatus,3000);});
</script>'''
    app._CONTROL_HTML = html.replace('</head>', css + '</head>', 1).replace('<body>', '<body>' + banner, 1).replace('</body>', js + '</body>', 1)
