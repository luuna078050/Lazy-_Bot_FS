from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR
import asyncio
import time

COOLDOWN_PROFIT=5.0
COOLDOWN_TIMEOUT=20.0
COOLDOWN_ERROR=10.0
COOLDOWN_MAX_HOLD=20.0
MAX_HOLD=300.0
_cooldowns={}
_last_radar_refresh=0.0
_radar_lock=asyncio.Lock()

async def radar_fixed(force=False):
    global _last_radar_refresh
    now=time.time()
    if not force and _last_radar_refresh and now-_last_radar_refresh<10:
        return
    async with _radar_lock:
        now=time.time()
        if not force and _last_radar_refresh and now-_last_radar_refresh<10:
            return
        try:
            rows=await asyncio.to_thread(RADAR.snapshot,15)
            out=[]
            for x in rows:
                s=str(x.get('symbol','')).replace('/','').upper()
                if not s:
                    continue
                out.append({'symbol':s,'price':float(x.get('price') or 0),'change':float(x.get('change_24h_pct') or 0),'change_24h_pct':float(x.get('change_24h_pct') or 0),'change_3m_pct':float(x.get('change_3m_pct') or 0),'history_age':float(x.get('history_age') or 0),'volume':float(x.get('quote_volume_24h') or 0),'quote_volume_24h':float(x.get('quote_volume_24h') or 0),'score':float(x.get('score') or 0),'signal':x.get('signal','WAIT'),'tf':'3m','estimated_entry':float(x.get('estimated_entry') or x.get('price') or 0),'estimated_exit':float(x.get('estimated_exit') or x.get('price') or 0),'estimated_stop':float(x.get('estimated_stop') or 0),'volume_ratio':float(x.get('volume_ratio') or 1.0),'pump_events':int(x.get('pump_events') or 0),'pump_score':float(x.get('pump_score') or 0),'hold_seconds':int(x.get('hold_seconds') or 60)})
            out.sort(key=lambda x:(x['signal']=='BUY',x['change_3m_pct'],x['score'],x['quote_volume_24h']),reverse=True)
            legacy.S['ranking']=out[:15]
            legacy.S['last_radar']=now
            legacy.S['error']=None if not RADAR.last_error else 'Radar WebSocket: '+str(RADAR.last_error)
            if out:
                top=','.join(f"{x['symbol']}:{x['signal']}:{x['change_3m_pct']:.3f}%/{x['history_age']:.0f}s" for x in out[:6])
                print(f"[RADAR] TOP6 {top}",flush=True)
            _last_radar_refresh=now
        except Exception as e:
            legacy.S['error']=f'Radar: {type(e).__name__}: {e}'
            legacy.S['last_radar']=now
            _last_radar_refresh=now

legacy.radar=radar_fixed

async def _close_at_snapshot(p, reason, snapshot):
    if legacy.S.get('mode') != 'PAPER':
        return await legacy.close(p, reason)
    original_price=legacy.price
    def fixed_price(symbol):
        if symbol==p['symbol']:
            return snapshot
        return original_price(symbol)
    legacy.price=fixed_price
    try:
        return await legacy.close(p, reason)
    finally:
        legacy.price=original_price

async def manage():
    now=time.time()
    stop_at=legacy.S.get('stop_requested')
    for p in list(legacy.S.get('positions',[])):
        try:
            snapshot=legacy.price(p['symbol']) or p['current']
            p['current']=snapshot
            entry=float(p.get('entry') or 0)
            live=((snapshot/entry)-1)*100 if entry else 0.0
            age=now-float(p.get('opened') or now)
            p['age_seconds']=int(max(0,age)); p['age']=p['age_seconds']
            if legacy.S.get('profit',0)>0 and live>=float(legacy.S['profit']):
                print(f"[TRADE] CLOSE {p['symbol']} reason=PROFIT_TARGET age={age:.1f}s live={live:.4f}% price={snapshot}",flush=True)
                await _close_at_snapshot(p,'PROFIT_TARGET',snapshot)
                _cooldowns[p['symbol']]=time.time()+COOLDOWN_PROFIT
                continue
            if stop_at:
                print(f"[TRADE] CLOSE {p['symbol']} reason=BOT_OFF age={age:.1f}s live={live:.4f}% price={snapshot}",flush=True)
                await _close_at_snapshot(p,'BOT_OFF',snapshot)
                continue
            if age>=float(getattr(legacy,'MAX_AGE',60) or 60):
                if live>=0:
                    print(f"[TRADE] CLOSE {p['symbol']} reason=TIMEOUT age={age:.1f}s live={live:.4f}% price={snapshot}",flush=True)
                    await _close_at_snapshot(p,'TIMEOUT',snapshot)
                    _cooldowns[p['symbol']]=time.time()+COOLDOWN_TIMEOUT
                elif age>=MAX_HOLD:
                    print(f"[TRADE] CLOSE {p['symbol']} reason=MAX_HOLD age={age:.1f}s live={live:.4f}% price={snapshot}",flush=True)
                    await _close_at_snapshot(p,'MAX_HOLD',snapshot)
                    _cooldowns[p['symbol']]=time.time()+COOLDOWN_MAX_HOLD
                else:
                    p['timeout_armed']=True
            elif age>=MAX_HOLD:
                print(f"[TRADE] CLOSE {p['symbol']} reason=MAX_HOLD age={age:.1f}s live={live:.4f}% price={snapshot}",flush=True)
                await _close_at_snapshot(p,'MAX_HOLD',snapshot)
                _cooldowns[p['symbol']]=time.time()+COOLDOWN_MAX_HOLD
        except Exception as e:
            legacy.S['error']=f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'
            _cooldowns[p.get('symbol','')]=time.time()+COOLDOWN_ERROR
            print(f'[ENGINE] MANAGE_ERROR {p.get("symbol")} {type(e).__name__}: {e}',flush=True)
    if stop_at and not legacy.S.get('positions'):
        legacy.S['stop_requested']=None

_original_open_pos=legacy.open_pos
async def open_pos_filtered(i,s):
    if not s:
        return
    s=str(s).upper().replace('/','')
    now=time.time()
    if _cooldowns.get(s,0.0)>now:
        print(f'[TRADE] SKIP {s} reason=COOLDOWN',flush=True)
        return
    if any(str(p.get('symbol','')).upper().replace('/','')==s for p in legacy.S.get('positions',[])):
        print(f'[TRADE] SKIP {s} reason=DUPLICATE_POSITION',flush=True)
        return
    # IMPORTANT: slot assignment is the execution authority in PAPER mode.
    # Do not require a fresh Radar BUY flag here; the old gate could leave every
    # slot empty when Radar was WAIT while the UI showed BOT ON.
    before_ids={p.get('id') for p in legacy.S.get('positions',[])}
    await _original_open_pos(i,s)
    for p in legacy.S.get('positions',[]):
        if p.get('id') not in before_ids and p.get('slot')==i and str(p.get('symbol','')).upper().replace('/','')==s:
            p.setdefault('timeout_armed',False)
            print(f"[TRADE] OPEN {p.get('symbol')} slot={p.get('slot')} stake={p.get('stake')} entry={p.get('entry')} opened_at={p.get('opened_at')} mode={legacy.S.get('mode')}",flush=True)
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
                occupied_symbols={str(p.get('symbol','')).upper().replace('/','') for p in legacy.S.get('positions',[])}
                for i,s in enumerate(list(legacy.S.get('slots',[]))):
                    if s and not any(p['slot']==i for p in legacy.S.get('positions',[])):
                        normalized=str(s).upper().replace('/','')
                        if normalized in occupied_symbols:
                            continue
                        await legacy.open_pos(i,s)
                        occupied_symbols={str(p.get('symbol','')).upper().replace('/','') for p in legacy.S.get('positions',[])}
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            legacy.S['error']=f'Engine: {type(e).__name__}: {e}'
            await asyncio.sleep(1)

legacy.manage=manage
legacy.engine=engine_fixed

async def _final_lifecycle_guard():
    legacy.manage=manage
    legacy.open_pos=open_pos_filtered
    try:
        html=legacy.HTML
        if 'data-closed-short-labels' not in html:
            marker='''<script data-closed-short-labels>(function(){const m={PROFIT_TARGET:'PT',TIMEOUT:'TO',MAX_HOLD:'MH',BOT_OFF:'OFF',ROTATION:'ROT',EMERGENCY_POSITION:'EMG',EMERGENCY_STOP:'ESTOP'};const f=window.__fsShortReason||function(r){return m[r]||r};window.__fsShortReason=f;})();</script>'''
            html=html.replace('</body>',marker+'</body>',1) if '</body>' in html else html+marker
            html=html.replace('${x.symbol} · ${x.reason}','${x.symbol} · ${window.__fsShortReason?window.__fsShortReason(x.reason):x.reason}')
            legacy.HTML=html
    except Exception as e:
        print(f'[UI] CLOSED_SHORT_LABELS_ERROR {type(e).__name__}: {e}',flush=True)

legacy.app.router.on_startup.append(_final_lifecycle_guard)