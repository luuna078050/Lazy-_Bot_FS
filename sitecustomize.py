"""Fast Scalper startup compatibility patch: show Binance Test account balance immediately after mode selection."""
try:
    from app import fast_scalper_beta_001_legacy as _legacy
    _original_state = _legacy.state

    async def _state_with_binance_balance():
        if _legacy.S.get('mode') == 'BINANCE_TEST' and float(_legacy.S.get('account', 0.0) or 0.0) <= 0 and _legacy.B.configured and _legacy.B.testnet:
            try:
                await _legacy.B.ping()
                acc = await _legacy.B.account()
                free_usdt = next((float(x['free']) for x in acc.get('balances', []) if x.get('asset') == 'USDT'), 0.0)
                _legacy.S['account'] = free_usdt
                _legacy.S['reserve'] = max(0.0, free_usdt - float(_legacy.S.get('bot', 0.0) or 0.0))
                _legacy.S['error'] = None
            except Exception as e:
                _legacy.S['error'] = f'Binance TEST account check failed: {type(e).__name__}: {e}'
        return await _original_state()

    _legacy.state = _state_with_binance_balance
except Exception:
    pass
