from __future__ import annotations

import json
from fastapi import HTTPException
from .fixed_app import app, LIVE_STATE
from .exchange_gateway import gateway


def install():
    original = None
    for route in list(app.router.routes):
        if getattr(route, 'path', None) == '/api/live/start' and 'POST' in (getattr(route, 'methods', None) or set()):
            original = route.endpoint
            app.router.routes.remove(route)
            break
    if original is None:
        return

    @app.post('/api/live/start')
    def live_start_with_account_snapshot(payload: dict):
        key = str(payload.get('api_key', '')).strip()
        secret = str(payload.get('api_secret', '')).strip()
        if not key or not secret:
            raise HTTPException(400, 'Для LIVE нужны Binance API Key и Secret')
        try:
            g = gateway('binance')
            g.exchange.apiKey = key
            g.exchange.secret = secret
            g.load_markets()
            balance = g.exchange.fetch_balance()
            account = float((balance.get('free') or {}).get('USDT') or 0)
        except Exception as exc:
            raise HTTPException(400, f'Binance preflight не пройден: {str(exc)[:240]}')
        state = {}
        try:
            if LIVE_STATE.exists():
                state = json.loads(LIVE_STATE.read_text())
        except Exception:
            state = {}
        state['account_start_balance_usdt'] = account
        state['account_balance_usdt'] = account
        state['profit_policy'] = 'FIXED_BOT_CAPITAL_ACCUMULATE_PROFIT'
        LIVE_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        return original(payload)
