from __future__ import annotations
import threading,time
from datetime import datetime,timezone
from typing import Any
from .pump_detector import analyze_3m_ohlcv

_state:dict[str,Any]={'running':False,'mode':'paper','started_at':None,'stopped_at':None,'initial_balance':0.0,'balance':0.0,'pnl':0.0,'trades':[],'open_positions':{},'orders':{},'config':{},'error':None,'stop_type':None}
_lock=threading.Lock(); _thread=None; _stop=threading.Event()

def _now(): return time.time()

def snapshot():
    with _lock:return {**_state,'trades':list(_state['trades'][-100:]),'open_positions':{k:dict(v) for k,v in _state['open_positions'].items()},'orders':{k:dict(v) for k,v in _state['orders'].items()}}

def _signal(ex,symbol,timeframe='3m'):
    try:
        pm=analyze_3m_ohlcv(ex.fetch_ohlcv(symbol,timeframe,limit=60)); return {'signal':'PUMP' if pm.get('signal')=='PUMP_NOW' else 'NORMAL','hold':pm.get('hold_seconds',180),'pump_score':pm.get('pump_score',0.0),'volume_ratio':pm.get('volume_ratio',1.0),'change_3m_pct':pm.get('change_3m_pct',0.0),'pump_events':pm.get('pump_events',0)}
    except Exception:return {'signal':'NORMAL','hold':180,'pump_score':0.0,'change_3m_pct':0.0}

def _close(slot_id,pos,last,reason):
    symbol=pos['symbol']; gross=(last-pos['entry_price'])*pos['amount']; fee=(pos['entry_price']*pos['amount']+last*pos['amount'])*pos['fee_pct']/100; net=gross-fee
    _state['balance']+=pos['allocated_usdt']+net; _state['pnl']+=net; _state['trades'].append({'slot_id':slot_id,'symbol':symbol,'timeframe':pos.get('timeframe','3m'),'side':'SELL','entry_price':pos['entry_price'],'exit_price':last,'amount':pos['amount'],'gross_pnl':gross,'fee':fee,'net_pnl':net,'reason':reason,'opened_at':pos['opened_at'],'closed_at':_now(),'fills':list(pos.get('fills',[])),'fill_count':len(pos.get('fills',[])),'signal':pos.get('signal')}); _state['open_positions'].pop(slot_id,None); _state['orders'].pop(slot_id,None)

def _promote_partial_orders():
    for slot_id,order in list(_state['orders'].items()):
        filled=float(order.get('filled_amount') or 0); fills=list(order.get('fills') or [])
        if filled<=0 or not fills: continue
        avg=sum(float(f.get('amount',0))*float(f.get('price',0)) for f in fills)/filled; allocated=sum(float(f.get('cost',0)) for f in fills)
        _state['open_positions'][slot_id]={'slot_id':slot_id,'symbol':order.get('symbol'),'timeframe':order.get('timeframe','3m'),'entry_price':avg,'amount':filled,'allocated_usdt':allocated,'opened_at':fills[0].get('time',_now()),'opened_ts':time.time(),'fee_pct':_state['config']['fee_pct'],'signal':order.get('signal','NORMAL'),'hold_seconds':order.get('hold_seconds',_state['config'].get('max_hold',180)),'pump_score':order.get('pump_score',0),'fills':fills,'stage':'OPEN_AFTER_STOP'}
    _state['orders'].clear()

def _tick(slot_id,symbol,timeframe,allocation,target,minp,sl,maxhold,gateway):
    try:
        ex=gateway('binance').exchange; t=ex.fetch_ticker(symbol); last=float(t.get('last') or 0); pct=float(t.get('percentage') or 0)
        if last<=0:return
        with _lock:
            order=_state['orders'].get(slot_id); pos=_state['open_positions'].get(slot_id)
            if pos:
                gross=(last-pos['entry_price'])*pos['amount']; fee=(pos['entry_price']*pos['amount']+last*pos['amount'])*pos['fee_pct']/100; net=gross-fee; age=time.time()-pos['opened_ts']; reason=None; hold=pos.get('hold_seconds',maxhold)
                if net>=target:reason='TARGET'
                elif sl>0 and (last/pos['entry_price']-1)*100<=-sl:reason='SL'
                elif age>=hold:reason='PUMP_20S_EXIT' if pos.get('signal')=='PUMP' else ('TIMEOUT' if net>=minp else 'CRITICAL_EXIT')
                if reason:_close(slot_id,pos,last,reason)
                return
            if order:
                remaining=order['remaining_amount']; chunk=min(remaining,order['requested_amount']*.5,_state['balance']/last)
                if chunk<=0:return
                cost=chunk*last; _state['balance']-=cost; order['fills'].append({'time':_now(),'amount':chunk,'price':last,'cost':cost}); order['filled_amount']+=chunk; order['remaining_amount']-=chunk; order['status']='FILLED' if order['remaining_amount']<=order['requested_amount']*.00001 else 'PARTIALLY_FILLED'
                if order['status']=='FILLED':
                    avg=sum(f['amount']*f['price'] for f in order['fills'])/order['filled_amount']; sig=order.get('signal','NORMAL'); _state['open_positions'][slot_id]={'slot_id':slot_id,'symbol':symbol,'timeframe':timeframe,'entry_price':avg,'amount':order['filled_amount'],'allocated_usdt':sum(f['cost'] for f in order['fills']),'opened_at':order['fills'][0]['time'],'opened_ts':time.time(),'fee_pct':_state['config']['fee_pct'],'signal_24h_pct':pct,'fills':list(order['fills']),'signal':sig,'hold_seconds':order.get('hold_seconds',maxhold),'pump_score':order.get('pump_score',0)}; _state['orders'].pop(slot_id,None)
                return
            sig=_signal(ex,symbol,timeframe)
            # Entry follows the ranked signal: a PUMP is immediate; otherwise
            # a small positive short-term move is enough for PAPER to exercise
            # the strategy instead of sitting idle because 24h % is flat.
            momentum=float(sig.get('change_3m_pct',0.0) or 0.0)
            entry_ok=(pct>=.15 or sig['signal']=='PUMP' or momentum>=.05 or float(sig.get('pump_score',0) or 0)>=.35)
            if not entry_ok or _state['balance']<=0 or allocation<=0:return
            amt=allocation/last; _state['orders'][slot_id]={'slot_id':slot_id,'symbol':symbol,'timeframe':timeframe,'side':'BUY','requested_usdt':allocation,'requested_amount':amt,'filled_amount':0.0,'remaining_amount':amt,'status':'NEW','fills':[],'signal':sig['signal'],'hold_seconds':sig['hold'],'pump_score':sig.get('pump_score',0)}
    except Exception as e:
        with _lock:_state['error']=str(e)[:300]

def _loop(gateway):
    while not _stop.is_set():
        with _lock:cfg=dict(_state['config']); reinvest=bool(cfg.get('reinvest_profit',False)); base=float(_state['balance'] if reinvest else cfg.get('initial_balance',0) or 0)
        for i,s in enumerate(cfg.get('pairs',[])):
            if _stop.is_set():break
            tf=cfg.get('timeframes',[])[i] if i<len(cfg.get('timeframes',[])) else '3m'; slot_id=f'{i}:{s}:{tf}'
            a=base*cfg['allocations'][i]/100 if i<len(cfg['allocations']) else 0; _tick(slot_id,s,tf,a,cfg['target_usdt'],cfg['min_usdt'],cfg['sl_pct'],cfg['max_hold'],gateway)
        time.sleep(1)
    with _lock:_state['running']=False;_state['stopped_at']=_now()

def start_paper(config,gateway):
    global _thread
    pairs=[str(x).strip().upper().replace('-','/') for x in config.get('pairs',[]) if str(x).strip()]; alloc=[float(x) for x in config.get('allocations',[])]; capital=float(config.get('capital',0)); tfs=[str(x).strip().lower() for x in config.get('timeframes',[])][:len(pairs)]
    tfs=[x if x in {'1m','3m','5m'} else '3m' for x in tfs]
    while len(tfs)<len(pairs):tfs.append('3m')
    if not 1<=len(pairs)<=10:raise ValueError('Выберите от 1 до 10 пар.')
    if len(alloc)!=len(pairs) or any(x<0 or x>100 for x in alloc) or abs(sum(alloc)-100)>.01:raise ValueError('Распределение по парам должно быть от 0 до 100% и дать ровно 100%.')
    if capital<=0:raise ValueError('Бюджет PAPER должен быть больше 0 USDT.')
    with _lock:
        _stop.clear(); _state.update({'running':True,'mode':'paper','started_at':_now(),'stopped_at':None,'initial_balance':capital,'balance':capital,'pnl':0.0,'trades':[],'open_positions':{},'orders':{},'error':None,'stop_type':None,'config':{'pairs':pairs,'allocations':alloc,'timeframes':tfs,'initial_balance':capital,'reinvest_profit':bool(config.get('reinvest_profit',False)),'target_usdt':float(config.get('target_usdt',.30)),'min_usdt':float(config.get('min_usdt',.20)),'sl_pct':float(config.get('sl_pct',.5)),'max_hold':int(config.get('max_hold',180)),'fee_pct':float(config.get('fee_pct',.1)),'risk_mode':config.get('risk_mode','NORMAL')}})
    _thread=threading.Thread(target=_loop,args=(gateway,),daemon=True);_thread.start();return snapshot()

def stop_paper(gateway):
    _stop.set()
    with _lock:
        _promote_partial_orders(); _state['running']=False;_state['stopped_at']=_now();_state['stop_type']='STOP'
    return snapshot()

def emergency_stop_paper(gateway):
    _stop.set()
    with _lock:
        for slot_id,pos in list(_state['open_positions'].items()):
            try:last=float(gateway('binance').exchange.fetch_ticker(pos['symbol']).get('last') or pos['entry_price'])
            except Exception:last=pos['entry_price']
            _close(slot_id,pos,last,'EMERGENCY_STOP')
        _state['orders'].clear();_state['running']=False;_state['stopped_at']=_now();_state['stop_type']='EMERGENCY_STOP'
    return snapshot()
