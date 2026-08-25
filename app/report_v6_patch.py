from __future__ import annotations

import json
import time
from typing import Any
from fastapi import HTTPException
from .fixed_app import app
from . import fixed_app as core
from .paper_engine import snapshot as paper_snapshot
from .market_radar import RADAR


def _remove_report_route():
    for r in list(app.router.routes):
        if getattr(r, 'path', None) == '/api/session/report/{mode}':
            app.router.routes.remove(r)


def _ws_price(symbol: str) -> float:
    key = symbol.replace('/', '').upper()
    with RADAR.lock:
        d = RADAR.tickers.get(key) or {}
        return float(d.get('c') or 0)


def _paper_report() -> dict[str, Any]:
    s = paper_snapshot()
    positions = s.get('open_positions') or {}
    account = float(s.get('balance', s.get('initial_balance', 0)) or 0)
    bot = float(s.get('initial_balance', 0) or 0)
    realized = float(s.get('pnl', 0) or 0)
    open_value = 0.0
    for p in positions.values() if isinstance(positions, dict) else []:
        px = _ws_price(str(p.get('symbol','')))
        open_value += px * float(p.get('amount',0) or 0) if px else float(p.get('allocated_usdt',0) or 0)
    equity = account + open_value
    unrealized = equity - bot - realized
    return {
        'mode': 'PAPER', 'running': bool(s.get('running', False)),
        'started_at': s.get('started_at'), 'stopped_at': s.get('stopped_at'),
        'initial_balance': bot, 'account_balance_usdt': equity,
        'bot_balance_usdt': bot, 'free_usdt': account,
        'equity_usdt': equity, 'realized_pnl': realized,
        'unrealized_pnl': unrealized, 'net_pnl': realized + unrealized,
        'assets': [], 'positions': list(positions.values()) if isinstance(positions, dict) else [],
        'orders': list((s.get('orders') or {}).values()),
        'order_history': [], 'trades': (s.get('trades') or [])[-50:],
        'config': s.get('config') or {}, 'stop_type': s.get('stop_type'),
        'error': s.get('error'), 'accumulated_profit_usdt': realized,
        'available_to_attract_usdt': max(0.0, realized),
        'profit_policy': 'FIXED_BOT_CAPITAL_ACCUMULATE_PROFIT',
    }


def _live_report() -> dict[str, Any]:
    try:
        state = json.loads(core.LIVE_STATE.read_text()) if core.LIVE_STATE.exists() else {}
    except Exception:
        state = {}
    positions=[]; assets=[]
    for symbol,p in (state.get('positions') or {}).items():
        px=_ws_price(symbol); qty=float(p.get('amount') or 0); cap=float(p.get('capital') or 0)
        value=qty*px if px else cap; upnl=value-cap
        positions.append({**p,'symbol':symbol,'current_price':px,'market_value':value,'unrealized_pnl':upnl,'age_sec':max(0,time.time()-float(p.get('opened') or time.time())),'stage':'OPEN'})
        assets.append({'asset':symbol.split('/')[0],'amount':qty,'price':px,'value_usdt':value,'unrealized_pnl':upnl})
    free=float(state.get('free_capital') or 0); bot=float(state.get('capital') or 0); equity=free+sum(float(x['market_value']) for x in positions); realized=float(state.get('realized_pnl') or 0); running=bool(core.LIVE_PROC and core.LIVE_PROC.poll() is None)
    return {'mode':'LIVE','running':running,'started_at':state.get('started_at'),'stopped_at':state.get('stopped_at'),'initial_balance':bot,'account_balance_usdt':equity,'bot_balance_usdt':bot,'free_usdt':free,'equity_usdt':equity,'realized_pnl':realized,'unrealized_pnl':equity-bot-realized,'net_pnl':equity-bot,'assets':assets,'positions':positions,'orders':list((state.get('orders') or {}).values()),'order_history':(state.get('order_history') or [])[-30:],'trades':list(state.get('trades') or [])[-50:],'config':state.get('config') or {},'stop_type':state.get('stop_type'),'error':state.get('error'),'accumulated_profit_usdt':realized,'available_to_attract_usdt':max(0.0,equity-bot),'profit_policy':'FIXED_BOT_CAPITAL_ACCUMULATE_PROFIT'}


def install():
    _remove_report_route()
    @app.get('/api/session/report/{mode}')
    def session_report_v6(mode: str):
        if mode.upper() == 'PAPER': return _paper_report()
        if mode.upper() == 'LIVE': return _live_report()
        raise HTTPException(400, 'Unknown mode')
