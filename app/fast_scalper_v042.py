from __future__ import annotations
import time
from . import fast_scalper_v042_base as base

# Keep the proven v0.4.2 engine and patch only the requested test regressions.
# Trading timeframe stays 1m; holding duration is a separate 1m/3m selector.
base.TRADING_TF = '1m'
base.DEFAULT_HOLD_SECONDS = 60
base.S['hold_seconds'] = 60
# Pydantic v2 keeps the field default in model_fields; update it so omitted values are 1 minute.
base.Start.model_fields['hold_seconds'].default = 60
base.Slots.model_fields['hold_seconds'].default = 60


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

# If Binance is temporarily unavailable, keep retrying the radar instead of marking the
# failed attempt as a successful 60-second cycle. This makes Radar recover automatically.
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
            base.S['last_radar'] = time.time() - base.RADAR_INTERVAL + 5
    except Exception as e:
        base.S['error'] = f'Radar: {type(e).__name__}: {e}'
        base.S['last_radar'] = time.time() - base.RADAR_INTERVAL + 5

base.radar = radar

html = base.HTML
html = html.replace('Trading TF: 3m', 'Trading TF: 1m')
html = html.replace('<option value="60">1 min</option><option value="180" selected>3 min</option>', '<option value="60" selected>1 min</option><option value="180">3 min</option>')
html = html.replace("$('hold').value=String(j.hold_seconds||180);", "if(document.activeElement!==$('hold'))$('hold').value=String(j.hold_seconds||60);")
old_start = "async function start(){try{await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}"
new_start = "async function start(){try{await api('/api/slots',{method:'POST',body:JSON.stringify({slots:vals(),profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}"
if old_start not in html:
    raise RuntimeError('start handler pattern not found')
base.HTML = html.replace(old_start, new_start)

app = base.app
