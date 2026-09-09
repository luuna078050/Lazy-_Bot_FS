"""Start Fast Scalper Beta with Binance Spot Testnet REST endpoint failover."""
import asyncio
import httpx
import uvicorn

from . import fast_scalper_beta_001_legacy as legacy

# Binance's official Spot Testnet docs publish a primary REST endpoint plus
# api1.testnet.binance.vision as an alternate. Keep the existing service and
# fail over only on transient gateway errors.
TESTNET_BASES = [
    "https://testnet.binance.vision/api",
    "https://api1.testnet.binance.vision/api",
]

if legacy.B.testnet:
    legacy.B.base = TESTNET_BASES[0]

_original_ping = legacy.Binance.ping
_original_account = legacy.Binance.account
_original_order = legacy.Binance.order

async def resilient_ping(self):
    bases = TESTNET_BASES if self.testnet else [self.base]
    last = None
    for base in bases:
        self.base = base
        for delay in (0.0, 0.5, 1.5):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await _original_ping(self)
            except httpx.HTTPStatusError as e:
                last = e
                if e.response is None or e.response.status_code not in {502, 503, 504}:
                    raise
    if last:
        raise last

async def resilient_account(self):
    bases = TESTNET_BASES if self.testnet else [self.base]
    last = None
    for base in bases:
        self.base = base
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
                if not any(f"Binance HTTP {code}:" in str(e) for code in (502, 503, 504)):
                    raise
    if last:
        raise last

async def resilient_order(self, params):
    bases = TESTNET_BASES if self.testnet else [self.base]
    last = None
    for base in bases:
        self.base = base
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
                if not any(f"Binance order HTTP {code}:" in str(e) for code in (502, 503, 504)):
                    raise
    if last:
        raise last

legacy.Binance.ping = resilient_ping
legacy.Binance.account = resilient_account
legacy.Binance.order = resilient_order

if __name__ == "__main__":
    uvicorn.run("app.fast_scalper_beta_001:app", host="0.0.0.0", port=int(__import__("os").environ["PORT"]))
