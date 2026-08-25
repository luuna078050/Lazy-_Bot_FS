from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .market_radar import RADAR

LOCK=threading.RLock(); STOP=threading.Event(); THREAD=None; HALT_ENTRIES=False
COOLDOWN:dict[str,float]={}
TARGET_PNL_PER_MIN_PER_100=1.73
COOLDOWN_SECONDS=180
FREEZE_EXIT_MIN_PNL=0.15
STATE:dict[str,Any]={"running":False,"mode":"paper","started_at":None,"stopped_at":None,"initial_balance":0.0,"account_balance_usdt":0.0,"free_usdt":0.0,"realized_pnl":0.0,"profit_reserve_usdt":0.0,"assets":{},"open_positions":{},"orders":{},"order_history":[],"trades":[],"config":{},"error":None,"stop_type":None,"pnl_window":[]}

def now(): return datetime.now(timezone.utc).isoformat()

def market(symbol):
    key=symbol.replace('/','').upper()
    with RADAR.lock:
        t=dict(RADAR.tickers.get(key) or {})
        if not t:return None
        price=float(t.get('c') or 0); tf=RADAR._timeframe_metrics(key,price); pulse=RADAR._pulse(key)
    if price<=0:return None
    return {"price":price,"change_24h_pct":float(t.get('P') or 0),"quote_volume_24h":float(t.get('q') or 0),**tf,**pulse}

def pnl(cap,entry,last,fee_pct):
    amount=cap/entry; gross=(last-entry)*amount; fee=(cap+last*amount)*fee_pct/100
    return gross-fee,gross,fee

def threshold():
    ts=STATE.get('trades',[])[-30:]
    if len(ts)<8:return 52.0
    wr=sum(1 for t in ts if float(t.get('net_pnl',0))>0)/len(ts)*100
    return 72.0 if wr<55 else 66.0 if wr<65 else 60.0 if wr<70 else 56.0

def decision(m):
    c1=float(m.get('change_1m_pct',0)); c3=float(m.get('change_3m_pct',0)); vr=float(m.get('volume_ratio',1)); buy=float(m.get('buy_ratio',.5)); stability=float(m.get('stability',0)); velocity=float(m.get('trade_velocity',0)); freeze=float(m.get('freeze_risk',1)); signal=str(m.get('signal','WAIT'))
    momentum=max(0,min(1,c3/.60)); accel=max(0,min(1,(c1*2.5+c3)/1.2)); flow=max(0,min(1,(buy-.50)/.18)); volume=max(0,min(1,(vr-1)/2)); vel=max(0,min(1,velocity/70)); safety=1-freeze
    quality=100*(.28*momentum+.16*accel+.20*flow+.16*volume+.12*vel+.08*stability)
    confirmations=sum((c3>=.03,vr>=1.15 or velocity>=20,buy>=.53,signal not in {'WAIT','FADE'},freeze<.80))
    th=threshold(); ok=confirmations>=3 and quality>=th and signal not in {'WAIT','FADE'}
    return {"quality":round(quality,2),"confirmations":confirmations,"threshold":th,"entry_ok":ok,"freeze_risk":freeze}

def snapshot():
    with LOCK:
        s=dict(STATE); s['open_positions']={k:dict(v) for k,v in STATE['open_positions'].items()}; s['trades']=list(STATE['trades'][-100:]); s['order_history']=list(STATE['order_history'][-100:])
    unreal=0; positions=[]
    for sym,pos in s['open_positions'].items():
        m=market(sym); px=float(m['price']) if m else float(pos['entry_price']); cap=float(pos['allocated_usdt']); qty=float(pos['amount']); upnl=qty*px-cap; unreal+=upnl; positions.append({**pos,'current_price':px,'market_value':qty*px,'unrealized_pnl':upnl,'age_sec':time.time()-float(pos['opened_ts'])})
    closed=s['trades']; wins=sum(1 for t in closed if float(t.get('net_pnl',0))>0); minute_pnl=sum(float(x['pnl']) for x in s.get('pnl_window',[]) if time.time()-float(x['ts'])<=60); capital=float(s.get('initial_balance',0) or 0)
    s.update({'positions':positions,'equity_usdt':float(s.get('account_balance_usdt',0))+unreal,'unrealized_pnl':unreal,'net_pnl':float(s.get('account_balance_usdt',0))+unreal-capital,'balance':float(s.get('free_usdt',0)),'pnl':float(s.get('realized_pnl',0)),'bot_balance_usdt':capital,'available_bot_usdt':float(s.get('free_usdt',0)),'win_rate':round(wins/len(closed)*100,2) if closed else 0,'closed_trades':len(closed),'target_win_rate':70.0,'target_pnl_per_min_per_100':TARGET_PNL_PER_MIN_PER_100,'target_pnl_per_min_usdt':round(capital*TARGET_PNL_PER_MIN_PER_100/100,4),'realized_pnl_last_minute':round(minute_pnl,4),'throughput_pnl_per_min_per_100':round(minute_pnl/capital*100,4) if capital else 0,'capital_efficiency_mode':'PORTFOLIO_THROUGHPUT','profit_policy':'FIXED_BOT_CAPITAL_TO_MAIN_ACCOUNT','max_pairs':10})
    return s

def close_position(sym,pos,last,reason):
    cap=float(pos['allocated_usdt']); net,gross,fee=pnl(cap,float(pos['entry_price']),last,float(pos['fee_pct'])); STATE['free_usdt']+=cap; STATE['account_balance_usdt']+=net; STATE['realized_pnl']+=net
    if net>0:STATE['profit_reserve_usdt']+=net
    STATE['trades'].append({'symbol':sym,'side':'SELL','entry_price':pos['entry_price'],'exit_price':last,'allocated_usdt':cap,'gross_pnl':gross,'fee':fee,'net_pnl':net,'reason':reason,'opened_at':pos['opened_at'],'closed_at':now(),'timeframe':pos['timeframe'],'maker_preferred':True})
    STATE['pnl_window'].append({'ts':time.time(),'pnl':net}); STATE['order_history'].append({'symbol':sym,'side':'SELL','status':'FILLED','price':last,'net_pnl':net,'reason':reason,'time':now()}); STATE['open_positions'].pop(sym,None); STATE['orders'].pop(sym,None); COOLDOWN[sym]=time.time()+COOLDOWN_SECONDS

def tick(sym,allocation,tf):
    m=market(sym)
    if not m:return
    last=float(m['price'])
    with LOCK:
        cfg=dict(STATE['config']); pos=STATE['open_positions'].get(sym); fee=float(cfg.get('fee_pct',.10))
        if pos:
            net,_,_=pnl(float(pos['allocated_usdt']),float(pos['entry_price']),last,fee); age=time.time()-float(pos['opened_ts']); freeze=float(m.get('freeze_risk',1)); target=max(FREEZE_EXIT_MIN_PNL,float(pos['target_profit_usdt'])); reason=None
            if net>=target:reason='TARGET_PROFIT'
            elif net>0 and freeze>=.45 and net>=FREEZE_EXIT_MIN_PNL:reason='FREEZE_PROFIT_EXIT'
            elif net>0 and age>=float(pos['max_hold_seconds']) and freeze>=.35:reason='TIME_OPPORTUNITY_EXIT'
            elif net<0 and age>=float(pos['max_hold_seconds']) and freeze>=.55:reason='HYPOTHESIS_FAILED'
            elif (last/float(pos['entry_price'])-1)*100<=-1.20:reason='CATASTROPHIC_STOP'
            if reason:close_position(sym,pos,last,reason)
            return
        if HALT_ENTRIES or STATE['free_usdt']<=0 or allocation<=0 or allocation>STATE['free_usdt']+1e-9 or time.time()<COOLDOWN.get(sym,0):return
        d=decision(m)
        if not d['entry_ok']:return
        amount=allocation/last; horizon={'1m':60,'3m':180,'5m':300}.get(tf,180); target=allocation*TARGET_PNL_PER_MIN_PER_100/100; STATE['free_usdt']-=allocation
        STATE['open_positions'][sym]={'symbol':sym,'entry_price':last,'amount':amount,'allocated_usdt':allocation,'opened_at':now(),'opened_ts':time.time(),'fee_pct':fee,'signal':'PUMP' if m.get('signal')=='PUMP_NOW' else 'CONFIRMED','hold_seconds':horizon,'max_hold_seconds':horizon,'timeframe':tf,'target_profit_usdt':target,'target_profit_per_min_usdt':target,'quality':d['quality'],'confirmations':d['confirmations'],'entry_threshold':d['threshold'],'maker_preferred':True,'stage':'OPEN'}
        STATE['order_history'].append({'symbol':sym,'side':'BUY','status':'FILLED','price':last,'cost':allocation,'time':now()})

def loop():
    while not STOP.is_set():
        try:
            with LOCK:cfg=dict(STATE['config'])
            for i,sym in enumerate(cfg.get('pairs',[])):tick(sym,float(cfg['initial_balance'])*float(cfg['allocations'][i])/100,cfg.get('timeframes',['3m']*len(cfg['pairs']))[i])
        except Exception as exc:
            with LOCK:STATE['error']=str(exc)[:300]
        time.sleep(1)
    with LOCK:STATE['running']=False;STATE['stopped_at']=now()

def start_paper(config,gateway_unused=None):
    global THREAD,HALT_ENTRIES
    pairs=[str(x).strip().upper().replace('-','/') for x in config.get('pairs',[]) if str(x).strip()]; alloc=[float(x) for x in config.get('allocations',[])]; tfs=[str(x).lower() for x in config.get('timeframes',[])]
    capital=float(config.get('capital',0))
    if not 1<=len(pairs)<=10:raise ValueError('Выберите от 1 до 10 пар.')
    if len(alloc)!=len(pairs) or any(x<=0 for x in alloc) or not 0<sum(alloc)<=100.0001:raise ValueError('Доли должны быть больше 0% и в сумме не превышать 100%.')
    if not tfs:tfs=[str(config.get('timeframe','3m')).lower()]*len(pairs)
    if len(tfs)!=len(pairs) or any(x not in {'1m','3m','5m'} for x in tfs):raise ValueError('Допустимые таймфреймы: 1m, 3m, 5m.')
    if capital<=0:raise ValueError('Бюджет PAPER должен быть больше 0 USDT.')
    RADAR.start();STOP.clear();HALT_ENTRIES=False;COOLDOWN.clear()
    with LOCK:
        STATE.update({'running':True,'mode':'paper','started_at':now(),'stopped_at':None,'initial_balance':capital,'account_balance_usdt':capital,'free_usdt':capital,'realized_pnl':0.0,'profit_reserve_usdt':0.0,'assets':{},'open_positions':{},'orders':{},'order_history':[],'trades':[],'error':None,'stop_type':None,'pnl_window':[],'config':{'pairs':pairs,'allocations':alloc,'allocated_pct':sum(alloc),'unused_capital_pct':100-sum(alloc),'initial_balance':capital,'fee_pct':float(config.get('fee_pct',.10)),'timeframes':tfs,'risk_mode':'PROFIT_FIRST','target_win_rate':70.0,'target_pnl_per_min_per_100':TARGET_PNL_PER_MIN_PER_100}})
    THREAD=threading.Thread(target=loop,daemon=True,name='fast-scalper-throughput-paper');THREAD.start();return snapshot()

def stop_paper(gateway_unused=None):
    global HALT_ENTRIES
    HALT_ENTRIES=True;STOP.set()
    with LOCK:STATE['orders'].clear();STATE['running']=False;STATE['stopped_at']=now();STATE['stop_type']='STOP'
    return snapshot()

def emergency_stop_paper(gateway_unused=None):
    global HALT_ENTRIES
    HALT_ENTRIES=True;STOP.set()
    with LOCK:
        for sym,pos in list(STATE['open_positions'].items()):
            m=market(sym);close_position(sym,pos,float(m['price']) if m else float(pos['entry_price']),'EMERGENCY_STOP')
        STATE['orders'].clear();STATE['running']=False;STATE['stopped_at']=now();STATE['stop_type']='EMERGENCY_STOP'
    return snapshot()
