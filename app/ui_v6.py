from __future__ import annotations

from fastapi.responses import HTMLResponse
from .ui_v5 import SKIN as BASE_SKIN
from .fixed_app import app

# ui_v5 already builds the Fast Scalper backend routes. Replace only the root
# dashboard with the corrected compact dashboard; keep the existing API.
for r in list(app.router.routes):
    if getattr(r, 'path', None) == '/':
        app.router.routes.remove(r)

SKIN = BASE_SKIN

OLD_METRICS = '''<section class="card"><div class="title">PnL <span style="float:right;color:#aaa">СЕГОДНЯ</span></div><div id="pnl" class="pnlbig">0.00 USDT (0.00%)</div><div class="pnlrow"><div>Realized PnL<br><b id="real">0.00</b></div><div>Unrealized PnL<br><b id="unreal">0.00</b></div><div>Net PnL<br><b id="net">0.00</b></div></div></section>
<section class="grid4"><div class="metric">💼 БАЛАНС АККАУНТА<b id="acct">—</b></div><div class="metric">🤖 БАЛАНС БОТА<b id="bot">—</b></div><div class="metric">◷ ИСПОЛЬЗОВАНО ПОЗИЦИЙ<b id="used">0 / 5</b><div class="bar"><i id="usedbar" style="width:0%"></i></div></div><div class="metric">💰 ДОСТУПНО В БОТЕ<b id="free">—</b></div></section>
'''

NEW_METRICS = '''<section class="card pnl-card"><div class="pnl-head"><div><div class="title">PnL <span style="color:#aaa">СЕГОДНЯ</span></div><div id="pnl" class="pnlbig">0.00 USDT (0.00%)</div></div><div class="account-box"><span>💼 БАЛАНС АККАУНТА</span><b id="acct">—</b></div></div><div class="pnlrow"><div>Realized PnL<br><b id="real">0.00</b></div><div>Unrealized PnL<br><b id="unreal">0.00</b></div><div>Net PnL<br><b id="net">0.00</b></div></div><div class="pnl-divider"></div><div class="bot-summary"><div>🤖 БАЛАНС БОТА<br><b id="bot">—</b></div><div>◷ ЗАДЕЙСТВОВАНО ПОЗИЦИЙ<br><b id="used">0 / 5</b></div><div>➕ ВОЗМОЖНО ПРИВЛЕЧЬ<br><b id="extra">—</b></div></div></section>
'''

if OLD_METRICS not in SKIN:
    raise RuntimeError('Fast Scalper v5 metrics block changed; UI v6 patch needs review')
SKIN = SKIN.replace(OLD_METRICS, NEW_METRICS, 1)

OLD_TOP_POS = '''<section class="two"><div class="card"><div class="title">🚀 ТОП ПАРЫ · РЕЙТИНГ СИГНАЛОВ</div><div id="top">Загрузка радара…</div></div><div class="card"><div class="title">◉ ОТКРЫТЫЕ ПОЗИЦИИ</div><div id="positions">Нет открытых позиций</div></div></section>
<section class="three"><div class="card"><div class="title">⚡ БЫСТРАЯ СТАТИСТИКА</div><div id="stats" class="muted">Сделок сегодня: 0<br>Прибыльных: 0<br>Убыточных: 0<br>Лучший трейд: 0<br>Худший трейд: 0</div></div><div class="card"><div class="title">⚙ РЕЖИМ РАБОТЫ</div><div class="muted">Таймфрейм</div><div class="tf"><button data-tf="1m">1m</button><button data-tf="3m" class="on">3m</button><button data-tf="5m">5m</button></div><div class="muted" style="margin-top:8px">Риск на сделку <b>5%</b><br>Комиссия <b>0,10% / 0,10%</b></div></div><div class="card"><div class="title">◉ БАЛАНС БОТА</div><div id="alloc">Нет выбранных пар</div><hr style="border-color:#331015"><div class="muted">ВОЗМОЖНЫЕ ДОП. РЕСУРСЫ</div><b id="extra">—</b><div class="muted">Баланс аккаунта − баланс бота</div></div></section>
'''

NEW_TOP_POS = '''<section class="two compact-main"><div class="card"><div class="title">🚀 ТОП ПАРЫ · РЕЙТИНГ СИГНАЛОВ</div><div id="top">Загрузка радара…</div></div><div class="card"><div class="title">◉ ОТКРЫТЫЕ ПОЗИЦИИ</div><div id="positions">Нет открытых позиций</div></div></section>
<section class="card"><div class="title">⚙ РЕЖИМ РАБОТЫ</div><div class="muted">Таймфрейм</div><div class="tf"><button data-tf="1m">1m</button><button data-tf="3m" class="on">3m</button><button data-tf="5m">5m</button></div><div class="muted" style="margin-top:8px">Риск на сделку <b>5%</b><br>Комиссия <b>0,10% / 0,10%</b></div></section>
'''

if OLD_TOP_POS not in SKIN:
    raise RuntimeError('Fast Scalper v5 top/positions block changed; UI v6 patch needs review')
SKIN = SKIN.replace(OLD_TOP_POS, NEW_TOP_POS, 1)

OLD_CONTROLS = '''<section class="card"><div class="controls"><div><button class="btn red" onclick="start('PAPER')">⚡ ЗАПУСТИТЬ PAPER</button><button class="btn" onclick="stop('PAPER')">■ STOP PAPER</button></div><div><button class="btn green" onclick="start('LIVE')">⚡ ЗАПУСТИТЬ LIVE</button><button class="btn red" onclick="stop('LIVE')">■ STOP LIVE</button><button class="btn" onclick="emergency()">⛔ EMERGENCY STOP</button></div></div><div class="status"><span id="paperStatus">○ PAPER: остановлен</span><span id="liveStatus">○ LIVE: остановлен</span></div></section>
'''

NEW_CONTROLS = '''<section class="card run-card"><div class="title">⚡ УПРАВЛЕНИЕ БОТОМ</div><div class="run-grid"><div class="run-mode"><div class="run-label">PAPER</div><button id="paperSwitch" class="run-switch" type="button" onclick="toggleRun('PAPER')"><span class="run-dot"></span><b id="paperSwitchText">OFF</b></button><div id="paperStatus" class="run-status">PAPER остановлен</div><div id="paperTimer" class="run-timer">00:00:00</div></div><div class="run-mode"><div class="run-label">LIVE</div><button id="liveSwitch" class="run-switch" type="button" onclick="toggleRun('LIVE')"><span class="run-dot"></span><b id="liveSwitchText">OFF</b></button><div id="liveStatus" class="run-status">LIVE остановлен</div><div id="liveTimer" class="run-timer">00:00:00</div><button class="btn" onclick="emergency()">⛔ EMERGENCY STOP</button></div></div></section>
'''

if OLD_CONTROLS not in SKIN:
    raise RuntimeError('Fast Scalper v5 controls block changed; UI v6 patch needs review')
SKIN = SKIN.replace(OLD_CONTROLS, NEW_CONTROLS, 1)

OLD_SETTINGS = '''<section class="card"><div class="title">⚙ НАСТРОЙКИ СЕССИИ</div><div class="muted">Бюджет</div><input class="input" id="capital" type="number" value="100" min="0.01" step="0.01"><div id="slots"></div><div id="total" class="muted"></div><div class="muted">Каждый слот: пара + PAPER/LIVE + % или USDT. Любые значения.</div><input class="input" id="key" placeholder="Binance API Key"><input class="input" id="secret" type="password" placeholder="Binance Secret Key"></section>
'''

NEW_SETTINGS = '''<section class="card"><div class="title">⚙ НАСТРОЙКИ СЕССИИ</div><div class="muted">Выделенный баланс бота</div><input class="input" id="capital" type="number" value="100" min="0.01" step="0.01"><div class="settings-note">Эта сумма — лимит капитала Fast Scalper. Прибыль не реинвестируется автоматически: она остаётся на балансе аккаунта.</div><div id="slots"></div><div id="total" class="muted"></div><div class="muted">Каждый слот: пара + PAPER/LIVE + % или USDT. Значения можно задавать любыми числами.</div><input class="input" id="key" placeholder="Binance API Key"><input class="input" id="secret" type="password" placeholder="Binance Secret Key"></section>
'''

if OLD_SETTINGS not in SKIN:
    raise RuntimeError('Fast Scalper v5 settings block changed; UI v6 patch needs review')
SKIN = SKIN.replace(OLD_SETTINGS, NEW_SETTINGS, 1)

# Add compact styling for the new layout and the requested green ON/OFF switches.
CSS = r'''<style>
.pnl-card{padding:12px}.pnl-head{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:start}.account-box{border:1px solid #6a4b00;background:#12100a;border-radius:10px;padding:8px 10px;text-align:right;color:#ffd04d}.account-box span{display:block;font-size:11px;color:#aaa}.account-box b{display:block;font-size:18px;margin-top:3px;color:#fff}.pnl-divider{height:1px;background:#421015;margin:10px 0}.bot-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;color:#aaa;font-size:11px}.bot-summary b{display:block;color:#fff;font-size:16px;margin-top:3px}.compact-main{margin-top:2px}.run-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.run-mode{border:1px solid #451015;border-radius:10px;padding:10px;background:#08090a;text-align:center}.run-label{font-weight:900;color:#ddd;margin-bottom:5px}.run-switch{display:inline-flex;align-items:center;justify-content:center;gap:7px;width:auto;min-width:84px;padding:7px 13px;border:1px solid #555;background:#18191b;color:#aaa;border-radius:999px;font-weight:900}.run-switch.on{background:#0e793b;border-color:#22e36f;color:#fff;box-shadow:0 0 10px rgba(34,227,111,.25)}.run-dot{width:9px;height:9px;border-radius:50%;background:#666}.run-switch.on .run-dot{background:#22e36f;box-shadow:0 0 9px #22e36f}.run-status{margin-top:7px;color:#aaa;font-size:12px}.run-status.on{color:#22e36f;font-weight:900}.run-timer{font-variant-numeric:tabular-nums;font-size:20px;font-weight:900;color:#fff;margin:5px 0}.settings-note{font-size:11px;color:#aaa;margin:5px 0 8px}.top-select{cursor:pointer}.pos b{font-size:15px}.position-main{font-size:13px}.position-sub{font-size:12px;color:#ddd;margin-top:3px}.position-sub .green{font-weight:900}.position-sub .red{font-weight:900}@media(max-width:600px){.pnl-head,.run-grid{grid-template-columns:1fr}.account-box{text-align:left}.bot-summary{grid-template-columns:1fr 1fr}.bot-summary>div:last-child{grid-column:1/-1}}
</style>'''
SKIN = SKIN.replace('</style></head>', CSS + '</style></head>', 1)

# Replace the original refresh/report JS with a small wrapper injected after it.
JS = r'''<script>
(function(){
  const started={PAPER:localStorage.getItem('fsRunStartPaper')||'',LIVE:localStorage.getItem('fsRunStartLive')||''};
  const timerIds={};
  const $=id=>document.getElementById(id);
  const money=v=>(Number(v)||0).toFixed(4)+' USDT';
  function setSwitch(mode,on){
    const low=mode.toLowerCase(), sw=$(low+'Switch'), txt=$(low+'SwitchText'), st=$(low+'Status')||$(low+'Status');
    if(sw)sw.classList.toggle('on',!!on);
    if(txt)txt.textContent=on?'ON':'OFF';
    if(st){st.textContent=mode+' '+(on?'работает':'остановлен');st.classList.toggle('on',!!on)}
    if(on && !started[mode]){started[mode]=String(Date.now());localStorage.setItem(mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive',started[mode])}
    if(!on){started[mode]='';localStorage.removeItem(mode==='PAPER'?'fsRunStartPaper':'fsRunStartLive')}
    runTimer(mode);
  }
  function runTimer(mode){
    const el=$(mode==='PAPER'?'paperTimer':'liveTimer'); if(!el)return;
    clearInterval(timerIds[mode]);
    const tick=()=>{let t=started[mode]?Math.max(0,Math.floor((Date.now()-Number(started[mode]))/1000)):0;const h=Math.floor(t/3600),m=Math.floor((t%3600)/60),s=t%60;el.textContent=[h,m,s].map(x=>String(x).padStart(2,'0')).join(':')};
    tick(); if(started[mode])timerIds[mode]=setInterval(tick,1000);
  }
  window.toggleRun=async function(mode){
    const sw=$(mode.toLowerCase()+'Switch');
    const on=sw&&sw.classList.contains('on');
    if(on){await stop(mode);return}
    await start(mode);
  };
  const oldStart=window.start, oldStop=window.stop;
  window.start=async function(mode){
    const fn=oldStart||(()=>Promise.resolve());
    try{await fn(mode);setSwitch(mode,true)}catch(e){throw e}
  };
  window.stop=async function(mode){
    const fn=oldStop||(()=>Promise.resolve());
    await fn(mode);setSwitch(mode,false);
  };
  const oldEmergency=window.emergency;
  window.emergency=async function(){if(oldEmergency)await oldEmergency();setSwitch('PAPER',false);setSwitch('LIVE',false)};
  window.fsV6Report=function(d){
    const account=Number(d.account_balance_usdt ?? d.equity_usdt ?? d.initial_balance ?? 0);
    const bot=Number(d.bot_balance_usdt ?? d.initial_balance ?? 0);
    const extra=Math.max(0,account-bot);
    if($('acct'))$('acct').textContent=money(account);
    if($('bot'))$('bot').textContent=money(bot);
    if($('extra'))$('extra').textContent=money(extra);
    if($('free'))$('free').textContent='';
    const p=d.positions||[];
    if($('used'))$('used').textContent=p.length+' / 5';
    if($('pnl'))$('pnl').textContent=money(d.net_pnl)+' ('+(d.initial_balance?((Number(d.net_pnl||0)/Number(d.initial_balance))*100).toFixed(2):'0.00')+'%)';
    if($('real'))$('real').textContent=money(d.realized_pnl);
    if($('unreal'))$('unreal').textContent=money(d.unrealized_pnl);
    if($('net'))$('net').textContent=money(d.net_pnl);
    if($('paperStatus') && d.mode==='PAPER')setSwitch('PAPER',!!d.running);
    if($('liveStatus') && d.mode==='LIVE')setSwitch('LIVE',!!d.running);
  };
  // Initial timers continue after reload when the previous session is still running.
  runTimer('PAPER');runTimer('LIVE');
})();
</script>'''
SKIN = SKIN.replace('</body>', JS + '</body>', 1)

# Correct the position presentation in the existing report renderer.
POS_PATCH = "$('positions').innerHTML=p.length?p.map(x=>`<div class=\"pos\"><b>${esc(x.symbol)}</b> • ${x.stage||'OPEN'}<br>Вход ${x.entry_price??'—'} → ${x.current_price??'—'}<br>TP ${x.take_profit??'—'} • SL ${x.stop_loss??'—'} • PnL ${money(x.unrealized_pnl)}</div>`).join(''):'Нет открытых позиций';"
POS_NEW = "$('positions').innerHTML=p.length?p.map(x=>{const entry=Number(x.entry_price||0);const qty=Number(x.amount||0);const expected=x.take_profit!=null?Number(x.take_profit):(qty>0?entry+(Number(d.config?.target_usdt||0.30)/qty):0);return `<div class=\"pos\"><div class=\"position-main\"><b>${esc(x.symbol)}</b> • OPEN</div><div class=\"position-sub\">Вход <b>${entry?entry.toPrecision(9):'—'}</b> → ожидаемый выход <b>${expected?expected.toPrecision(9):'—'}</b></div><div class=\"position-sub\">TP ${x.take_profit??(expected?expected.toPrecision(9):'—')} • SL ${x.stop_loss??'—'} • PnL <b class=\"${Number(x.unrealized_pnl||0)>=0?'green':'red'}\">${money(x.unrealized_pnl)}</b> • ордер ${money(x.allocated_usdt)}</div></div>`}).join(''):'Нет открытых позиций';"
if POS_PATCH not in SKIN:
    raise RuntimeError('Fast Scalper v5 position renderer changed; UI v6 patch needs review')
SKIN = SKIN.replace(POS_PATCH, POS_NEW, 1)

# The original refresh assigns account and bot to the same equity. Replace those
# assignments so the UI uses the distinct report fields.
BAL_PATCH = "$('acct').textContent=money(d.equity_usdt);$('bot').textContent=money(d.equity_usdt);$('free').textContent=money(d.free_usdt);$('extra').textContent=money(Math.max(0,(+d.account_balance_usdt||+d.equity_usdt||0)-(+d.bot_balance_usdt||+d.initial_balance||0)));"
BAL_NEW = "$('acct').textContent=money(d.account_balance_usdt??d.equity_usdt??d.initial_balance);$('bot').textContent=money(d.bot_balance_usdt??d.initial_balance);$('extra').textContent=money(Math.max(0,(+d.account_balance_usdt||+d.equity_usdt||0)-(+d.bot_balance_usdt||+d.initial_balance||0)));"
if BAL_PATCH not in SKIN:
    raise RuntimeError('Fast Scalper v5 balance renderer changed; UI v6 patch needs review')
SKIN = SKIN.replace(BAL_PATCH, BAL_NEW, 1)

@app.get('/', response_class=HTMLResponse)
def home():
    return SKIN
