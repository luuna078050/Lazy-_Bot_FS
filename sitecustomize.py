"""Fast Scalper startup compatibility and Binance Testnet resilience patch."""
try:
    import asyncio
    import httpx
    from app import fast_scalper_beta_001_legacy as _legacy

    # Binance Testnet can intermittently return 502/503/504 from /ping even when
    # the signed account/order endpoints are reachable. Do not make that probe
    # a hard prerequisite for the real API operation.
    _original_ping = _legacy.Binance.ping
    async def _resilient_ping(self):
        last = None
        for delay in (0.0, 0.5, 1.5):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await _original_ping(self)
            except httpx.HTTPStatusError as e:
                last = e
                if e.response is None or e.response.status_code not in {502, 503, 504}:
                    raise
        return None
    _legacy.Binance.ping = _resilient_ping

    # Retry transient gateway errors on the signed account request as well.
    _original_account = _legacy.Binance.account
    async def _resilient_account(self):
        last = None
        for delay in (0.0, 0.5, 1.5):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await _original_account(self)
            except httpx.HTTPStatusError as e:
                last = e
                if e.response is None or e.response.status_code not in {502, 503, 504}:
                    raise
            except RuntimeError as e:
                last = e
                text = str(e)
                if not any(f'Binance HTTP {code}:' in text for code in (502, 503, 504)):
                    raise
        raise last
    _legacy.Binance.account = _resilient_account

    # Apply the same transient-gateway retry to signed orders so a temporary
    # Binance edge 502 does not immediately turn into a failed trade operation.
    _original_order = _legacy.Binance.order
    async def _resilient_order(self, params):
        last = None
        for delay in (0.0, 0.5, 1.5):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await _original_order(self, params)
            except httpx.HTTPStatusError as e:
                last = e
                if e.response is None or e.response.status_code not in {502, 503, 504}:
                    raise
            except RuntimeError as e:
                last = e
                text = str(e)
                if not any(f'Binance order HTTP {code}:' in text for code in (502, 503, 504)):
                    raise
        raise last
    _legacy.Binance.order = _resilient_order

    # Keep the existing balance-overlay behavior, but let the resilient
    # Binance methods above handle transient gateway responses.
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
