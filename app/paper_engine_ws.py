from __future__ import annotations
import json, threading, time
from collections import defaultdict, deque
from datetime import datetime, timezone
from statistics import median
from typing import Any
import websocket

_state: dict[str, Any] = {'running':False,'mode':'paper','started_at':None,'stopped_at':None,'initial_balance':0.0,'balance':0.0,'pnl':0.0,'trades':[],'open_positions':{},'orders':{},'config':{},'error':None,'stop_type':None}
_lock=threading.Lock(); _thread=None; _stop=threading.Event(); _feed=None

def _now(): return datetime.now(timezone.utc).isoformat()
def snapshot():
    with _lock:
        return {**_state,'trades':list(_state['trades'][-100:]),'open_positions':{k:dict(v) for k,v in _state['open_positions'].items()},'orders':{k:dict(v) for k,v in _state['orders'].items()}}

class MarketFeed:
    def __init__(self,symbols):
        self.symbols=[s.upper().replace('/','') for s in symbols]
        self.lock=threading.Lock(); self.latest={}; self.pulses=defaultdict(lambda:deque(maxlen=14)); self.current={}; self.bars=defaultdict(lambda:deque(maxlen=8))
        self.ws=None; self.thread=None; self.stop_event=threading.Event(); self.error=None
    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_event.clear(); self.thread=threading.Thread(target=self._run,name='paper-market-websocket',daemon=True); self.thread.start()
    def stop(self):
        self.stop_event.set()
        if self.ws:
            try:self.ws.close()
            except Exception:pass
    def _run(self):
        streams=[]
        for s in self.symbols: streams += [f'{s.lower()}@aggTrade',f'{s.lower()}@kline_3m']
        url='wss://stream.binance.com:443/stream?streams='+'/'.join(streams)
        while not self.stop_event.is_set():
            try:
                self.ws=websocket.WebSocketApp(url,on_message=self._on_message,on_error=self._on_error)
                self.ws.run_forever(ping_interval=15,ping_timeout=10)
            except Exception as exc:self.error=str(exc)[:300]
            if not self.stop_event.is_set():time.sleep(2)
    def _on_error(self,_ws,error): self.error=str(error)[:300]
    def _on_message(self,_ws,raw):
        try:
            d=json.loads(raw).get('data',{}); event=d.get('e'); s=str(d.get('s','')).upper()
            if not s:return
            if event=='aggTrade':
                price=float(d.get('p',0) or 0); qty=float(d.get('q',0) or 0)
                if price<=0:return
                sec=int(time.time()); quote=price*qty; buy=not bool(d.get('m',False))
                with self.lock:
                    self.latest[s]=price; b=self.current.get(s)
                    if b is None or b['sec']!=sec:
                        if b is not None:self._finalize(s,b)
                        b={'sec':sec,'price':price,'quote':0.0,'buy':0.0,'trades':0}; self.current[s]=b
                    b['price']=price; b['quote']+=quote; b['buy']+=quote if buy else 0.0; b['trades']+=1
            elif event=='kline':
                k=d.get('k',{}); close=float(k.get('c',0) or 0); op=float(k.get('o',0) or 0); qv=float(k.get('q',0) or 0)
                if close<=0:return
                row={'ts':float(k.get('t',0))/1000,'open':op,'close':close,'quote_volume':qv,'closed':bool(k.get('x'))}
                with self.lock:
                    self.latest[s]=close; bars=self.bars[s]
                    if bars and bars[-1]['ts']==row['ts']:bars[-1]=row
                    else:bars.append(row)
        except Exception as exc:self.error=str(exc)[:300]
    def _finalize(self,s,b): self.pulses[s].append({'sec':b['sec'],'price':b['price'],'quote':b['quote'],'buy':b['buy'],'trades':b['trades']})
    def snapshot(self,symbol):
        s=symbol.upper().replace('/','')
        with self.lock:
            price=float(self.latest.get(s,0) or 0); h=list(self.pulses.get(s,())); bars=list(self.bars.get(s,()))
        if price<=0:return None
        c1=c2=c3=0.0
        if len(h)>=2:c1=price/h[-2]['price']-1
        if len(h)>=3:c2=price/h[-3]['price']-1
        if len(h)>=4:c3=price/h[-4]['price']-1
        base=median([x['quote'] for x in h[-6:-1] if x['quote']>0]) if len(h)>2 else 0.0; vr=(h[-1]['quote']/base if base>0 else 1.0) if h else 1.0
        buy=(h[-1]['buy']/h[-1]['quote']) if h and h[-1]['quote']>0 else .5
        accel=max(0,c1*10000)+max(0,c2*5000)+max(0,c3*2500)
        score=max(0,min(1,.45*min(1,accel/6)+.30*min(1,max(0,(vr-1)/4))+.25*max(0,min(1,(buy-.5)/.35))))
        state='IGNITION' if c1>=.0012 and c2>=.0018 and vr>=2 and buy>=.58 and score>=.62 else ('EARLY_ROCKET' if c1>=.0006 and vr>=1.5 and buy>=.55 and score>=.45 else 'WAIT')
        change3=0.0; vol3=1.0
        if bars:
            cur=bars[-1]; change3=(price/cur['open']-1)*100 if cur['open']>0 else 0.0
            prev=[x['quote_volume'] for x in bars[-6:-1] if x['quote_volume']>0]; base3=median(prev) if prev else 0.0; vol3=cur['quote_volume']/base3 if base3>0 else 1.0
        return {'price':price,'change_3m_pct':change3,'volume_ratio':vol3,'pump_score':score,'signal':'PUMP' if state=='IGNITION' else 'NORMAL','state':state,'hold':20 if state=='IGNITION' else 180}

def _close(symbol,pos,last,reason):
    gross=(last-pos['entry_price'])*pos['amount']; fee=(pos['entry_price']*pos['amount']+last*pos['amount'])*pos['fee_pct']/100; net=gross-fee
    _state['balance']+=pos['allocated_usdt']+net; _state['pnl']+=net
    _state['trades'].append({'symbol':symbol,'side':'SELL','entry_price':pos['entry_price'],'exit_price':last,'amount':pos['amount'],'gross_pnl':gross,'fee':fee,'net_pnl':net,'reason':reason,'opened_at':pos['opened_at'],'closed_at':_now(),'fills':list(pos.get('fills',[])),'fill_count':len(pos.get('fills',[])),'signal':pos.get('signal')})
    _state['open_positions'].pop(symbol,None); _state['orders'].pop(symbol,None)

def _promote_partial_orders():
    for symbol,order in list(_state['orders'].items()):
        filled=float(order.get('filled_amount') or 0); fills=list(order.get('fills') or [])
        if filled<=0 or not fills: continue
        avg=sum(float(f['amount'])*float(f['price']) for f in fills)/filled; allocated=sum(float(f['cost']) for f in fills)
        _state['open_positions'][symbol]={'symbol':symbol,'entry_price':avg,'amount':filled,'allocated_usdt':allocated,'opened_at':fills[0].get('time',_now()),'opened_ts':time.time(),'fee_pct':_state['config']['fee_pct'],'signal':order.get('signal','NORMAL'),'hold_seconds':order.get('hold_seconds',180),'pump_score':order.get('pump_score',0),'fills':fills,'stage':'OPEN_AFTER_STOP'}
    _state['orders'].clear()

def _tick(symbol,allocation,target,minp,sl,maxhold,feed):
    m=feed.snapshot(symbol)
    if not m:return
    last=float(m['price'])
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
                avg=sum(f['amount']*f['price'] for f in order['fills'])/order['filled_amount']; sig=order.get('signal','NORMAL')
                _state['open_positions'][symbol]={'symbol':symbol,'entry_price':avg,'amount':order['filled_amount'],'allocated_usdt':sum(f['cost'] for f in order['fills']),'opened_at':order['fills'][0]['time'],'opened_ts':time.time(),'fee_pct':_state['config']['fee_pct'],'signal_24h_pct':m['change_3m_pct'],'fills':list(order['fills']),'signal':sig,'hold_seconds':order.get('hold_seconds',maxhold),'pump_score':order.get('pump_score',0)}
                _state['orders'].pop(symbol,None)
            return
        if not (m['change_3m_pct']>=.15 or m['signal']=='PUMP') or _state['balance']<=0 or allocation<=0:return
        amt=allocation/last
        _state['orders'][symbol]={'symbol':symbol,'side':'BUY','requested_usdt':allocation,'requested_amount':amt,'filled_amount':0.0,'remaining_amount':amt,'status':'NEW','fills':[],'signal':m['signal'],'hold_seconds':m['hold'],'pump_score':m['pump_score']}

def _loop(feed):
    while not _stop.is_set():
        with _lock:cfg=dict(_state['config'])
        for i,s in enumerate(cfg.get('pairs',[])):
            if _stop.is_set():break
            allocation=cfg['initial_balance']*cfg['allocations'][i]/100 if i<len(cfg['allocations']) else 0
            _tick(s,allocation,cfg['target_usdt'],cfg['min_usdt'],cfg['sl_pct'],cfg['max_hold'],feed)
        time.sleep(1)
    with _lock:_state['running']=False; _state['stopped_at']=_now()

def start_paper(config,gateway):
    global _thread,_feed
    pairs=[str(x).strip().upper().replace('-','/') for x in config.get('pairs',[]) if str(x).strip()]; alloc=[float(x) for x in config.get('allocations',[])]; capital=float(config.get('capital',0))
    if not 1<=len(pairs)<=5:raise ValueError('Выберите от 1 до 5 пар.')
    if len(alloc)!=len(pairs) or any(x<0 or x>100 or abs(x-round(x/10)*10)>0.001 for x in alloc) or abs(sum(alloc)-100)>.01:raise ValueError('Для PAPER доли должны быть кратны 10% и в сумме дать 100%.')
    if capital<=0:raise ValueError('Бюджет PAPER должен быть больше 0 USDT.')
    with _lock:
        _stop.clear(); _state.update({'running':True,'mode':'paper','started_at':_now(),'stopped_at':None,'initial_balance':capital,'balance':capital,'pnl':0.0,'trades':[],'open_positions':{},'orders':{},'error':None,'stop_type':None,'config':{'pairs':pairs,'allocations':alloc,'initial_balance':capital,'target_usdt':float(config.get('target_usdt',.30)),'min_usdt':float(config.get('min_usdt',.20)),'sl_pct':float(config.get('sl_pct',.5)),'max_hold':int(config.get('max_hold',180)),'fee_pct':float(config.get('fee_pct',.1)),'risk_mode':config.get('risk_mode','NORMAL')}})
    _feed=MarketFeed(pairs); _feed.start(); _thread=threading.Thread(target=_loop,args=(_feed,),daemon=True); _thread.start(); return snapshot()

def stop_paper(gateway):
    global _feed
    _stop.set()
    if _feed:_feed.stop()
    with _lock:
        _promote_partial_orders(); _state['running']=False; _state['stopped_at']=_now(); _state['stop_type']='STOP'
    return snapshot()

def emergency_stop_paper(gateway):
    global _feed
    _stop.set()
    with _lock:
        for symbol,pos in list(_state['open_positions'].items()):
            try:
                m=_feed.snapshot(symbol) if _feed else None; last=float(m['price']) if m else pos['entry_price']
            except Exception:last=pos['entry_price']
            _close(symbol,pos,last,'EMERGENCY_STOP')
        _state['orders'].clear(); _state['running']=False; _state['stopped_at']=_now(); _state['stop_type']='EMERGENCY_STOP'
    if _feed:_feed.stop()
    return snapshot()

def paper_price(symbol):
    try:
        m=_feed.snapshot(symbol) if _feed else None
        return float(m['price']) if m else 0.0
    except Exception:return 0.0
