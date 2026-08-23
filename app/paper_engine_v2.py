from __future__ import annotations
import threading, time
from datetime import datetime, timezone
from typing import Any
from .market_radar import RADAR

_state: dict[str, Any] = {
    'running': False, 'mode': 'paper', 'started_at': None, 'stopped_at': None,
    'initial_balance': 0.0, 'account_balance_usdt': 0.0, 'free_usdt': 0.0,
    'realized_pnl': 0.0, 'assets': {}, 'open_positions': {}, 'orders': {}, 'order_history': [],
    'trades': [], 'config': {}, 'error': None, 'stop_type': None,
}
_lock = threading.RLock(); _thread = None; _stop = threading.Event(); _halt_entries = False

def _now(): return datetime.now(timezone.utc).isoformat()

def _market(symbol: str) -> dict[str, float] | None:
    key = symbol.replace('/', '').upper()
    with RADAR.lock:
        t = dict(RADAR.tickers.get(key) or {})
        pulse = RADAR._pulse(key)
        tf = RADAR._three_min_metrics(key, float(t.get('c') or 0)) if t else {'change_3m_pct': 0.0, 'volume_ratio': 1.0}
    price = float(t.get('c') or 0)
    if price <= 0: return None
    return {'price': price, 'change_24h_pct': float(t.get('P') or 0), **tf, **pulse}

def _copy_state():
    return {**_state,'assets':{k:dict(v) if isinstance(v,dict) else v for k,v in _state['assets'].items()},'open_positions':{k:dict(v) for k,v in _state['open_positions'].items()},'orders':{k:dict(v) for k,v in _state['orders'].items()},'order_history':list(_state['order_history'][-100:]),'trades':list(_state['trades'][-100:])}

def snapshot():
    with _lock:s=_copy_state()
    positions=[]; unreal=0.0
    for symbol,p in s['open_positions'].items():
        m=_market(symbol); px=float(m['price']) if m else float(p['entry_price']); qty=float(p['amount']); value=qty*px; cap=float(p['allocated_usdt']); upnl=value-cap; unreal+=upnl
        positions.append({**p,'current_price':px,'market_value':value,'unrealized_pnl':upnl,'age_sec':max(0,time.time()-float(p.get('opened_ts') or time.time())),'stage':p.get('stage','OPEN')})
    account=float(s.get('account_balance_usdt',s.get('initial_balance',0)) or 0); equity=account+unreal
    s['positions']=positions; s['equity_usdt']=equity; s['unrealized_pnl']=unreal; s['net_pnl']=equity-float(s['initial_balance']); s['balance']=float(s['free_usdt']); s['pnl']=float(s['realized_pnl']); s['bot_balance_usdt']=float(s['initial_balance']); s['available_bot_usdt']=float(s['free_usdt'])
    return s

def _signal(m):
    return {'signal':'PUMP' if m.get('signal')=='PUMP_NOW' else 'NORMAL','hold':int(m.get('hold_seconds',180) or 180),'pump_score':float(m.get('pump_score',0)),'volume_ratio':float(m.get('pulse_volume_ratio',m.get('volume_ratio',1))),'change_3m_pct':float(m.get('change_3m_pct',0)),'pump_events':int(m.get('pump_events',0))}

def _close(symbol,pos,last,reason):
    qty=float(pos['amount']); entry=float(pos['entry_price']); cap=float(pos['allocated_usdt']); fee_pct=float(pos['fee_pct']); gross=(last-entry)*qty; fee=(cap+last*qty)*fee_pct/100; net=gross-fee
    _state['free_usdt'] += cap
    _state['account_balance_usdt'] += net
    base=symbol.split('/')[0]; _state['assets'].pop(base,None); _state['realized_pnl'] += net
    _state['trades'].append({'symbol':symbol,'side':'SELL','entry_price':entry,'exit_price':last,'amount':qty,'gross_pnl':gross,'fee':fee,'net_pnl':net,'reason':reason,'opened_at':pos['opened_at'],'closed_at':_now(),'fills':list(pos.get('fills',[])),'fill_count':len(pos.get('fills',[])),'signal':pos.get('signal')})
    _state['order_history'].append({'symbol':symbol,'side':'SELL','status':'FILLED','requested_amount':qty,'filled_amount':qty,'price':last,'reason':reason,'time':_now()}); _state['open_positions'].pop(symbol,None); _state['orders'].pop(symbol,None)

def _tick(symbol,allocation,target,minp,sl,maxhold):
    m=_market(symbol)
    if not m:return
    last=float(m['price'])
    with _lock:
        pos=_state['open_positions'].get(symbol)
        if pos:
            qty=float(pos['amount']); cap=float(pos['allocated_usdt']); fee_pct=float(pos['fee_pct']); gross=(last-float(pos['entry_price']))*qty; fee=(cap+last*qty)*fee_pct/100; net=gross-fee; age=time.time()-float(pos['opened_ts']); reason=None; hold=float(pos.get('hold_seconds',maxhold))
            if net>=target:reason='TARGET'
            elif sl>0 and (last/float(pos['entry_price'])-1)*100<=-sl:reason='SL'
            elif age>=hold:reason='PUMP_20S_EXIT' if pos.get('signal')=='PUMP' else ('TIMEOUT' if net>=minp else 'CRITICAL_EXIT')
            if reason:_close(symbol,pos,last,reason)
            else:
                base=symbol.split('/')[0]; _state['assets'][base]={'amount':qty,'current_price':last,'value_usdt':qty*last,'entry_value_usdt':cap,'unrealized_pnl':net}
            return
        if _halt_entries or _state['free_usdt']<=0 or allocation<=0:return
        sig=_signal(m)
        if not (float(m.get('change_3m_pct',0))>=.15 or sig['signal']=='PUMP'):return
        if allocation>_state['free_usdt']+1e-9:return
        amount=allocation/last; fills=[{'time':_now(),'amount':amount,'price':last,'cost':allocation}]; _state['free_usdt']-=allocation
        _state['orders'][symbol]={'symbol':symbol,'side':'BUY','requested_usdt':allocation,'requested_amount':amount,'filled_amount':amount,'remaining_amount':0.0,'status':'FILLED','fills':fills,'signal':sig['signal'],'hold_seconds':sig['hold']}
        _state['order_history'].append({**_state['orders'][symbol],'price':last,'time':_now()}); _state['open_positions'][symbol]={'symbol':symbol,'entry_price':last,'amount':amount,'allocated_usdt':allocation,'opened_at':fills[0]['time'],'opened_ts':time.time(),'fee_pct':_state['config']['fee_pct'],'signal':sig['signal'],'hold_seconds':sig['hold'],'pump_score':sig['pump_score'],'fills':fills,'stage':'OPEN'}
        base=symbol.split('/')[0]; _state['assets'][base]={'amount':amount,'current_price':last,'value_usdt':allocation,'entry_value_usdt':allocation,'unrealized_pnl':0.0}; _state['orders'].pop(symbol,None)

def _loop(gateway_unused):
    while not _stop.is_set():
        with _lock:cfg=dict(_state['config'])
        for i,symbol in enumerate(cfg.get('pairs',[])):
            if _stop.is_set():break
            allocation=cfg['initial_balance']*cfg['allocations'][i]/100 if i<len(cfg['allocations']) else 0; _tick(symbol,allocation,cfg['target_usdt'],cfg['min_usdt'],cfg['sl_pct'],cfg['max_hold'])
        time.sleep(1)
    with _lock:_state['running']=False;_state['stopped_at']=_now()

def start_paper(config,gateway_unused=None):
    global _thread,_halt_entries
    pairs=[str(x).strip().upper().replace('-','/') for x in config.get('pairs',[]) if str(x).strip()]; alloc=[float(x) for x in config.get('allocations',[])]; capital=float(config.get('capital',0))
    if not 1<=len(pairs)<=5:raise ValueError('Выберите от 1 до 5 пар.')
    if len(alloc)!=len(pairs) or any(x<=0 for x in alloc) or abs(sum(alloc)-100)>.01:raise ValueError('Доли выбранных пар должны дать ровно 100%.')
    if capital<=0:raise ValueError('Бюджет PAPER должен быть больше 0 USDT.')
    RADAR.start();_stop.clear();_halt_entries=False
    with _lock:_state.update({'running':True,'mode':'paper','started_at':_now(),'stopped_at':None,'initial_balance':capital,'account_balance_usdt':capital,'free_usdt':capital,'realized_pnl':0.0,'assets':{},'open_positions':{},'orders':{},'order_history':[],'trades':[],'error':None,'stop_type':None,'config':{'pairs':pairs,'allocations':alloc,'initial_balance':capital,'target_usdt':float(config.get('target_usdt',.30)),'min_usdt':float(config.get('min_usdt',.20)),'sl_pct':float(config.get('sl_pct',.5)),'max_hold':int(config.get('max_hold',180)),'fee_pct':float(config.get('fee_pct',.1)),'risk_mode':config.get('risk_mode','NORMAL')}})
    _thread=threading.Thread(target=_loop,args=(None,),daemon=True,name='fast-scalper-paper-engine');_thread.start();return snapshot()

def stop_paper(gateway_unused=None):
    global _halt_entries
    _halt_entries=True;_stop.set()
    with _lock:_state['orders'].clear();_state['running']=False;_state['stopped_at']=_now();_state['stop_type']='STOP'
    return snapshot()

def emergency_stop_paper(gateway_unused=None):
    global _halt_entries
    _halt_entries=True;_stop.set()
    with _lock:
        for symbol,pos in list(_state['open_positions'].items()):
            m=_market(symbol);last=float(m['price']) if m else float(pos['entry_price']);_close(symbol,pos,last,'EMERGENCY_STOP')
        _state['orders'].clear();_state['running']=False;_state['stopped_at']=_now();_state['stop_type']='EMERGENCY_STOP'
    return snapshot()
