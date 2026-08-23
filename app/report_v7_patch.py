from __future__ import annotations

from fastapi import HTTPException
from .fixed_app import app
from .report_v6_patch import _paper_report, _live_report, _remove_report_route


def _paper_report_v7():
    d = _paper_report()
    bot = float(d.get('bot_balance_usdt', d.get('initial_balance', 0)) or 0)
    account = float(d.get('account_balance_usdt', bot) or bot)
    accumulated = account - bot
    d['accumulated_profit_usdt'] = accumulated
    d['account_balance_usdt'] = account
    d['bot_balance_usdt'] = bot
    d['available_to_attract_usdt'] = max(0.0, account - bot)
    d['profit_policy'] = 'FIXED_BOT_CAPITAL_ACCUMULATE_PROFIT'
    return d


def _live_report_v7():
    d = _live_report()
    state_account = getattr(__import__('app.fixed_app', fromlist=['LIVE_STATE']), 'LIVE_STATE', None)
    start_account = 0.0
    try:
        import json
        if state_account and state_account.exists():
            s = json.loads(state_account.read_text())
            start_account = float(s.get('account_start_balance_usdt', s.get('account_balance_usdt', 0)) or 0)
    except Exception:
        start_account = 0.0
    bot = float(d.get('bot_balance_usdt', d.get('initial_balance', 0)) or 0)
    accumulated = float(d.get('realized_pnl', 0) or 0)
    account = start_account + accumulated if start_account > 0 else bot + accumulated
    d['account_balance_usdt'] = account
    d['bot_balance_usdt'] = bot
    d['accumulated_profit_usdt'] = accumulated
    d['available_to_attract_usdt'] = max(0.0, account - bot)
    d['profit_policy'] = 'FIXED_BOT_CAPITAL_ACCUMULATE_PROFIT'
    return d


def install():
    _remove_report_route()

    @app.get('/api/session/report/{mode}')
    def session_report_v7(mode: str):
        mode = mode.upper()
        if mode == 'PAPER':
            return _paper_report_v7()
        if mode == 'LIVE':
            return _live_report_v7()
        raise HTTPException(400, 'Unknown mode')
