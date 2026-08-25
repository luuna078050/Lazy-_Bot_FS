from __future__ import annotations

import inspect
import os
import threading
import time
import urllib.request

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.routing import request_response

from . import fixed_app as core
from .profit_first_engine_v4 import snapshot as paper_snapshot
from .market_radar import RADAR


_KEEPALIVE_STARTED = False


def _remove_route(path: str):
    for route in list(core.app.router.routes):
        if getattr(route, 'path', None) == path and getattr(route, 'methods', None):
            core.app.router.routes.remove(route)


def _ws_price(symbol: str) -> float:
    key = symbol.replace('/', '').upper()
    with RADAR.lock:
        row = RADAR.tickers.get(key) or {}
    return float(row.get('c') or 0)


def _paper_report() -> dict:
    s = paper_snapshot()
    positions = s.get('open_positions') or {}
    account = float(s.get('balance', s.get('initial_balance', 0)) or 0)
    bot = float(s.get('initial_balance', 0) or 0)
    realized = float(s.get('pnl', 0) or 0)
    open_value = 0.0
    for p in positions.values() if isinstance(positions, dict) else []:
        px = _ws_price(str(p.get('symbol', '')))
        open_value += px * float(p.get('amount', 0) or 0) if px else float(p.get('allocated_usdt', 0) or 0)
    equity = account + open_value
    unrealized = equity - bot - realized
    return {
        'mode': 'PAPER', 'running': bool(s.get('running', False)),
        'started_at': s.get('started_at'), 'stopped_at': s.get('stopped_at'),
        'initial_balance': bot, 'account_balance_usdt': equity,
        'bot_balance_usdt': bot, 'free_usdt': account, 'equity_usdt': equity,
        'realized_pnl': realized, 'unrealized_pnl': unrealized,
        'net_pnl': realized + unrealized,
        'assets': [], 'positions': list(positions.values()) if isinstance(positions, dict) else [],
        'orders': list((s.get('orders') or {}).values()),
        'order_history': list((s.get('order_history') or [])[-50:]),
        'trades': list((s.get('trades') or [])[-50:]),
        'config': s.get('config') or {}, 'stop_type': s.get('stop_type'),
        'error': s.get('error'),
        'accumulated_profit_usdt': realized,
        'available_to_attract_usdt': max(0.0, realized),
        'target_pnl_per_min_per_100': s.get('target_pnl_per_min_per_100', 1.73),
        'realized_pnl_last_minute': s.get('realized_pnl_last_minute', 0.0),
        'throughput_pnl_per_min_per_100': s.get('throughput_pnl_per_min_per_100', 0.0),
        'profit_policy': 'FIXED_BOT_CAPITAL_ACCUMULATE_PROFIT',
    }


def _install_correct_paper_report():
    _remove_route('/api/session/report/{mode}')

    @core.app.get('/api/session/report/{mode}')
    def session_report(mode: str):
        mode = mode.upper()
        if mode == 'PAPER':
            return _paper_report()
        # Preserve the existing LIVE report implementation by importing it
        # only for LIVE. PAPER must never read the obsolete paper_engine state.
        from .report_v7_patch import _live_report_v7
        if mode == 'LIVE':
            return _live_report_v7()
        raise HTTPException(400, 'Unknown mode')


def _keepalive_loop():
    while True:
        try:
            base = os.getenv('RENDER_EXTERNAL_URL', '').rstrip('/')
            urls = [base + '/api/health?ka=1'] if base else []
            urls.append(f"http://127.0.0.1:{os.getenv('PORT', '8000')}/api/health?ka=1")
            for url in urls:
                try:
                    with urllib.request.urlopen(url, timeout=8) as r:
                        r.read(32)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(60)


def _start_keepalive():
    global _KEEPALIVE_STARTED
    if _KEEPALIVE_STARTED:
        return
    _KEEPALIVE_STARTED = True
    threading.Thread(target=_keepalive_loop, daemon=True, name='fast-scalper-render-keepalive').start()


def _install_ui_fix():
    route = next((r for r in core.app.router.routes if getattr(r, 'path', None) == '/'), None)
    if route is None or not hasattr(route, 'endpoint'):
        return
    original = route.endpoint
    if getattr(original, '_fs_v14_fix', False):
        return

    def endpoint(*args, **kwargs):
        response = original() if not inspect.signature(original).parameters else original(*args, **kwargs)
        html = response.body.decode('utf-8') if isinstance(response, HTMLResponse) and isinstance(response.body, (bytes, bytearray)) else str(response)
        css = r'''<style id="fs-v14-fix-css">
/* Manual "Добавить пару" input is obsolete: radar already provides the ranked pairs. */
input[placeholder*="Добавить пару"], div:has(> input[placeholder*="Добавить пару"]){display:none!important}
</style>'''
        js = r'''<script id="fs-v14-fix-js">
(function(){
  function cleanPairAdder(){
    document.querySelectorAll('input[placeholder*="Добавить пару"]').forEach(function(input){
      var box=input.closest('div');
      if(box)box.remove();
    });
  }
  function stabilizeControls(){
    cleanPairAdder();
    var paper=document.getElementById('paperSwitch'),live=document.getElementById('liveSwitch');
    if(paper)paper.setAttribute('aria-label','PAPER');
    if(live)live.setAttribute('aria-label','LIVE');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',stabilizeControls);else setTimeout(stabilizeControls,50);
  setInterval(stabilizeControls,1000);
})();
</script>'''
        html = html.replace('</head>', css + '</head>', 1)
        html = html.replace('</body>', js + '</body>', 1)
        headers = dict(getattr(response, 'headers', {}) or {})
        for k in ('content-length','Content-Length','content-type','Content-Type'):
            headers.pop(k, None)
        headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return HTMLResponse(content=html, status_code=getattr(response, 'status_code', 200), headers=headers, media_type='text/html')

    endpoint._fs_v14_fix = True
    route.endpoint = endpoint
    route.app = request_response(endpoint)


def install(app):
    _install_correct_paper_report()
    _install_ui_fix()
    _start_keepalive()
