from __future__ import annotations
import time
from . import fast_scalper_v042_base as base
from fastapi.dependencies.utils import get_dependant

# Keep the proven v0.4.2 engine and patch only the requested test regressions.
# Trading timeframe stays 1m; holding duration is a separate 1m/3m selector.
base.TRADING_TF = '1m'
base.DEFAULT_HOLD_SECONDS = 60
base.S['hold_seconds'] = 60
base.Start.model_fields['hold_seconds'].default = 60
base.Slots.model_fields['hold_seconds'].default = 60

# Paper-test risk guard: a timeout must never be allowed to turn into a deep loss.
# Profit target remains user-selected; this is only a hard adverse-move guard.
MAX_LOSS_PCT = 0.30


def close_position(p, reason):
    ep = p['entry']
    xp = p.get('current') or base.qprice(p['symbol']) or ep
    pnl = (xp / ep - 1) * p['stake']
    base.S['free'] += p['stake']
    if base.S['reinvest']:
        base.S['free'] += pnl
        base.S['bot'] += pnl
    else:
        base.S['account'] += pnl
    base.S['realized'] += pnl
    base.S['session_realized'] += pnl
    base.S['session_trades'] += 1
    base.S['closed'].insert(0, dict(p, exit=xp, pnl=pnl, reason=reason, closed_at=base.now()))
    base.S['closed'] = base.S['closed'][:100]
    base.S['orders'].insert(0, {'time':base.now(),'symbol':p['symbol'],'side':'SELL','status':'FILLED','price':xp,'slot':p['slot'],'pnl':pnl,'reason':reason})
    base.S['positions'].remove(p)

base.close_position = close_position

# Auto TOP-6 must be explicit. PAPER ON must never silently refill six old/radar pairs.
def fill_auto_slots_disabled():
    return None
base.fill_auto_slots = fill_auto_slots_disabled

# Retry Radar after failures instead of waiting a full minute.
async def radar(force=False):
    if not force and base.S['last_radar'] and time.time()-base.S['last_radar'] < base.RADAR_INTERVAL:
        return
    try:
        base.S['ranking'] = await base.build_ranking()
        if base.S['ranking']:
            base.S['last_radar'] = time.time()
            base.S['error'] = None
        else:
            base.S['error'] = 'Radar: no ranking data'
            base.S['last_radar'] = time.time()-base.RADAR_INTERVAL+5
    except Exception as e:
        base.S['error'] = f'Radar: {type(e).__name__}: {e}'
        base.S['last_radar'] = time.time()-base.RADAR_INTERVAL+5

base.radar = radar

# Replace the base position manager so the paper engine has a hard loss guard.
async def manage_positions():
    if not base.S['positions']:
        return
    try:
        ticks = await base.get_json('/api/v3/ticker/price')
        latest = {x.get('symbol'): float(x.get('price')) for x in ticks if isinstance(x,dict) and x.get('symbol')}
    except Exception:
        latest = {}
    for p in list(base.S['positions']):
        p['current'] = latest.get(p['symbol']) or base.qprice(p['symbol']) or p.get('current') or p['entry']
        age = time.time() - p['opened']
        live = (p['current'] / p['entry'] - 1) * 100
        if base.S['profit'] > 0 and live >= base.S['profit']:
            close_position(p, 'PROFIT_TARGET')
        elif live <= -MAX_LOSS_PCT:
            close_position(p, 'MAX_LOSS')
        elif age >= base.S['hold_seconds']:
            close_position(p, 'TIMEOUT')

base.manage_positions = manage_positions

# Dedicated hold-duration endpoint: changing the selector immediately updates the engine.
@base.app.post('/api/hold')
async def set_hold(body: dict):
    try:
        hold = int(body.get('hold_seconds'))
    except Exception:
        raise base.HTTPException(400, 'hold_seconds must be 60 or 180')
    if hold not in (60, 180):
        raise base.HTTPException(400, 'hold_seconds must be 60 or 180')
    base.S['hold_seconds'] = hold
    return await base.state()

# Manual pairs must not depend on Radar/ticker validation being available.
# Binance price lookup is still used when the engine actually opens the position.
@base.app.post('/api/slots_manual')
async def slots_manual(b: base.Slots):
    clean = [x.upper().replace('/','') for x in b.slots if x.strip()]
    if len(clean) > base.MAX_SLOTS:
        raise base.HTTPException(400, f'Maximum {base.MAX_SLOTS} pairs')
    if base.S['positions']:
        raise base.HTTPException(400, 'Close current positions before changing slots')
    base.S['slots'] = [{'symbol':clean[i], 'tf':base.TRADING_TF, 'auto':False} if i < len(clean) else None for i in range(base.MAX_SLOTS)]
    base.S['profit'] = b.profit_pct
    base.S['reinvest'] = b.reinvest
    base.S['hold_seconds'] = b.hold_seconds
    return await base.state()

# Replace the original /api/slots route endpoint with the non-blocking manual version.
for _route in base.app.routes:
    if getattr(_route, 'path', None) == '/api/slots' and 'POST' in getattr(_route, 'methods', set()):
        _route.endpoint = slots_manual
        _route.dependant = get_dependant(path=_route.path, call=slots_manual)
        break

html = base.HTML
html = html.replace('Trading TF: 3m', 'Trading TF: 1m')
html = html.replace('<option value="60">1 min</option><option value="180" selected>3 min</option>', '<option value="60" selected>1 min</option><option value="180">3 min</option>')
html = html.replace("$('hold').value=String(j.hold_seconds||180);", "if(document.activeElement!==$('hold'))$('hold').value=String(j.hold_seconds||60);")
html = html.replace('id="hold"', 'id="hold" onchange="holdChanged()"')
hold_marker = "async function start(){"
hold_handler = "async function holdChanged(){try{await api('/api/hold',{method:'POST',body:JSON.stringify({hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}\n"
if hold_handler not in html:
    html = html.replace(hold_marker, hold_handler + hold_marker, 1)
# Do not let the 1-second refresh overwrite manual slot editing.
html = html.replace("let editingSlots=false;", "let editingSlots=false;let holdEditing=false;")
html = html.replace("$('hold').value=String(j.hold_seconds||180);", "if(!holdEditing)$('hold').value=String(j.hold_seconds||60);")
html = html.replace("$('hold').value=String(j.hold_seconds||60);", "if(!holdEditing)$('hold').value=String(j.hold_seconds||60);")
html = html.replace("async function holdChanged(){", "async function holdChanged(){holdEditing=false;")
html = html.replace("$('hold').addEventListener", "$('hold').addEventListener('focus',()=>holdEditing=true);$('hold').addEventListener") if "$('hold').addEventListener" in html else html
old_start = "async function start(){try{await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}"
new_start = "async function start(){try{await api('/api/slots',{method:'POST',body:JSON.stringify({slots:vals(),profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}"
if old_start not in html:
    raise RuntimeError('start handler pattern not found')
base.HTML = html.replace(old_start, new_start)

app = base.app
