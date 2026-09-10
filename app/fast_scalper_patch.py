from . import fast_scalper_beta_001_legacy as legacy
from . import fast_scalper_antloss as anti
from fastapi import HTTPException
import asyncio
import time
import httpx

legacy.MAX_AGE=60
STOP_GRACE=60.0

async def manage_safe():
    now=time.time(); stop_at=legacy.S.get('stop_requested')
    for p in list(legacy.S.get('positions', [])):
        try:
            snapshot=legacy.price(p['symbol']) or p['current']; p['current']=snapshot
            live=(snapshot/p['entry']-1)*100; age=now-p['opened']
            if legacy.S['profit']>0 and live>=legacy.S['profit']:
                print(f'[TRADE] CLOSE {p["symbol"]} reason=PROFIT_TARGET age={age:.1f}s live={live:.4f}% price={snapshot}',flush=True)
                await anti._close_at_snapshot(p,'PROFIT_TARGET',snapshot); anti._cooldowns[p['symbol']]=time.time()+anti.COOLDOWN_PROFIT; continue
            if stop_at:
                if now-stop_at>=STOP_GRACE:
                    print(f'[TRADE] CLOSE {p["symbol"]} reason=BOT_OFF age={age:.1f}s live={live:.4f}% price={snapshot}',flush=True)
                    await anti._close_at_snapshot(p,'BOT_OFF',snapshot)
                continue
            if age>=legacy.MAX_AGE:
                if live>=0:
                    print(f'[TRADE] CLOSE {p["symbol"]} reason=TIMEOUT age={age:.1f}s live={live:.4f}% price={snapshot}',flush=True)
                    await anti._close_at_snapshot(p,'TIMEOUT',snapshot); anti._cooldowns[p['symbol']]=time.time()+anti.COOLDOWN_TIMEOUT
                else:
                    p['opened']=now; p['timeout_armed']=True
                    print(f'[TRADE] HOLD {p["symbol"]} reason=TIMEOUT_DEFERRED age={age:.1f}s live={live:.4f}% price={snapshot}',flush=True)
        except Exception as e:
            legacy.S['error']=f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'; anti._cooldowns[p.get('symbol','')]=time.time()+anti.COOLDOWN_ERROR
    if stop_at and not legacy.S.get('positions'): legacy.S['stop_requested']=None

anti.manage=manage_safe; legacy.manage=manage_safe
_original_close=legacy.close
async def close_with_timestamp(p,reason):
    result=await _original_close(p,reason)
    try:
        for item in legacy.S.get('closed',[]):
            if item.get('id')==p.get('id'): item['closed_at']=time.time(); break
    except Exception: pass
    return result
legacy.close=close_with_timestamp

def remove_post(path):
    for r in list(legacy.app.router.routes):
        if getattr(r,'path',None)==path and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)

remove_post('/api/paper/stop')
@legacy.app.post('/api/paper/stop')
async def stop_fixed():
    legacy.S['running']=False; legacy.S['stop_requested']=time.time() if legacy.S.get('positions') else None
    print(f'[BOT] OFF requested positions={len(legacy.S.get("positions",[]))}',flush=True)
    return await legacy.state()

_original_start=legacy.start
async def start_clean(b):
    if legacy.S.get('positions'): raise HTTPException(400,'Close current positions before a new session')
    legacy.S['stop_requested']=None; result=await _original_start(b); legacy.S['closed']=[]; legacy.S['orders']=[]; return await legacy.state()
remove_post('/api/paper/start')
@legacy.app.post('/api/paper/start')
async def start_endpoint(b:legacy.Start): return await start_clean(b)

async def reset_fixed():
    if legacy.S.get('running') or legacy.S.get('positions'): raise HTTPException(400,'BOT OFF and no open positions required')
    s=legacy.S; s['stop_requested']=None; s['running']=False; s['bot']=0.0; s['free']=0.0; s['realized']=0.0; s['session_realized']=0.0; s['session_trades']=0; s['session_started']=None; s['session_elapsed']=0.0; s['day_started']=None; s['day_elapsed']=0.0; s['positions']=[]; s['closed']=[]; s['orders']=[]; s['slots']=[None]*legacy.MAX_SLOTS; s['profit']=0.41; s['reinvest']=False; s['cycle']=0; s['last_radar']=0.0; s['error']=None
    if s.get('mode')=='PAPER': s['account']=legacy.START; s['reserve']=legacy.START
    else: s['reserve']=max(0.0,float(s.get('account',0.0) or 0.0))
    return await legacy.state()
remove_post('/api/reset')
@legacy.app.post('/api/reset')
async def reset_endpoint(): return await reset_fixed()

remove_post('/api/slots/auto-top6')
@legacy.app.post('/api/slots/auto-top6')
async def auto_top6_fixed(b:legacy.Slots):
    await legacy.radar(True); ranked=[]; seen=set()
    for x in legacy.S.get('ranking',[]):
        s=str(x.get('symbol','')).upper().replace('/','')
        if s and s not in seen: ranked.append(s); seen.add(s)
    target=ranked[:legacy.MAX_SLOTS]; old=list(legacy.S.get('slots',[]))
    for i in range(legacy.MAX_SLOTS):
        old_s=str(old[i] or '').upper().replace('/',''); new_s=str(target[i] if i<len(target) else '').upper().replace('/','')
        if old_s!=new_s:
            for p in legacy.S.get('positions',[]):
                if p.get('slot')==i:
                    live=(float(p.get('current',0))/float(p.get('entry',1))-1)*100
                    print(f'[ROTATION] KEEP {p.get("symbol")} old_slot={i} new_slot={new_s} live={live:.4f}%',flush=True); p['slot']=None
    legacy.S['slots']=target+[None]*(legacy.MAX_SLOTS-len(target)); legacy.S['profit']=b.profit_pct; legacy.S['reinvest']=b.reinvest
    return await legacy.state()

_NOTIONAL_CACHE={}
_NOTIONAL_TTL=300.0
async def symbol_min_notional(symbol):
    symbol=str(symbol).upper().replace('/','')
    cached=_NOTIONAL_CACHE.get(symbol)
    if cached and time.time()-cached[0] < _NOTIONAL_TTL:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r=await c.get(legacy.B.base+'/v3/exchangeInfo',params={'symbol':symbol})
            r.raise_for_status(); data=r.json()
        rows=data.get('symbols') or []
        if not rows: raise RuntimeError(f'Binance exchangeInfo has no symbol {symbol}')
        minimum=0.0
        for f in rows[0].get('filters',[]):
            ft=f.get('filterType')
            if ft=='NOTIONAL' and f.get('applyMinToMarket',True): minimum=max(minimum,float(f.get('minNotional') or 0))
            elif ft=='MIN_NOTIONAL' and f.get('applyToMarket',True): minimum=max(minimum,float(f.get('minNotional') or 0))
        _NOTIONAL_CACHE[symbol]=(time.time(),minimum)
        return minimum
    except Exception as e:
        print(f'[TRADE] FILTER_LOOKUP {symbol} failed: {type(e).__name__}: {e}',flush=True)
        return 0.0

_original_open_pos=legacy.open_pos
async def open_pos_safe(i,s):
    if not s:return
    symbol=str(s).upper().replace('/','')
    if any(str(p.get('symbol','')).upper().replace('/','')==symbol for p in legacy.S.get('positions',[])):
        print(f'[TRADE] SKIP {symbol} reason=DUPLICATE_SYMBOL',flush=True); return
    if legacy.S.get('mode')!='BINANCE_TEST':
        await _original_open_pos(i,s); return
    free=float(legacy.S.get('free',0.0) or 0.0); bot=float(legacy.S.get('bot',0.0) or 0.0); slots=sum(1 for x in legacy.S.get('slots',[]) if x)
    if free<=0 or bot<=0 or slots<=0:return
    allocated=min(free,bot/slots); minimum=await symbol_min_notional(symbol); stake=allocated
    if minimum>0 and stake<minimum:
        if free+1e-9<minimum:
            print(f'[TRADE] SKIP {symbol} reason=NOTIONAL min={minimum:.4f} free={free:.4f} alloc={allocated:.4f}',flush=True)
            legacy.S['error']=f'Binance BUY {symbol}: skipped, min notional {minimum:.4f} > free {free:.4f}'; return
        stake=min(free,minimum*1.02); print(f'[TRADE] SIZE_UP {symbol} min={minimum:.4f} alloc={allocated:.4f} stake={stake:.4f}',flush=True)
    async def place(q): return await legacy.B.market_buy(symbol,q)
    try:
        r=await place(stake); status=r.get('status','')
        if status!='FILLED': raise RuntimeError(f'Binance BUY not filled: {status or r}')
    except Exception as e:
        text=str(e)
        if '-1013' in text and 'NOTIONAL' in text:
            retry_min=max(minimum,stake)*1.08
            if retry_min<=free+1e-9 and retry_min>stake:
                try:
                    print(f'[TRADE] RETRY_NOTIONAL {symbol} stake={retry_min:.4f}',flush=True)
                    r=await place(retry_min); status=r.get('status','')
                    if status!='FILLED': raise RuntimeError(f'Binance BUY not filled: {status or r}')
                    stake=retry_min
                except Exception as e2:
                    legacy.S['error']=f'Binance BUY {symbol}: {type(e2).__name__}: {e2}'; print(f'[TRADE] BUY_ERROR {symbol} slot={i} {type(e2).__name__}: {e2}',flush=True); return
            else:
                legacy.S['error']=f'Binance BUY {symbol}: {text}'; print(f'[TRADE] BUY_ERROR {symbol} slot={i} {text}',flush=True); return
        else:
            legacy.S['error']=f'Binance BUY {symbol}: {type(e).__name__}: {e}'; print(f'[TRADE] BUY_ERROR {symbol} slot={i} {type(e).__name__}: {e}',flush=True); return
    qty=float(r.get('executedQty') or 0); spent=float(r.get('cummulativeQuoteQty') or 0)
    if qty<=0 or spent<=0:
        legacy.S['error']=f'Binance BUY {symbol}: empty fill {r}'; print(f'[TRADE] BUY_ERROR {symbol} slot={i} empty fill',flush=True); return
    ep=spent/qty; legacy.S['free']=max(0.0,float(legacy.S.get('free',0.0))-spent)
    p={'id':f"B{r.get('orderId',int(time.time()*1000))}",'slot':i,'symbol':symbol,'tf':legacy.TF,'entry':ep,'current':ep,'stake':spent,'qty':qty,'opened':time.time(),'opened_at':legacy.now(),'order_id':r.get('orderId')}
    legacy.S['positions'].append(p); legacy.S['orders'].insert(0,{'time':legacy.now(),'symbol':symbol,'side':'BUY','status':status,'price':ep,'qty':qty,'stake':spent,'order_id':r.get('orderId'),'slot':i}); legacy.S['error']=None
    print(f'[TRADE] BUY FILLED {symbol} slot={i+1} stake={spent:.4f} price={ep:.8f} qty={qty:.8f}',flush=True)
legacy.open_pos=open_pos_safe

async def engine_fixed():
    asyncio.create_task(anti._radar_loop())
    while True:
        try:
            if legacy.S.get('running') or legacy.S.get('stop_requested'): await manage_safe()
            if legacy.S.get('running'):
                occupied={str(p.get('symbol','')).upper().replace('/','') for p in legacy.S.get('positions',[])}
                for i,s in enumerate(list(legacy.S.get('slots',[]))):
                    if s and not any(p.get('slot')==i for p in legacy.S.get('positions',[])):
                        n=str(s).upper().replace('/','')
                        if n in occupied: continue
                        await legacy.open_pos(i,s); occupied={str(p.get('symbol','')).upper().replace('/','') for p in legacy.S.get('positions',[])}
            await asyncio.sleep(1)
        except asyncio.CancelledError: raise
        except Exception as e: legacy.S['error']=f'Engine: {type(e).__name__}: {e}'; print(f'[ENGINE] {type(e).__name__}: {e}',flush=True); await asyncio.sleep(1)
anti.manage=manage_safe; legacy.manage=manage_safe; legacy.engine=engine_fixed

# The final UI patch is imported after this module. Add the Radar ADD PAIR
# click handler at startup so it survives the later HTML/render replacement.
async def _install_radar_add_pair_handler():
    try:
        html=legacy.HTML
        if 'data-radar-add-handler' in html:
            return
        handler='''<script data-radar-add-handler>document.addEventListener("click",function(e){const b=e.target.closest(".add-radar");if(!b)return;const s=b.dataset.symbol;if(typeof addRadarPair==="function")addRadarPair(s);});</script>'''
        if '</body>' in html:
            legacy.HTML=html.replace('</body>',handler+'</body>',1)
        else:
            legacy.HTML=html+handler
    except Exception as e:
        print(f'[UI] ADD_PAIR_HANDLER_ERROR {type(e).__name__}: {e}',flush=True)

legacy.app.router.on_startup.append(_install_radar_add_pair_handler)

legacy.HTML=legacy.HTML

# Load the production repair layer now, then apply the final lifecycle/UI patch.
from . import fast_scalper_live_repair
from . import fast_scalper_final_patch
