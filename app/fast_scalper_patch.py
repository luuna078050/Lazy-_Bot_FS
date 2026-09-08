from . import fast_scalper_beta_001_legacy as legacy
from .fast_scalper_antloss import manage as anti_loss_manage

# Restore the previous anti-loss timeout behavior without changing the trading engine structure.
legacy.manage = anti_loss_manage

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
    "$('closed').innerHTML=(state.closed||[]).slice(0,5).map(x=>`<div class=\"line\">${x.symbol} · ${x.reason} · ${num(x.pnl)} USDT · ${num(x.exit)}</div>`).join('')||'No closed trades';",
    "$('closed').innerHTML=(state.closed||[]).slice(0,5).map(x=>`<div class=\"line ${Number(x.pnl)>=0?'profit-pos':'profit-neg'}\">${x.symbol} · ${x.reason} · ${num(x.pnl)} USDT · ${num(x.exit)}</div>`).join('')||'No closed trades';"
)
legacy.HTML = html
