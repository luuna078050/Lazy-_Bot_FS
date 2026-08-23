from __future__ import annotations
import threading,time
from datetime import datetime,timezone
from typing import Any
from .pump_detector import analyze_3m_ohlcv
_state:dict[str,Any]={'running':False,'mode':'paper','started_at':None,'stopped_at':None,'initial_balance':0.0,'balance':0.0,'pnl':0.0,'trades':[],'open_positions':{},'orders':{},'config':{},'error':None,'stop_type':None}
_lock=threading.Lock(); _thread=None; _stop=threading.Event()
def _now(): return datetime.now(timezone.utc).isoformat()
def snapshot():
 with _lock:return {**_state,'trades':list(_state['trades'][-100:]),'open_positions':{k:dict(v) for k,v in _state['open_positions'].items()},'orders':{k:dict(v) for k,v in _state['orders'].items()}}
def _signal(ex,symbol):
 try:
  pm=analyze_3m_ohlcv(ex.fetch_ohlcv(symbol,'3m',limit=60)); return {'signal':'PUMP' if pm.get('signal')=='PUMP_NOW' else 'NORMAL','hold':pm.get('hold_seconds',180),'pump_score':pm.get('pump_score',0.0),'volume_ratio':pm.get('volume_ratio',1.0),'change_3m_pct':pm.get('change_3m_pct',0.0),'pump_events':pm.get('pump_events',0)}
 except Exception:return {'signal':'NORMAL','hold':180,'pump_score':0.0}
def _close(symbol,pos,last,reason):
 gross=(last-pos['entry_price'])*pos['amount']; fee=(pos['entry_price']*pos['amount']+last*pos['amount'])*pos['fee_pct']/100; net=gross-fee
 _state['balance']+=pos['allocated_usdt']+net; _state['pnl']+=net; _state['trades'].append({'symbol':symbol,'side':'SELL','entry_price':pos['entry_price'],'exit_price':last,'amount':pos['amount'],'gross_pnl':gross,'fee':fee,'net_pnl':net,'reason':reason,'opened_at':pos['opened_at'],'closed_at':_now(),'fills':list(pos.get('fills',[])),'fill_count':len(pos.get('fills',[])),'signal':pos.get('signal')}); _state['open_positions'].pop(symbol,None); _state['orders'].pop(symbol,None)
def _tick(symbol,allocation,target,minp,sl,maxhold,gateway):
 try:
  ex=gateway('binance').exchange; t=ex.fetch_ticker(symbol); last=float(t.get('last') or 0); pct=float(t.get('percentage') or 0)
  if last<=0:return
  with _lock:
   order=_state['orders'].get(symbol); pos=_state['open_positions'].get(symbol)
   if pos:
    gross=(last-pos['entry_price'])*pos['amount']; fee=(pos['entry_price']*pos['amount']+last*pos['amount'])*pos['fee_pct']/100; net=gross-fee; age=time.time()-pos['opened_ts']; reason=None; hold=pos.get('hold_seconds',maxhold)
    if net>=target:reason='TARGET'
    elif sl>0 and (last/pos['entry_price']-1)*100<=-sl:reason='SL'
    elif age>=hold:reason='PUMP_20S_EXIT' if pos.get('signal')=='PUMP' else ('TIMEOUT' if net>=minp else 'CRITICAL_EXIT')
    if reason:_close(symbol,pos,last,reason)
    return
   if order:
    remaining=order['remaining_amount']; chunk=min(remaining,order['requested_amount']*.5,_state['balance']/last)
    if chunk<=0:return
    cost=chunk*last; _state['balance']-=cost; order['fills'].append({'time':_now(),'amount':chunk,'price':last,'cost':cost}); order['filled_amount']+=chunk; order['remaining_amount']-=chunk; order['status']='FILLED' if order['remaining_amount']<=order['requested_amount']*.00001 else 'PARTIALLY_FILLED'
    if order['status']=='FILLED':
     avg=sum(f['amount']*f['price'] for f in order['fills'])/order['filled_amount']; sig=order.get('signal','NORMAL'); _state['open_positions'][symbol]={'symbol':symbol,'entry_price':avg,'amount':order['filled_amount'],'allocated_usdt':sum(f['cost'] for f in order['fills']),'opened_at':order['fills'][0]['time'],'opened_ts':time.time(),'fee_pct':_state['config']['fee_pct'],'signal_24h_pct':pct,'fills':list(order['fills']),'signal':sig,'hold_seconds':order.get('hold_seconds',maxhold),'pump_score':order.get('pump_score',0)}
    return
   sig=_signal(ex,symbol)
   if not (pct>=.15 or sig['signal']=='PUMP') or _state['balance']<=0 or allocation<=0:return
   amt=allocation/last; _state['orders'][symbol]={'symbol':symbol,'side':'BUY','requested_usdt':allocation,'requested_amount':amt,'filled_amount':0.0,'remaining_amount':amt,'status':'NEW','fills':[],'signal':sig['signal'],'hold_seconds':sig['hold'],'pump_score':sig.get('pump_score',0)}
 except Exception as e:
  with _lock:_state['error']=str(e)[:300]
def _loop(gateway):
 while not _stop.is_set():
  with _lock:cfg=dict(_state['config'])
  for i,s in enumerate(cfg.get('pairs',[])):
   if _stop.is_set():break
   a=cfg['initial_balance']*cfg['allocations'][i]/100 if i<len(cfg['allocations']) else 0; _tick(s,a,cfg['target_usdt'],cfg['min_usdt'],cfg['sl_pct'],cfg['max_hold'],gateway)
  time.sleep(5)
 with _lock:_state['running']=False;_state['stopped_at']=_now()
def start_paper(config,gateway):
 global _thread
 pairs=[str(x).strip().upper().replace('-','/') for x in config.get('pairs',[]) if str(x).strip()]; alloc=[float(x) for x in config.get('allocations',[])]; capital=float(config.get('capital',0))
 if not 1<=len(pairs)<=5:raise ValueError('Выберите от 1 до 5 пар.')
 if len(alloc)!=len(pairs) or abs(sum(alloc)-100)>.01:raise ValueError('Распределение по парам должно быть ровно 100%.')
 if capital<=0:raise ValueError('Бюджет PAPER должен быть больше 0 USDT.')
 with _lock:
  _stop.clear(); _state.update({'running':True,'mode':'paper','started_at':_now(),'stopped_at':None,'initial_balance':capital,'balance':capital,'pnl':0.0,'trades':[],'open_positions':{},'orders':{},'error':None,'stop_type':None,'config':{'pairs':pairs,'allocations':alloc,'initial_balance':capital,'target_usdt':float(config.get('target_usdt',.30)),'min_usdt':float(config.get('min_usdt',.20)),'sl_pct':float(config.get('sl_pct',.5)),'max_hold':int(config.get('max_hold',180)),'fee_pct':float(config.get('fee_pct',.1)),'risk_mode':config.get('risk_mode','NORMAL')}})
 _thread=threading.Thread(target=_loop,args=(gateway,),daemon=True);_thread.start();return snapshot()
def stop_paper(gateway):
 _stop.set()
 with _lock:_state['running']=False;_state['stopped_at']=_now();_state['stop_type']='STOP'
 return snapshot()
def emergency_stop_paper(gateway):
 _stop.set()
 with _lock:
  for symbol,pos in list(_state['open_positions'].items()):
   try:last=float(gateway('binance').exchange.fetch_ticker(symbol).get('last') or pos['entry_price'])
   except Exception:last=pos['entry_price']
   _close(symbol,pos,last,'EMERGENCY_STOP')
  _state['orders'].clear();_state['running']=False;_state['stopped_at']=_now();_state['stop_type']='EMERGENCY_STOP'
 return snapshot()
