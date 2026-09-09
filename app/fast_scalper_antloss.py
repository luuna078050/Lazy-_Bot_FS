from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR
import asyncio
import time

# A timeout is a safety exit, not the normal entry/exit mechanism.
# Prevent immediate re-entry on the same symbol after an exit.
COOLDOWN_PROFIT=5.0
COOLDOWN_TIMEOUT=20.0
COOLDOWN_ERROR=10.0
MIN_SIGNAL_AGE=45.0
MIN_3M_MOMENTUM=0.08
_cooldowns={}
_last_radar_refresh=0.0

async def radar_fixed(force=False):
    global _last_radar_refresh
    now=time.time()
    if not force and _last_radar_refresh and now-_last_radar_refresh<10:
        return
    try:
        rows=RADAR.snapshot(15)
        out=[]
        for x in rows:
            s=str(x.get('symbol','')).replace('/','').upper()
            if not s:
                continue
            out.append({
                'symbol':s,
                'price':float(x.get('price') or 0),
                'change':float(x.get('change_24h_pct') or 0),
                'change_24h_pct':float(x.get('change_24h_pct') or 0),
                'change_3m_pct':float(x.get('change_3m_pct') or 0),
                'history_age':float(x.get('history_age') or 0),
                'volume':float(x.get('quote_volume_24h') or 0),
                'quote_volume_24h':float(x.get('quote_volume_24h') or 0),
                'score':float(x.get('score') or 0),
                'signal':x.get('signal','WAIT'),
                'tf':'3m',
                'estimated_entry':float(x.get('estimated_entry') or x.get('price') or 0),
                'estimated_exit':float(x.get('estimated_exit') or x.get('price') or 0),
                'estimated_stop':float(x.get('estimated_stop') or 0),
                'volume_ratio':float(x.get('volume_ratio') or 1.0),
                'pump_events':int(x.get('pump_events') or 0),
                'pump_score':float(x.get('pump_score') or 0),
                'hold_seconds':int(x.get('hold_seconds') or 60),
            })
        out.sort(key=lambda x:(x['signal']=='BUY',x['change_3m_pct'],x['score'],x['quote_volume_24h']),reverse=True)
        legacy.S['ranking']=out[:15]
        legacy.S['last_radar']=now
        legacy.S['error']=None if not RADAR.last_error else 'Radar WebSocket: '+str(RADAR.last_error)
        _last_radar_refresh=now
    except Exception as e:
        legacy.S['error']=f'Radar: {type(e).__name__}: {e}'
        legacy.S['last_radar']=now
        _last_radar_refresh=now

legacy.radar=radar_fixed

async def _close_at_snapshot(p, reason, snapshot):
    if legacy.S.get('mode') != 'PAPER':
        return await legacy.close(p, reason)
    original_price = legacy.price
    def fixed_price(symbol):
        if symbol == p['symbol']:
            return snapshot
        return original_price(symbol)
    legacy.price = fixed_price
    try:
        return await legacy.close(p, reason)
    finally:
        legacy.price = original_price

async def manage():
    now=time.time()
    for p in list(legacy.S['positions']):
        try:
            snapshot = legacy.price(p['symbol']) or p['current']
            p['current'] = snapshot
            live = (snapshot / p['entry'] - 1) * 100
            age = now - p['opened']

            if legacy.S['profit'] > 0 and live >= legacy.S['profit']:
                print(f"[TRADE] CLOSE {p['symbol']} reason=PROFIT_TARGET age={age:.1f}s live={live:.4f}% price={snapshot}", flush=True)
                await _close_at_snapshot(p, 'PROFIT_TARGET', snapshot)
                _cooldowns[p['symbol']]=time.time()+COOLDOWN_PROFIT
                continue

            if age >= legacy.MAX_AGE:
                print(f"[TRADE] CLOSE {p['symbol']} reason=TIMEOUT age={age:.1f}s live={live:.4f}% price={snapshot}", flush=True)
                await _close_at_snapshot(p, 'TIMEOUT', snapshot)
                _cooldowns[p['symbol']]=time.time()+COOLDOWN_TIMEOUT
                continue
        except Exception as e:
            legacy.S['error'] = f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'
            _cooldowns[p.get('symbol','')]=time.time()+COOLDOWN_ERROR

_original_open_pos = legacy.open_pos
async def open_pos_filtered(i, s):
    if not s:return
    s=str(s).upper().replace('/','')
    now=time.time()
    until=_cooldowns.get(s,0.0)
    if until>now:return

    # Never open a scalping position merely because a symbol is liquid.
    # Require a fresh short-term BUY signal from the 3m radar.
    row=next((x for x in legacy.S.get('ranking',[]) if str(x.get('symbol','')).replace('/','').upper()==s),None)
    if not row or row.get('signal')!='BUY':
        return
    try:
        m3=float(row.get('change_3m_pct') or 0.0)
        hist_age=float(row.get('history_age') or 0.0)
    except (TypeError,ValueError):
        return
    if hist_age<MIN_SIGNAL_AGE or m3<MIN_3M_MOMENTUM:
        return
    before_ids={p.get('id') for p in legacy.S.get('positions',[])}
    await _original_open_pos(i,s)
    for p in legacy.S.get('positions',[]):
        if p.get('id') not in before_ids and p.get('slot')==i and p.get('symbol')==s:
            p.setdefault('timeout_armed',False)
            p['signal_3m']=m3
            print(f"[TRADE] OPEN {p.get('symbol')} slot={p.get('slot')} stake={p.get('stake')} entry={p.get('entry')} opened_at={p.get('opened_at')} mode={legacy.S.get('mode')} signal3m={m3:.4f}%",flush=True)
            break
legacy.open_pos=open_pos_filtered

async def _radar_loop():
    while True:
        try:
            if legacy.S.get('running'):
                await asyncio.wait_for(legacy.radar(True),timeout=10)
            else:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            legacy.S['error']=f'Radar: {type(e).__name__}: {e}'
        await asyncio.sleep(5)

async def engine_fixed():
    asyncio.create_task(_radar_loop())
    while True:
        try:
            if legacy.S.get('running'):
                await manage()
                for i,s in enumerate(list(legacy.S.get('slots',[]))):
                    if s and not any(p['slot']==i for p in legacy.S.get('positions',[])):
                        await legacy.open_pos(i,s)
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            legacy.S['error']=f'Engine: {type(e).__name__}: {e}'
            await asyncio.sleep(1)

legacy.manage=manage
legacy.engine=engine_fixed
