from . import fast_scalper_beta_001_legacy as legacy
import asyncio
import time
import httpx

_RETRY_STATUS = {502, 503, 504}


def _bases():
    primary = legacy.B.base
    if legacy.B.testnet:
        alt = 'https://api1.testnet.binance.vision/api'
    else:
        alt = 'https://api1.binance.com/api'
    return [primary, alt] if primary != alt else [primary]


async def _get_json(path, *, params=None, headers=None, timeout=8):
    last = None
    for base in _bases():
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as c:
                    r = await c.get(base + path, params=params, headers=headers)
                if r.status_code in _RETRY_STATUS:
                    last = RuntimeError(f'Binance HTTP {r.status_code} from {base}')
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r
            except (httpx.HTTPError, RuntimeError) as e:
                last = e
                if attempt == 0:
                    await asyncio.sleep(0.25)
    raise last or RuntimeError('Binance request failed')


async def ping():
    await _get_json('/v3/ping')


async def account():
    tr = await _get_json('/v3/time')
    server_ms = int(tr.json()['serverTime'])
    p = legacy.B.sign({'timestamp': server_ms})
    r = await _get_json('/v3/account', params=p, headers={'X-MBX-APIKEY': legacy.B.key})
    return r.json()


async def order(params):
    p = dict(params)
    tr = await _get_json('/v3/time')
    p['timestamp'] = int(tr.json()['serverTime'])
    p = legacy.B.sign(p)
    last = None
    for base in _bases():
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(base + '/v3/order', params=p, headers={'X-MBX-APIKEY': legacy.B.key})
            if r.status_code in _RETRY_STATUS:
                last = RuntimeError(f'Binance order HTTP {r.status_code} from {base}')
                continue
            if r.status_code >= 400:
                try: body = r.json()
                except Exception: body = r.text[:500]
                raise RuntimeError(f'Binance order HTTP {r.status_code}: {body}')
            return r.json()
        except (httpx.HTTPError, RuntimeError) as e:
            last = e
    raise last or RuntimeError('Binance order failed')


legacy.B.ping = ping
legacy.B.account = account
legacy.B.order = order
legacy.B._resilience_installed = True
