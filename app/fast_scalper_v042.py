from __future__ import annotations
from . import fast_scalper_v042_base as base

# Keep the proven v0.4.2 engine and patch only the requested test regressions.
base.TRADING_TF = '1m'

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

html = base.HTML
html = html.replace('Trading TF: 3m', 'Trading TF: 1m')
html = html.replace("$('hold').value=String(j.hold_seconds||180);", "if(document.activeElement!==$('hold'))$('hold').value=String(j.hold_seconds||180);")
old_start = "async function start(){try{await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}"
new_start = "async function start(){try{let vs=vals();if(vs.length){await api('/api/slots',{method:'POST',body:JSON.stringify({slots:vs,profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})})}await api('/api/paper/start',{method:'POST',body:JSON.stringify({profit_pct:parseFloat(($('p').value||'0').replace(',','.')),reinvest:$('reinvest').checked,hold_seconds:parseInt($('hold').value)})});await refresh()}catch(e){alert(e.message)}}"
if old_start not in html:
    raise RuntimeError('start handler pattern not found')
base.HTML = html.replace(old_start, new_start)

app = base.app
