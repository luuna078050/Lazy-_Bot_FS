from . import fast_scalper_beta_001_legacy as legacy
from fastapi import HTTPException
import time
from . import binance_resilience
from .fast_scalper_antloss import manage as anti_loss_manage

legacy.manage = anti_loss_manage

_original_close = legacy.close
async def close_with_timestamp(p, reason):
    result = await _original_close(p, reason)
    try:
        for item in legacy.S.get('closed', []):
            if item.get('symbol') == p.get('symbol'):
                item['closed_at'] = time.time()
                break
    except Exception:
        pass
    return result
legacy.close = close_with_timestamp

_original_start = legacy.start
async def start_clean(b):
    result = await _original_start(b)
    legacy.S['closed'] = []
    legacy.S['orders'] = []
    return await legacy.state()

for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/api/paper/start' and 'POST' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.post('/api/paper/start')
async def start_endpoint(b: legacy.Start):
    return await start_clean(b)

async def reset_fixed():
    if legacy.S.get('running') or legacy.S.get('positions'):
        raise HTTPException(400, 'BOT OFF and no open positions required')
    s = legacy.S
    s['running'] = False
    s['bot'] = 0.0
    s['free'] = 0.0
    s['realized'] = 0.0
    s['session_realized'] = 0.0
    s['session_trades'] = 0
    s['session_started'] = None
    s['session_elapsed'] = 0.0
    s['day_started'] = None
    s['day_elapsed'] = 0.0
    s['positions'] = []
    s['closed'] = []
    s['orders'] = []
    s['slots'] = [None] * legacy.MAX_SLOTS
    s['profit'] = 0.41
    s['reinvest'] = False
    s['cycle'] = 0
    s['last_radar'] = 0.0
    s['error'] = None
    if s.get('mode') == 'PAPER':
        s['account'] = legacy.START
        s['reserve'] = legacy.START
    else:
        s['reserve'] = max(0.0, float(s.get('account', 0.0) or 0.0))
    return await legacy.state()

for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/api/reset' and 'POST' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.post('/api/reset')
async def reset_endpoint():
    return await reset_fixed()

# Reconcile AUTO TOP-6 with live positions. The old endpoint changed slot
# symbols without reconciling positions tied to the old slot index. That can
# leave stale positions attached to changed slots and can create duplicate
# symbols during rotation.
for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/api/slots/auto-top6' and 'POST' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.post('/api/slots/auto-top6')
async def auto_top6_fixed(b: legacy.Slots):
    await legacy.radar(True)
    ranked=[]
    seen=set()
    for x in legacy.S.get('ranking',[]):
        s=str(x.get('symbol','')).upper().replace('/','')
        if s and s not in seen:
            ranked.append(s)
            seen.add(s)
    target=ranked[:legacy.MAX_SLOTS]
    old=list(legacy.S.get('slots',[]))
    for i in range(legacy.MAX_SLOTS):
        old_s=str(old[i] or '').upper().replace('/','')
        new_s=str(target[i] if i < len(target) else '').upper().replace('/','')
        if old_s != new_s:
            for p in list(legacy.S.get('positions',[])):
                if p.get('slot') == i:
                    try:
                        await legacy.close(p,'ROTATION')
                    except Exception as e:
                        legacy.S['error']=f'Rotation close {p.get("symbol")}: {type(e).__name__}: {e}'
    legacy.S['slots']=target+[None]*(legacy.MAX_SLOTS-len(target))
    legacy.S['profit']=b.profit_pct
    legacy.S['reinvest']=b.reinvest
    return await legacy.state()

html = legacy.HTML
html = html.replace(
    '.row{display:flex;gap:8px;flex-wrap:wrap}',
    '.row{display:flex;gap:8px;flex-wrap:wrap}.allocation-row{display:grid;grid-template-columns:minmax(100px,150px) auto auto;gap:8px;align-items:center}.allocation-actions{font-size:11px!important;padding:8px 10px!important;white-space:nowrap}.profit-row{margin-top:8px;align-items:center}'
)
html = html.replace(
    '<div class="card"><div class="row"><input id="allocation" class="input amount" type="number" step="0.01" min="0" placeholder="Amount"><button type="button" class="btn test" id="allocBtn">SET BOT BALANCE</button><button type="button" class="btn stop" id="withdrawBtn">WITHDRAW</button><input id="profit" class="input" type="number" step="0.01" value="0.41"><label style="padding:10px"><input id="reinvest" type="checkbox" checked> Reinvest</label></div>',
    '<div class="card"><div class="allocation-row"><input id="allocation" class="input amount" type="number" step="0.01" min="0" placeholder="Amount"><button type="button" class="btn test allocation-actions" id="allocBtn">SET BOT BALANCE</button><button type="button" class="btn stop allocation-actions" id="withdrawBtn">WITHDRAW</button></div><div class="row profit-row"><input id="profit" class="input" type="number" step="0.01" value="0.41"><label style="padding:10px"><input id="reinvest" type="checkbox" checked> Reinvest</label></div>'
)
html = html.replace(
    '.line{font-size:12px;',
    '.profit-pos{color:#16c784;font-weight:700}.profit-neg{color:#ff4d5f;font-weight:700}.line{font-size:12px;'
)
html = html.replace(
    '.profit-pos{color:#16c784;font-weight:700}.profit-neg{color:#ff4d5f;font-weight:700}.line{font-size:12px;',
    '.profit-pos{color:#16c784;font-weight:700}.profit-neg{color:#ff4d5f;font-weight:700}.pos-line{display:flex;align-items:center;gap:6px;font-size:11px;padding:4px 0;border-bottom:1px solid #24314a}.pos-main{min-width:0;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pos-timer{flex:0 0 auto;font-weight:800}.line{font-size:12px;'
)
html = html.replace(
    "$('pos').innerHTML=p.length?p.map(x=>`<div class=\"line\">${x.symbol} · ${num(x.stake)} USDT · ${num(x.current)}</div>`).join(''):'No open positions';",
    "$('pos').innerHTML=p.length?p.map(x=>{const d=(Number(x.current||0)/Number(x.entry||x.current||1)-1)*100;const age=Math.max(0,Math.floor(Date.now()/1000-Number(x.opened||Date.now()/1000)));return `<div class=\"pos-line\"><span class=\"pos-main\">${x.symbol} · ${num(x.stake)} USDT · IN ${num(x.entry)} · Δ ${d>=0?'+':''}${d.toFixed(3)}% · OUT ${num(x.current)}</span><span class=\"pos-timer\">${clock(age)}</span></div>`}).join(''):'No open positions';"
)
html = html.replace(
    "$('closed').innerHTML=(state.closed||[]).slice(0,5).map(x=>`<div class=\"line\">${x.symbol} · ${x.reason} · ${num(x.pnl)} USDT · ${num(x.exit)}</div>`).join('')||'No closed trades';",
    "$('closed').innerHTML=(state.closed||[]).slice(0,5).map(x=>{const pnl=Number(x.pnl||0);const ts=Number(x.closed_at||0);const t=ts?new Date(ts*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}):'--:--:--';return `<div class=\"line ${pnl>=0?'profit-pos':'profit-neg'}\">${x.symbol} · ${x.reason} · ${pnl>=0?'+':''}${pnl.toFixed(4)} USDT · ${num(x.stake)} · ${num(x.entry)}→${num(x.exit)} · ${t}</div>`}).join('')||'No closed trades';"
)
legacy.HTML = html
