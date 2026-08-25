from __future__ import annotations

import json
import time
from typing import Any
from fastapi import HTTPException
from .fixed_app import app
from . import fixed_app as core
from .profit_first_engine import snapshot as paper_snapshot
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
    positions = s.get('positions') or []
    account = float(s.get('account_balance_usdt', s.get('equity_usdt', s.get('initial_balance', 0))) or 0)
    bot = float(s.get('bot_balance_usdt', s.get('initial_balance', 0)) or 0)
    return {
        'mode': 'PAPER', 'running': bool(s.get('running', False)),
        'started_at': s.get('started_at'), 'stopped_at': s.get('stopped_at'),
        'initial_balance': float(s.get('initial_balance', 0) or 0),
        'account_balance_usdt': account, 'bot_balance_usdt': bot,
        'free_usdt': float(s.get('free_usdt', 0) or 0),
        'equity_usdt': float(s.get('equity_usdt', account) or account),
        'realized_pnl': float(s.get('realized_pnl', 0) or 0),
        'unrealized_pnl': float(s.get('unrealized_pnl', 0) or 0),
        'net_pnl': float(s.get('net_pnl', 0) or 0),
        'assets': s.get('assets') or [], 'positions': positions,
        'orders': list((s.get('orders') or {}).values()),
        'order_history': (s.get('order_history') or [])[-30:],
        'trades': (s.get('trades') or [])[-50:], 'config': s.get('config') or {},
        'stop_type': s.get('stop_type'), 'error': s.get('error'),
        'win_rate': float(s.get('win_rate', 0) or 0),
        'closed_trades': int(s.get('closed_trades', 0) or 0),
        'target_win_rate': float(s.get('target_win_rate', 70) or 70),
        'adaptive_quality_threshold': float(s.get('adaptive_quality_threshold', 58) or 58),
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
    free=float(state.get('free_capital') or 0); bot=float(state.get('capital') or 0)
    equity=free+sum(float(x['market_value']) for x in positions)
    realized=float(state.get('realized_pnl') or 0)
    running=bool(core.LIVE_PROC and core.LIVE_PROC.poll() is None)
    return {'mode':'LIVE','running':running,'started_at':state.get('started_at'),'stopped_at':state.get('stopped_at'),
            'initial_balance':bot,'account_balance_usdt':equity,'bot_balance_usdt':bot,'free_usdt':free,
            'equity_usdt':equity,'realized_pnl':realized,'unrealized_pnl':equity-bot-realized,'net_pnl':equity-bot,
            'assets':assets,'positions':positions,'orders':list((state.get('orders') or {}).values()),
            'order_history':(state.get('order_history') or [])[-30:],'trades':list(state.get('trades') or [])[-50:],
            'config':state.get('config') or {},'stop_type':state.get('stop_type'),'error':state.get('error')}


def install():
    _remove_report_route()
    @app.get('/api/session/report/{mode}')
    def session_report_v6(mode: str):
        if mode.upper() == 'PAPER': return _paper_report()
        if mode.upper() == 'LIVE': return _live_report()
        raise HTTPException(400, 'Unknown mode')
