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
HARD_TIMEOUT = 300.0

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
            usable=bool(ind['ready'] and ind['ready_1m'] and cfs>=7 and ind['ema9']>ind['ema21']
                        and ind['ema9_1m']>=ind['ema21_1m'] and 52.0<=ind['rsi']<=72.0
                        and one>0 and two>0 and three>0 and vr>=1.0 and risk<=2.0)
            score=float(t.get('score',0) or 0)+cfs*5.0+max(0.0,vr-1.0)*8.0+max(0.0,buy-.5)*20.0
            row=dict(t)
            row.update({'entry_allowed':usable,'entry_score':round(score,2),'entry_confirmations':cfs,
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

async def manage_core():
    now=time.time()
    for p in list(legacy.S.get('positions',[])):
        try:
            cur=legacy.price(p['symbol']) or p.get('current') or p.get('entry');p['current']=cur
            entry=float(p.get('entry') or 0);stake=float(p.get('stake') or 0)
            live=((float(cur)/entry)-1.0)*100.0 if entry else 0.0
            p['delta_usdt']=live/100.0*stake
            p['age_seconds']=max(0,int(now-float(p.get('opened') or now)));p['age']=p['age_seconds']
            target=float(legacy.S.get('profit',DEFAULT_PROFIT) or DEFAULT_PROFIT)
            if target>0 and live>=target:
                await legacy.close(p,'PROFIT_TARGET');continue
            if p['age_seconds']>=SOFT_TIMEOUT and live>=0.30:
                await legacy.close(p,'TIMEOUT');continue
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
    row=next((x for x in legacy.S.get('ranking',[]) if str(x.get('symbol','')).upper().replace('/','')==s),None)
    # PAPER mode: a filled TOP-10 slot is an executable order. Do not wait for the
    # scored ranking/indicator gate; the slot itself is the user's selection.
    # This lets all 10 selected slots become positions as soon as live ticker prices
    # are available. BINANCE_TEST keeps the confirmed-entry gate.
    if legacy.S.get('mode') != 'PAPER':
        if not row or not bool(row.get('entry_allowed')): return
    if float(legacy.S.setdefault('pair_cooldown',{}).get(s,0) or 0)>time.time(): return
    await _original_open(i,s)
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
                selected=list(legacy.S.get('slots',[]))[:TRADE_SLOTS]
                await refresh_paper_prices(selected)
                occupied={int(p.get('slot')) for p in legacy.S.get('positions',[]) if str(p.get('slot','')).lstrip('-').isdigit()}
                for i,s in enumerate(selected):
                    if i in occupied or not s: continue
                    await open_core(i,s)
                    if len(legacy.S.get('positions',[]))>=TRADE_SLOTS: break
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
    raise HTTPException(403,'Use BINANCE TEST start only through the configured test mode')

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
    try:
        await legacy.close(target,'MANUAL_CLOSE')
    except Exception as e:
        legacy.S['error']=f'Close {target.get("symbol")}: {type(e).__name__}: {e}'
        raise HTTPException(502,legacy.S['error'])
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
print('FAST_SCALPER_CORE ROTATION_POOL=20 TRADE_SLOTS=10 TP_DEFAULT=0.33 SOFT=90 HARD=300 ENTRY=3M_EMA+1M_EMA+RSI+VOLUME COOLDOWN=180',flush=True)