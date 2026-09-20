from __future__ import annotations
import asyncio, re, time
import httpx
from fastapi import HTTPException
from pydantic import BaseModel
from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR

ROTATION_POOL = 20
TRADE_SLOTS = 10
MAX_ENTRY_CANDIDATES = 10
DEFAULT_PROFIT = 0.33
DEFAULT_PAPER_BOT = 0.0
SOFT_TIMEOUT = 90.0
ROTATION_SECONDS = 60.0
HARD_TIMEOUT = 60.0

# Scalp economics: the target must cover the modeled round-trip costs and
# leave at least 0.02 USDT net on a small (~15 USDT) position.
MIN_NET_PROFIT_USDT = 0.02
MODEL_ROUNDTRIP_COST_PCT = 0.30
MIN_SCALP_MOVE_PCT = 0.45

legacy.S['auto_top'] = True
legacy.S.setdefault('pair_cooldown',{})

def _series_indicators(bars):
    closes=[float(x.get('close') or 0) for x in bars if float(x.get('close') or 0)>0]
    if len(closes)<21:
        return {'ready':False,'ema9':0.0,'ema21':0.0,'rsi':50.0}
    vals=closes[-80:]
    def ema(period):
        k=2.0/(period+1.0); e=vals[0]
        for v in vals[1:]: e=float(v)*k+e*(1.0-k)
        return e
    diffs=[bb-aa for aa,bb in zip(closes[-15:],closes[-14:])]
    gains=[max(0.0,d) for d in diffs]; losses=[max(0.0,-d) for d in diffs]
    ag=sum(gains)/14.0; al=sum(losses)/14.0
    rsi=100.0 if al<=1e-12 and ag>0 else (50.0 if al<=1e-12 else 100.0-100.0/(1.0+ag/al))
    return {'ready':True,'ema9':ema(9),'ema21':ema(21),'rsi':rsi}

def _required_target_pct(stake):
    stake=max(0.01,float(stake or 0.0))
    return max(float(DEFAULT_PROFIT), MODEL_ROUNDTRIP_COST_PCT + (MIN_NET_PROFIT_USDT/stake)*100.0)

def _scalp_move_pct(symbol, t):
    # Use observed recent movement, not a directional prediction.
    vals=[]
    for k in ('change_1m_pct','change_2m_pct','change_3m_pct','change_4m_pct'):
        try: vals.append(abs(float(t.get(k,0) or 0)))
        except (TypeError,ValueError): pass
    with RADAR.lock:
        bars=list(RADAR.bars.get(str(symbol).upper().replace('/',''),()))
    ranges=[]
    for b in bars[-5:]:
        try:
            hi=float(b.get('high') or 0); lo=float(b.get('low') or 0)
            if hi>0 and lo>0: ranges.append((hi-lo)/lo*100.0)
        except (TypeError,ValueError): pass
    return max(vals+[0.0]+ranges)

def _indicators(symbol):
    s=str(symbol).upper().replace('/','')
    with RADAR.lock:
        bars1=list(RADAR.bars.get(s,()))
        bars3=list(getattr(RADAR,'bars_3m',{}).get(s,()))
    i1=_series_indicators(bars1)
    i3=_series_indicators(bars3)
    if not i3['ready']:
        return {'ready':False,'ready_1m':i1['ready'],'tf':'3m','ema9':0.0,'ema21':0.0,'rsi':50.0,
                'ema9_1m':i1['ema9'],'ema21_1m':i1['ema21'],'rsi_1m':i1['rsi'],'volume_ratio_3m':0.0}
    vols=[max(0.0,float(x.get('quote_volume') or 0)) for x in bars3[-21:]]
    base=sum(vols[:-1])/max(1,len(vols[:-1])) if len(vols)>=4 else 0.0
    vr=vols[-1]/base if base>0 and vols else 0.0
    return {'ready':True,'ready_1m':i1['ready'],'tf':'3m','ema9':i3['ema9'],'ema21':i3['ema21'],
            'rsi':i3['rsi'],'ema9_1m':i1['ema9'],'ema21_1m':i1['ema21'],'rsi_1m':i1['rsi'],
            'volume_ratio_3m':vr}

async def radar_core(force=False):
    if not force and legacy.S.get('last_radar') and time.time()-legacy.S['last_radar']<5: return
    try:
        rows=RADAR.snapshot(ROTATION_POOL); ranked=[]
        cooldowns=legacy.S.setdefault('pair_cooldown',{})
        now=time.time()
        for s0,t in [(x.get('symbol',''),x) for x in rows]:
            s=str(s0).upper().replace('/','')
            if not s: continue
            if float(cooldowns.get(s,0) or 0)>now: continue
            ind=_indicators(s)
            cfs=0
            one=float(t.get('change_1m_pct',0) or 0)
            two=float(t.get('change_2m_pct',0) or 0)
            three=float(t.get('change_3m_pct',0) or 0)
            four=float(t.get('change_4m_pct',0) or 0)
            vr=float(t.get('volume_ratio',0) or 0)
            buy=float(t.get('buy_ratio',0.5) or 0.5)
            risk=float(t.get('risk_pct',0) or 0)
            if ind['ready'] and ind['ema9']>ind['ema21']: cfs+=1
            if ind['ready_1m'] and ind['ema9_1m']>ind['ema21_1m']: cfs+=1
            if ind['ready'] and 52.0<=ind['rsi']<=72.0: cfs+=1
            if one>0.05: cfs+=1
            if two>0.05: cfs+=1
            if three>0.10: cfs+=1
            if four>-0.15: cfs+=1
            if vr>=1.0: cfs+=1
            if buy>=0.52: cfs+=1
            if risk<=2.0: cfs+=1
            scalp_move=_scalp_move_pct(s,t)
            usable=bool(ind['ready'] and ind['ready_1m'] and cfs>=7 and ind['ema9']>ind['ema21']
                        and ind['ema9_1m']>=ind['ema21_1m'] and 52.0<=ind['rsi']<=72.0
                        and one>0 and two>0 and three>0 and vr>=1.0 and risk<=2.0
                        and scalp_move>=MIN_SCALP_MOVE_PCT)
            score=float(t.get('score',0) or 0)+cfs*5.0+max(0.0,vr-1.0)*8.0+max(0.0,buy-.5)*20.0
            row_extra_move=scalp_move
            row=dict(t)
            row.update({'entry_allowed':usable,'entry_score':round(score,2),'entry_confirmations':cfs,
                        'scalp_move_pct':round(row_extra_move,3),'min_scalp_move_pct':MIN_SCALP_MOVE_PCT,
                        'ema9_3m':round(ind['ema9'],10),'ema21_3m':round(ind['ema21'],10),
                        'ema9_1m':round(ind['ema9_1m'],10),'ema21_1m':round(ind['ema21_1m'],10),
                        'rsi14_3m':round(ind['rsi'],2),'indicator_tf':'3m',
                        'candidate_pool':'TOP-20','signal':'BUY' if usable else 'WATCH'})
            ranked.append(row)
        ranked.sort(key=lambda z:(1 if z.get('entry_allowed') else 0,float(z.get('entry_score',0)),float(z.get('score',0))),reverse=True)
        legacy.S['ranking']=ranked[:ROTATION_POOL];legacy.S['last_radar']=time.time()
        legacy.S['error']=None if not getattr(RADAR,'last_error',None) else 'Radar WebSocket: '+RADAR.last_error
        refresh_slots()
    except Exception as e:
        legacy.S['error']=f'Radar: {type(e).__name__}: {e}';legacy.S['last_radar']=time.time()

def refresh_slots():
    if not legacy.S.get('auto_top', True): return
    ranked=[]; seen=set()
    for x in legacy.S.get('ranking',[]):
        s=str(x.get('symbol','')).upper().replace('/','')
        if s and s not in seen and re.fullmatch(r'[A-Z0-9]+USDT',s): ranked.append(s); seen.add(s)
    target=ranked[:ROTATION_POOL]; old=(list(legacy.S.get('slots',[]))+[None]*ROTATION_POOL)[:ROTATION_POOL]
    occupied={int(p.get('slot')) for p in legacy.S.get('positions',[]) if str(p.get('slot','')).lstrip('-').isdigit()}; used={str(x).upper().replace('/','') for x in old if x}; final=list(old)
    for i in range(ROTATION_POOL):
        if i in occupied: continue
        candidate=next((s for s in target if s not in used),None)
        if candidate:
            previous=str(final[i] or '').upper().replace('/','')
            if previous: used.discard(previous)
            final[i]=candidate; used.add(candidate)
        else: final[i]=None
    legacy.S['slots']=final

legacy.radar=radar_core
legacy.MAX_AGE=SOFT_TIMEOUT

async def refresh_binance_test_prices(symbols):
    """Refresh all open BINANCE_TEST prices with one public request per engine tick."""
    if legacy.S.get('mode')!='BINANCE_TEST': return
    wanted={str(x).upper().replace('/','') for x in symbols if x}
    if not wanted: return
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r=await client.get(f"{legacy.B.base}/v3/ticker/price")
            r.raise_for_status()
            data=r.json()
        with RADAR.lock:
            for row in data if isinstance(data,list) else []:
                s=str(row.get('symbol','')).upper()
                if s not in wanted: continue
                try: px=float(row.get('price') or 0)
                except (TypeError,ValueError): continue
                if px>0: RADAR.tickers[s]={'s':s,'c':str(px)}
    except Exception as e:
        legacy.S['error']=f'Binance price feed: {type(e).__name__}: {e}'

def _execution_price(symbol):
    return float(legacy.price(symbol) or 0)

async def manage_core():
    await refresh_binance_test_prices([p.get('symbol') for p in legacy.S.get('positions',[])])

    now=time.time()
    for p in list(legacy.S.get('positions',[])):
        try:
            cur=_execution_price(p['symbol']) or p.get('current') or p.get('entry')
            p['current']=cur
            entry=float(p.get('entry') or 0.0)
            stake=float(p.get('stake') or 0.0)
            live=((float(cur)/entry)-1.0)*100.0 if entry else 0.0
            p['delta_usdt']=live/100.0*stake
            p['age_seconds']=max(0,int(now-float(p.get('opened') or now)))
            p['age']=p['age_seconds']

            # Keep the user-selected target semantics from the v0.4.2
            # baseline, but protect it with the modeled round-trip cost and
            # minimum net-profit requirement. Do NOT add an arbitrary extra
            # 0.25 percentage-point buffer: that made normal 0.33% targets
            # effectively unreachable on small slots.
            configured=float(p.get('target_pct') or legacy.S.get('profit') or DEFAULT_PROFIT)
            target=configured
            modeled_net=stake*(live/100.0-MODEL_ROUNDTRIP_COST_PCT/100.0)

            # Baseline PROFIT_TARGET, protected: it may only close when the
            # expected net remains positive after modeled costs.
            if target>0 and live>=target:
                await legacy.close(p,'PROFIT_TARGET')
                continue

            # Baseline ROTATION: after 60 seconds allow a profitable rotation,
            # but never force a loss merely because the rotation clock expired.
            if (p in legacy.S.get('positions',[]) and
                p['age_seconds']>=ROTATION_SECONDS and
                modeled_net>=MIN_NET_PROFIT_USDT):
                await legacy.close(p,'ROTATION')
                continue

            # Absolute time guard. This is the only automatic path that may
            # realize a negative PnL; it is a hard hold limit, not a target.
            if p in legacy.S.get('positions',[]) and p['age_seconds']>=HARD_TIMEOUT:
                await legacy.close(p,'MAX_HOLD')
        except Exception as e:
            legacy.S['error']=f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'
legacy.manage=manage_core

_original_open=legacy.open_pos
async def refresh_paper_prices(symbols):
    """Refresh selected PAPER slot prices from Binance public market data in one request."""
    symbols=[str(x).upper().replace('/','') for x in symbols if x]
    if not symbols or legacy.S.get('mode')!='PAPER': return
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r=await client.get('https://data-api.binance.vision/api/v3/ticker/price')
            r.raise_for_status()
            data=r.json()
        wanted=set(symbols)
        with RADAR.lock:
            for row in data if isinstance(data,list) else []:
                s=str(row.get('symbol','')).upper()
                if s in wanted:
                    try:
                        p=float(row.get('price') or 0)
                    except (TypeError,ValueError):
                        continue
                    if p>0: RADAR.tickers[s]={'s':s,'c':str(p)}
    except Exception as e:
        legacy.S['error']=f'Paper price feed: {type(e).__name__}: {e}'

async def open_core(i,symbol):
    if legacy.S.get('stop_requested') or not legacy.S.get('running'): return
    if i>=TRADE_SLOTS or not symbol or len(legacy.S.get('positions',[]))>=TRADE_SLOTS: return
    s=str(symbol).upper().replace('/','')
    if any(str(p.get('symbol','')).upper().replace('/','')==s for p in legacy.S.get('positions',[])): return
    # HARD RULE: an occupied execution slot is an order instruction in BOTH
    # PAPER and BINANCE_TEST. Radar ranking/entry confirmation is used to build
    # AUTO TOP-10, but it must never veto an already occupied slot.
    # The user can therefore fill slots from TOP-20 (or manually), press BOT ON,
    # and the occupied slots are sent to the selected execution mode.
    await _original_open(i,s)
    # Store the economic minimum target on the position so it remains stable
    # even if the session input is changed later.
    for p in reversed(legacy.S.get('positions',[])):
        if str(p.get('symbol','')).upper().replace('/','')==s and int(p.get('slot',-1))==i:
            p['target_pct']=_required_target_pct(float(p.get('stake') or 0.0))
            break
legacy.open_pos=open_core

PAPER_MAKER_FEE_RATE=0.001
PAPER_SLIPPAGE_RATE=0.0005

_original_close_core=legacy.close
async def close_net_core(p,reason):
    if legacy.S.get('mode')!='PAPER':
        return await _original_close_core(p,reason)
    entry=float(p.get('entry') or 0.0)
    stake=float(p.get('stake') or 0.0)
    exit_price=float(legacy.price(p.get('symbol')) or p.get('current') or entry)
    if entry<=0 or stake<=0:
        return await _original_close_core(p,reason)
    effective_entry=entry*(1.0+PAPER_SLIPPAGE_RATE)
    effective_exit=exit_price*(1.0-PAPER_SLIPPAGE_RATE)
    qty=stake/effective_entry
    gross_proceeds=qty*effective_exit
    entry_fee=stake*PAPER_MAKER_FEE_RATE
    exit_fee=gross_proceeds*PAPER_MAKER_FEE_RATE
    net_pnl=gross_proceeds-exit_fee-stake-entry_fee
    legacy.S['free']+=stake
    legacy.S['bot']+=net_pnl if legacy.S.get('reinvest') else 0.0
    legacy.S['account']+=net_pnl if not legacy.S.get('reinvest') else 0.0
    legacy.refresh_reserve()
    legacy.S['realized']+=net_pnl
    legacy.S['session_realized']+=net_pnl
    legacy.S['session_trades']+=1
    closed=dict(p,exit=exit_price,pnl=net_pnl,reason=reason,closed_at=legacy.now(),net_pnl=net_pnl,commission=entry_fee+exit_fee)
    legacy.S['closed'].insert(0,closed);legacy.S['closed']=legacy.S['closed'][:100]
    legacy.S['orders'].insert(0,{'time':legacy.now(),'symbol':p['symbol'],'side':'SELL','price':exit_price,'pnl':net_pnl,'reason':reason,'commission':entry_fee+exit_fee})
    sym=str(p.get('symbol','')).upper().replace('/','')
    if sym and (net_pnl<0 or reason in {'TIMEOUT','MAX_HOLD'}):
        legacy.S.setdefault('pair_cooldown',{})[sym]=time.time()+180.0
    print(f"TRADE_CLOSE symbol={sym} reason={reason} pnl={net_pnl:.6f} age={int(p.get('age_seconds',0) or 0)}",flush=True)
    if p in legacy.S.get('positions',[]): legacy.S['positions'].remove(p)
    return closed
legacy.close=close_net_core

async def engine_core():
    while True:
        try:
            if legacy.S.get('positions'): await manage_core()
            if legacy.S.get('running') and not legacy.S.get('stop_requested'):
                # Entry pass comes first. In PAPER, selected slots must fill from
                # live ticker prices without waiting for the slower radar/indicator
                # refresh. With 10 slots this normally completes in one engine tick.
                # HARD RULE: Radar TOP-20 owns the slot queue when AUTO TOP-10 is ON.
                # The first 10 ranked pairs are written into slots 01..10 before execution.
                # When AUTO is OFF, only the manually occupied slots are executable.
                if legacy.S.get('auto_top', True):
                    refresh_slots()
                selected=list(legacy.S.get('slots',[]))[:TRADE_SLOTS]
                selected=[str(s).upper().replace('/','').strip() if s else None for s in selected]
                await refresh_paper_prices(selected)
                occupied={int(p.get('slot')) for p in legacy.S.get('positions',[]) if str(p.get('slot','')).lstrip('-').isdigit()}
                for i,s in enumerate(selected):
                    if i in occupied or not s:
                        continue
                    print(f"OPEN_SLOT_ATTEMPT slot={i+1} symbol={s} mode={legacy.S.get('mode')} free={float(legacy.S.get('free',0) or 0):.6f}",flush=True)
                    before=len(legacy.S.get('positions',[]))
                    await open_core(i,s)
                    after=len(legacy.S.get('positions',[]))
                    if after>before:
                        print(f"OPEN_SLOT_FILLED slot={i+1} symbol={s} positions={after}",flush=True)
                    elif legacy.S.get('error'):
                        print(f"OPEN_SLOT_BLOCKED slot={i+1} symbol={s} error={legacy.S.get('error')}",flush=True)
                    if after>=TRADE_SLOTS:
                        break
                await radar_core(False)
            await asyncio.sleep(1)
        except asyncio.CancelledError: raise
        except Exception as e: legacy.S['error']=f'Engine: {type(e).__name__}: {e}'; await asyncio.sleep(1)
legacy.engine=engine_core

for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/paper/start' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/paper/start')
async def start_core(b: legacy.Start):
    if legacy.S.get('positions'):
        raise HTTPException(400,'Close current positions before a new session')
    if legacy.S.get('mode')=='PAPER':
        if legacy.S.get('bot',0)<=0:
            legacy.S['bot']=legacy.S.get('account',legacy.START)
        legacy.S['free']=max(0.0,float(legacy.S['bot'])-legacy.invested())
        legacy.S['profit']=float(b.profit_pct)
        legacy.S['reinvest']=bool(b.reinvest)
        legacy.S['running']=True
        legacy.S['stop_requested']=False
        legacy.S['session_started']=legacy.now()
        legacy.S['session_elapsed']=0.0
        legacy.S['session_realized']=0.0
        legacy.S['session_trades']=0
        legacy.S['error']=None
        legacy.S['day_started']=legacy.S.get('day_started') or legacy.now()
        legacy.refresh_reserve()
        return await legacy.state()
    if legacy.S.get('mode')=='BINANCE_TEST':
        if not legacy.B.configured:
            raise HTTPException(400,'Binance API credentials are not configured')
        if not legacy.B.testnet:
            raise HTTPException(403,'BINANCE_TEST requires Binance Testnet')
        if float(legacy.S.get('bot',0) or 0)<=0:
            raise HTTPException(400,'Set Bot Allocation before starting BINANCE_TEST')
        try:
            await legacy.B.ping()
            acc=await legacy.B.account()
            free_usdt=next((float(x.get('free') or 0) for x in acc.get('balances',[]) if x.get('asset')=='USDT'),0.0)
            if free_usdt<float(legacy.S['bot']):
                raise RuntimeError(f"Bot allocation {legacy.S['bot']:.8f} exceeds free USDT {free_usdt:.8f}")
            legacy.S['account']=free_usdt+legacy.invested()
            legacy.S['free']=max(0.0,float(legacy.S['bot'])-legacy.invested())
            legacy.S['profit']=float(b.profit_pct)
            legacy.S['reinvest']=bool(b.reinvest)
            legacy.S['running']=True
            legacy.S['stop_requested']=False
            legacy.S['session_started']=legacy.now()
            legacy.S['session_elapsed']=0.0
            legacy.S['session_realized']=0.0
            legacy.S['session_trades']=0
            legacy.S['error']=None
            legacy.S['day_started']=legacy.S.get('day_started') or legacy.now()
            legacy.refresh_reserve()
            return await legacy.state()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400,f'Binance TEST start failed: {type(e).__name__}: {e}')
    raise HTTPException(403,'Unsupported trading mode')

for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/paper/stop' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/paper/stop')
async def stop_core():
    legacy.S['running']=False; legacy.S['stop_requested']=True; return await legacy.state()

@legacy.app.post('/api/position/close')
async def close_position_core(b:dict):
    ident=str(b.get('id') or '').strip()
    symbol=str(b.get('symbol') or '').upper().replace('/','').strip()
    target=None
    for p in legacy.S.get('positions',[]):
        if ident and str(p.get('id'))==ident:
            target=p; break
        if symbol and str(p.get('symbol','')).upper().replace('/','')==symbol:
            target=p; break
    if target is None:
        raise HTTPException(404,'Open position not found')
    slot=target.get('slot')
    sym=str(target.get('symbol','')).upper().replace('/','')
    try:
        await legacy.close(target,'MANUAL_CLOSE')
    except Exception as e:
        legacy.S['error']=f'Close {target.get("symbol")}: {type(e).__name__}: {e}'
        raise HTTPException(502,legacy.S['error'])
    # A manual close frees the execution slot and blocks immediate re-entry
    # of the same pair. AUTO TOP can then refill it with the next eligible pair.
    try:
        si=int(slot)
        if 0 <= si < ROTATION_POOL:
            slots=list(legacy.S.get('slots',[]))
            while len(slots)<ROTATION_POOL: slots.append(None)
            slots[si]=None
            legacy.S['slots']=slots[:ROTATION_POOL]
    except (TypeError,ValueError):
        pass
    if sym:
        legacy.S.setdefault('pair_cooldown',{})[sym]=time.time()+180.0
    return await legacy.state()

for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/reset' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/reset')
async def reset_core():
    if legacy.S.get('running'): raise HTTPException(400,'STOP the bot before RESET')
    for p in list(legacy.S.get('positions',[])): await legacy.close(p,'RESET')
    legacy.S['slots']=[None]*ROTATION_POOL; legacy.S['auto_top']=True; legacy.S['profit']=DEFAULT_PROFIT; legacy.S['reinvest']=True; legacy.S['pair_cooldown']={}; legacy.S['stop_requested']=None
    legacy.S['session_elapsed']=0.0; legacy.S['session_realized']=0.0; legacy.S['session_trades']=0; legacy.S['session_started']=None; legacy.S['day_started']=None; legacy.S['cycle']=0; legacy.S['last_radar']=0.0; legacy.S['error']=None
    if legacy.S.get('mode')=='PAPER': legacy.S['account']=legacy.START; legacy.S['bot']=DEFAULT_PAPER_BOT; legacy.S['free']=DEFAULT_PAPER_BOT; legacy.S['reserve']=max(0.0,legacy.S['account']-legacy.S['bot'])
    return await legacy.state()

class SlotsBody(BaseModel):
    slots:list[str]=[]
    profit_pct:float=DEFAULT_PROFIT
    reinvest:bool=True
    auto_top:bool=False
for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/slots' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/slots')
async def slots_core(b:SlotsBody):
    a=[]
    for x in b.slots:
        s=str(x).upper().replace('/','').strip()
        if s and s not in a: a.append(s)
    if len(a)>ROTATION_POOL: raise HTTPException(400,'Maximum 20 pairs')
    bad=[s for s in a if not re.fullmatch(r'[A-Z0-9]+USDT',s)]
    if bad: raise HTTPException(400,'Invalid Binance pairs: '+','.join(bad))
    old=(list(legacy.S.get('slots',[]))+[None]*ROTATION_POOL)[:ROTATION_POOL]; new=(a+[None]*ROTATION_POOL)[:ROTATION_POOL]
    occupied={int(p.get('slot')) for p in legacy.S.get('positions',[]) if str(p.get('slot','')).lstrip('-').isdigit()}
    for i in occupied:
        if old[i] and new[i]!=old[i]: new[i]=old[i]
    legacy.S['slots']=new; legacy.S['auto_top']=bool(b.auto_top); legacy.S['profit']=float(b.profit_pct); legacy.S['reinvest']=bool(b.reinvest)
    if legacy.S['auto_top']: refresh_slots()
    return await legacy.state()

class AutoTopBody(BaseModel):
    enabled: bool
for r in list(legacy.app.router.routes):
    if getattr(r,'path',None)=='/api/auto-top' and 'POST' in (getattr(r,'methods',set()) or set()): legacy.app.router.routes.remove(r)
@legacy.app.post('/api/auto-top')
async def auto_top_core(b:AutoTopBody):
    legacy.S['auto_top']=bool(b.enabled)
    if legacy.S['auto_top']: refresh_slots()
    return await legacy.state()

legacy.S['profit']=DEFAULT_PROFIT
legacy.S['reinvest']=True
print('FAST_SCALPER_CORE BASELINE=2026-09-06T17:44+02:00 ROTATION_POOL=20 TRADE_SLOTS=10 TP_DEFAULT=0.33 ROTATION=60 MIN_NET=0.02 COST=0.30 MIN_MOVE=0.45 HARD=60 ENTRY=SCALP_FILTER COOLDOWN=180 SPOT_ONLY=1',flush=True)