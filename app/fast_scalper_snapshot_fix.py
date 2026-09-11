from __future__ import annotations
import time
from datetime import datetime, timezone

from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_final_patch as final
from . import fast_scalper_radar_timeframes_fix  # noqa: F401

# Requested maximum normal trade duration: 90 seconds.
# Profit target can close earlier; 90s is the timeout horizon.
legacy.MAX_AGE = 90

_original_final_close_safe = final.close_safe

async def close_snapshot_safe(p, reason, timeout=10.0):
    """Close PAPER positions against the exact price snapshot that triggered the close.

    Also normalize closed_at to an ISO UTC timestamp so the browser does not interpret
    Unix seconds as milliseconds. Binance TEST keeps the real filled SELL path.
    """
    symbol = str(p.get('symbol', '')).upper().replace('/', '')
    if legacy.S.get('mode') != 'PAPER':
        return await _original_final_close_safe(p, reason, timeout)

    try:
        entry = float(p.get('entry') or 0)
        stake = float(p.get('stake') or 0)
        xp = float(p.get('current') or 0) or float(legacy.price(symbol) or entry)
        if entry <= 0 or stake <= 0 or xp <= 0:
            raise RuntimeError(f'invalid close snapshot entry={entry} stake={stake} price={xp}')

        pnl = (xp / entry - 1.0) * stake
        if reason == 'PROFIT_TARGET' and pnl < 0:
            print(f'[TRADE] PT_REJECT {symbol} snapshot_pnl={pnl:.8f} USDT price={xp}', flush=True)
            reason = 'PRICE_RETRACE'

        now_iso = datetime.now(timezone.utc).isoformat()
        legacy.S['free'] += stake
        if legacy.S.get('reinvest'):
            legacy.S['bot'] += pnl
        else:
            legacy.S['account'] += pnl
        legacy.refresh_reserve()
        legacy.S['realized'] += pnl
        legacy.S['session_realized'] += pnl
        legacy.S['session_trades'] += 1
        legacy.S['orders'].insert(0, {
            'time': now_iso, 'symbol': symbol, 'side': 'SELL',
            'price': xp, 'pnl': pnl, 'reason': reason,
        })
        closed = dict(p, exit=xp, pnl=pnl, reason=reason, closed_at=now_iso)
        legacy.S['closed'].insert(0, closed)
        legacy.S['closed'] = legacy.S['closed'][:100]
        legacy.S['positions'].remove(p)
        print(f'[TRADE] CLOSE_OK {symbol} reason={reason} pnl={pnl:.8f} price={xp} age={max(0,time.time()-float(p.get("opened") or time.time())):.1f}s', flush=True)
        return True
    except Exception as e:
        legacy.S['error'] = f'Close {symbol}: {type(e).__name__}: {e}'
        print(f'[TRADE] CLOSE_ERROR {symbol} reason={reason} {type(e).__name__}: {e}', flush=True)
        return False

# All lifecycle paths in fast_scalper_final_patch resolve close_safe dynamically.
final.close_safe = close_snapshot_safe

# Fix the older wrapper which was replacing ISO timestamps with Unix seconds.
_original_legacy_close = legacy.close
async def close_timestamp_normalized(p, reason):
    result = await _original_legacy_close(p, reason)
    try:
        for item in legacy.S.get('closed', []):
            if item.get('id') == p.get('id'):
                item['closed_at'] = datetime.now(timezone.utc).isoformat()
                item['close_time'] = item['closed_at']
                break
    except Exception:
        pass
    return result
legacy.close = close_timestamp_normalized
