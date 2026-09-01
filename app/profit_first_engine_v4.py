from __future__ import annotations
import time
from . import profit_first_engine_v3 as base
from .market_radar import RADAR

DEFAULT_PROFIT_TARGET_PCT=0.30
REPRICE_COOLDOWN=5.0
ENTRY_MAX_WAIT=20.0
CATASTROPHIC_STOP_PCT=1.20

def _target(allocation, pct):
    return max(0.0, float(allocation or 0))*max(0.0001,float(pct or DEFAULT_PROFIT_TARGET_PCT))/100.0

def _analysis(symbol):
    return RADAR.symbol_analysis(symbol.replace('/',''))

def _projected_exit(entry, allocation, analysis, profit_pct):
    target=_target(allocation,profit_pct)
    return entry*(1+max(0.0001,float(profit_pct)/100)),target

def _open_position(symbol,allocation,timeframe,analysis):
    price=float(analysis['price']); pct=float(base.STATE['config'].get('profit_target_pct',DEFAULT_PROFIT_TARGET_PCT)); exit_price,target=_projected_exit(price,allocation,analysis,pct); amount=allocation/price
    base.STATE['free_usdt']-=allocation
    hold={'1m':60,'3m':180}.get(timeframe,180)
    base.STATE['open_positions'][symbol]={'symbol':symbol,'entry_price':price,'amount':amount,'allocated_usdt':allocation,'opened_at':base.now(),'opened_ts':time.time(),'fee_pct':float(base.STATE['config'].get('fee_pct',.10)),'signal':'WALL_CONFIRMED' if (analysis.get('wall') or {}).get('direction')=='bullish' else 'MATRIX_CONFIRMED','timeframe':timeframe,'hold_seconds':hold,'max_hold_seconds':hold,'target_price':exit_price,'target_profit_usdt':target,'profit_target_pct':pct,'wall_direction':(analysis.get('wall') or {}).get('direction'),'wall_score':(analysis.get('wall') or {}).get('score',0),'matrix':analysis.get('matrix',{}),'quality':analysis.get('score',0),'stage':'OPEN','management':'GLOBAL_PROFIT_TARGET'}
    base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'FILLED','price':price,'cost':allocation,'type':'PAPER_MARKET','reason':'RADAR_ENTRY','time':base.now()})

def _stage_order(symbol,allocation,timeframe,analysis):
    price=float(analysis['price']); pct=float(base.STATE['config'].get('profit_target_pct',DEFAULT_PROFIT_TARGET_PCT)); exit_price,target=_projected_exit(price,allocation,analysis,pct)
    base.STATE['orders'][symbol]={'symbol':symbol,'side':'BUY','status':'NEW','type':'LIMIT','price':price,'requested_usdt':allocation,'created_ts':time.time(),'timeframe':timeframe,'target_price':exit_price,'target_profit_usdt':target,'profit_target_pct':pct,'wall_score':(analysis.get('wall') or {}).get('score',0),'wall_direction':(analysis.get('wall') or {}).get('direction'),'matrix':analysis.get('matrix',{}),'quality':analysis.get('score',0),'reprice_count':0,'last_reprice_ts':0}
    base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'NEW','price':price,'cost':allocation,'type':'PAPER_LIMIT','reason':'RADAR_SETUP','time':base.now()})

def _manage_order(symbol,order,allocation,timeframe):
    a=_analysis(symbol)
    if not a:return
    now=time.time(); wall=a.get('wall') or {}
    if wall.get('direction')=='bearish' and float(wall.get('score',0))<-.12:
        base.STATE['orders'].pop(symbol,None); base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'CANCELED','price':order['price'],'reason':'RADAR_REVERSAL','time':base.now()}); return
    new_price=float(a['price']); old=float(order['price'])
    if now-float(order.get('last_reprice_ts',0))>=REPRICE_COOLDOWN and old>0 and abs(new_price-old)/old>=.0003:
        order['price']=new_price; pct=float(order.get('profit_target_pct',DEFAULT_PROFIT_TARGET_PCT)); order['target_price']=new_price*(1+pct/100); order['reprice_count']+=1; order['last_reprice_ts']=now; base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'REPLACED','old_price':old,'price':new_price,'reason':'PRICE_UPDATE','time':base.now()})
    if abs(float(a['price'])-float(order['price']))/max(float(order['price']),1e-12)<=.0007 and float(a['score'])>=52:
        base.STATE['orders'].pop(symbol,None); _open_position(symbol,allocation,timeframe,a)
    elif now-float(order['created_ts'])>ENTRY_MAX_WAIT:
        base.STATE['orders'].pop(symbol,None); base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'CANCELED','price':order['price'],'reason':'ENTRY_TIMEOUT','time':base.now()})

def _manage_position(symbol,pos):
    a=_analysis(symbol)
    if not a:return
    last=float(a['price']); fee=float(pos.get('fee_pct',.1)); net,_,_=base.pnl(float(pos['allocated_usdt']),float(pos['entry_price']),last,fee); age=time.time()-float(pos['opened_ts']); wall=a.get('wall') or {}; target=float(pos.get('target_profit_usdt',0)); reason=None
    if net>=target and target>0: reason='TARGET_PROFIT'
    elif net>0 and wall.get('direction')=='bearish' and float(wall.get('score',0))<-.12: reason='WALL_REVERSAL_PROFIT'
    elif net>0 and age>=float(pos['max_hold_seconds']): reason='TIME_EXIT_PROFIT'
    elif net<=0 and age>=float(pos['max_hold_seconds']): reason='HYPOTHESIS_FAILED'
    elif (last/float(pos['entry_price'])-1)*100<=-CATASTROPHIC_STOP_PCT: reason='CATASTROPHIC_STOP'
    if reason: base.close_position(symbol,pos,last,reason)
    else:
        pos['current_price']=last; pos['unrealized_pnl']=net; pos['age_sec']=age; pos['wall_direction']=wall.get('direction'); pos['wall_score']=wall.get('score',0); pos['matrix']=a.get('matrix',{}); pos['projected_profit_usdt']=max(0.0,target)

def tick(symbol:str,allocation:float,timeframe:str):
    a=_analysis(symbol)
    if not a:return
    with base.LOCK:
        pos=base.STATE['open_positions'].get(symbol); order=base.STATE['orders'].get(symbol)
        if pos:_manage_position(symbol,pos); return
        if order:_manage_order(symbol,order,allocation,timeframe); return
        if base.HALT_ENTRIES or base.STATE['free_usdt']<=0 or allocation<=0 or allocation>base.STATE['free_usdt']+1e-9 or time.time()<base.COOLDOWN.get(symbol,0):return
        wall=a.get('wall') or {}; matrix=a.get('matrix') or {}; score=float(a.get('score',0)); ups=sum(1 for x in ('1m','3m','5m','15m','30m') if float((matrix.get(x) or {}).get('trend',0))>0); ch3=float((matrix.get('3m') or {}).get('change_pct',0)); ch5=float((matrix.get('5m') or {}).get('change_pct',0)); wall_ok=wall.get('direction') in {'bullish','neutral'} and float(wall.get('score',0))>=-.08; momentum_ok=ch3>=-.10 and ch5>=-.15; signal_ok=score>=52 and wall_ok and momentum_ok and (ups>=2 or float(a.get('pulse',{}).get('pump_score',0))>=.45)
        if signal_ok:_stage_order(symbol,allocation,timeframe,a)

def start_paper(config,gateway_unused=None):
    base.tick=tick; cfg=dict(config); pairs=list(cfg.get('pairs') or []); capital=float(cfg.get('capital',0) or 0); amounts=[float(x) for x in cfg.get('amounts',[]) if float(x)>0]
    if amounts and len(amounts)==len(pairs): cfg['allocations']=[x/capital*100 for x in amounts]
    cfg['profit_target_pct']=float(cfg.get('profit_target_pct',DEFAULT_PROFIT_TARGET_PCT)); cfg['reinvest']=True
    return base.start_paper(cfg,gateway_unused)

def stop_paper(gateway_unused=None):
    base.HALT_ENTRIES=True; base.STOP.set()
    with base.LOCK:
        for sym,pos in list(base.STATE['open_positions'].items()):
            a=_analysis(sym)
            if a:base.close_position(sym,pos,float(a['price']),'MANUAL_STOP')
        base.STATE['orders'].clear(); base.STATE['running']=False; base.STATE['stopped_at']=base.now(); base.STATE['stop_type']='STOP'
    return snapshot()

def emergency_stop_paper(gateway_unused=None):
    base.HALT_ENTRIES=True; base.STOP.set()
    with base.LOCK:
        for sym,pos in list(base.STATE['open_positions'].items()):
            a=_analysis(sym); base.close_position(sym,pos,float(a['price']) if a else float(pos['entry_price']),'EMERGENCY_STOP')
        base.STATE['orders'].clear(); base.STATE['running']=False; base.STATE['stopped_at']=base.now(); base.STATE['stop_type']='EMERGENCY_STOP'
    return snapshot()

def snapshot():
    s=base.snapshot(); s['account_balance_usdt']=float(s.get('account_balance_usdt',s.get('initial_balance',0))); s['free_usdt']=float(s.get('free_usdt',0)); s['invested_usdt']=max(0.0,s['account_balance_usdt']-s['free_usdt']); s['bot_balance_usdt']=float(s.get('initial_balance',0)); s['reinvest']=True; s['strategy']={'profit_target_pct':float(s.get('config',{}).get('profit_target_pct',DEFAULT_PROFIT_TARGET_PCT)),'trade_timeframe':(s.get('config',{}).get('timeframes') or ['3m'])[0],'analysis_timeframes':['1m','3m','5m','15m','30m'],'deep_analysis_slots':8,'reprice_cooldown_sec':REPRICE_COOLDOWN}; return s
