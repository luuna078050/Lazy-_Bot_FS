from __future__ import annotations
import time
from . import profit_first_engine_v3 as base
from .market_radar import RADAR

# Test baseline: 25 USDT position.
# Exit economics scale linearly with the actual position size.
TEST_STAKE_USDT=25.0
IDEAL_PNL_PER_MIN=0.30
ACCEPTABLE_PNL_PER_MIN=0.23
FLOOR_PNL_PER_MIN=0.15
REPRICE_COOLDOWN=5.0
ENTRY_MAX_WAIT=20.0

def _range(allocation:float,minutes:float=1.0):
    scale=max(0.0,float(allocation or 0))/TEST_STAKE_USDT
    return IDEAL_PNL_PER_MIN*scale*minutes,ACCEPTABLE_PNL_PER_MIN*scale*minutes,FLOOR_PNL_PER_MIN*scale*minutes

def _analysis(symbol):return RADAR.symbol_analysis(symbol.replace('/',''))

def _projected_exit(entry:float,allocation:float,analysis:dict):
    wall=analysis.get('wall') or {};tf=analysis.get('tf') or {};ch3=float((tf.get('3m') or {}).get('change_pct',0));ch5=float((tf.get('5m') or {}).get('change_pct',0));pressure=max(-0.004,min(0.006,(ch3*.45+ch5*.25)/100+float(wall.get('score',0))*.002));exit_price=entry*(1+max(.0008,pressure));ideal,acceptable,floor=_range(allocation,1);return exit_price,ideal,acceptable,floor

def _open_position(symbol,allocation,timeframe,analysis):
    price=float(analysis['price']);amount=allocation/price;exit_price,ideal,acceptable,floor=_projected_exit(price,allocation,analysis);base.STATE['free_usdt']-=allocation
    base.STATE['open_positions'][symbol]={'symbol':symbol,'entry_price':price,'amount':amount,'allocated_usdt':allocation,'opened_at':base.now(),'opened_ts':time.time(),'fee_pct':float(base.STATE['config'].get('fee_pct',.10)),'signal':'WALL_CONFIRMED' if (analysis.get('wall') or {}).get('direction')=='bullish' else 'MATRIX_CONFIRMED','timeframe':timeframe,'hold_seconds':{'1m':60,'3m':180,'5m':300}.get(timeframe,180),'max_hold_seconds':{'1m':60,'3m':180,'5m':300}.get(timeframe,180),'target_price':exit_price,'ideal_pnl_per_min':ideal,'acceptable_pnl_per_min':acceptable,'floor_pnl_per_min':floor,'wall_direction':(analysis.get('wall') or {}).get('direction'),'wall_score':(analysis.get('wall') or {}).get('score',0),'matrix':analysis.get('matrix',analysis.get('tf',{})),'quality':analysis.get('score',0),'stage':'OPEN','management':'DYNAMIC_REPRICE'}
    base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'FILLED','price':price,'cost':allocation,'type':'PAPER_LIMIT','reason':'WALL_MATRIX_ENTRY','time':base.now()})

def _stage_order(symbol,allocation,timeframe,analysis):
    price=float(analysis['price']);exit_price,ideal,acceptable,floor=_projected_exit(price,allocation,analysis);base.STATE['orders'][symbol]={'symbol':symbol,'side':'BUY','status':'NEW','type':'LIMIT','price':price,'requested_usdt':allocation,'created_ts':time.time(),'timeframe':timeframe,'ideal_pnl_per_min':ideal,'acceptable_pnl_per_min':acceptable,'floor_pnl_per_min':floor,'target_price':exit_price,'wall_score':(analysis.get('wall') or {}).get('score',0),'wall_direction':(analysis.get('wall') or {}).get('direction'),'matrix':analysis.get('matrix',analysis.get('tf',{})),'quality':analysis.get('score',0),'reprice_count':0,'last_reprice_ts':0}
    base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'NEW','price':price,'cost':allocation,'type':'PAPER_LIMIT','reason':'WALL_MATRIX_SETUP','time':base.now()})

def _manage_order(symbol,order,allocation,timeframe):
    a=_analysis(symbol)
    if not a:return
    now=time.time();wall=a.get('wall') or {};projected=float(a.get('projected_pnl_per_min_100',0))*allocation/100
    if wall.get('direction')=='bearish' and float(wall.get('score',0))<-.12:
        base.STATE['orders'].pop(symbol,None);base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'CANCELED','price':order['price'],'reason':'WALL_DIRECTION_CHANGED','time':base.now()});return
    if projected<float(order['floor_pnl_per_min']) and now-float(order['created_ts'])>=5:
        base.STATE['orders'].pop(symbol,None);base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'CANCELED','price':order['price'],'reason':'EXPECTED_RETURN_BELOW_FLOOR','time':base.now()});return
    new_price=float(a['price']);old=float(order['price'])
    if now-float(order.get('last_reprice_ts',0))>=REPRICE_COOLDOWN and abs(new_price-old)/old>=.0003:
        order['price']=new_price;order['target_price']=_projected_exit(new_price,allocation,a)[0];order['reprice_count']+=1;order['last_reprice_ts']=now;base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'REPLACED','old_price':old,'price':new_price,'reason':'WALL_REPRICE','time':base.now()})
    if abs(float(a['price'])-float(order['price']))/float(order['price'])<=.0005 and float(a['score'])>=52:
        base.STATE['orders'].pop(symbol,None);_open_position(symbol,allocation,timeframe,a)
    elif now-float(order['created_ts'])>ENTRY_MAX_WAIT:
        base.STATE['orders'].pop(symbol,None);base.STATE['order_history'].append({'symbol':symbol,'side':'BUY','status':'CANCELED','price':order['price'],'reason':'ENTRY_TIMEOUT','time':base.now()})

def _manage_position(symbol,pos):
    a=_analysis(symbol)
    if not a:return
    last=float(a['price']);fee=float(pos.get('fee_pct',.1));net,_,_=base.pnl(float(pos['allocated_usdt']),float(pos['entry_price']),last,fee);age=time.time()-float(pos['opened_ts']);wall=a.get('wall') or {};projected=float(a.get('projected_pnl_per_min_100',0))*float(pos['allocated_usdt'])/100;ideal=float(pos['ideal_pnl_per_min']);acceptable=float(pos['acceptable_pnl_per_min']);floor=float(pos['floor_pnl_per_min']);reason=None
    if wall.get('direction')=='bearish' and float(wall.get('score',0))<-.12 and net>0:reason='WALL_REVERSAL_PROFIT'
    elif net>=ideal and projected>=acceptable:reason='IDEAL_RANGE'
    elif net>=acceptable and projected<acceptable:reason='ACCEPTABLE_RANGE'
    elif net>0 and projected<floor:reason='FLOOR_PROTECTION'
    elif net>0 and age>=float(pos['max_hold_seconds']):reason='TIME_EXIT'
    elif net<0 and age>=float(pos['max_hold_seconds']):reason='HYPOTHESIS_FAILED'
    elif (last/float(pos['entry_price'])-1)*100<=-1.20:reason='CATASTROPHIC_STOP'
    if reason:base.close_position(symbol,pos,last,reason)
    else:
        pos['current_price']=last;pos['unrealized_pnl']=net;pos['projected_pnl_per_min']=projected;pos['wall_direction']=wall.get('direction');pos['wall_score']=wall.get('score',0);pos['matrix']=a.get('matrix',a.get('tf',{}));pos['age_sec']=age

def tick(symbol:str,allocation:float,timeframe:str):
    a=_analysis(symbol)
    if not a:return
    with base.LOCK:
        pos=base.STATE['open_positions'].get(symbol);order=base.STATE['orders'].get(symbol)
        if pos:_manage_position(symbol,pos);return
        if order:_manage_order(symbol,order,allocation,timeframe);return
        if base.HALT_ENTRIES or base.STATE['free_usdt']<=0 or allocation<=0 or allocation>base.STATE['free_usdt']+1e-9 or time.time()<base.COOLDOWN.get(symbol,0):return
        wall=a.get('wall') or {};tf=a.get('matrix') or a.get('tf') or {};score=float(a.get('score',0));ch3=float((tf.get('3m') or {}).get('change_pct',0));ch5=float((tf.get('5m') or {}).get('change_pct',0));matrix_up=sum(1 for x in ('1m','3m','5m','15m','30m') if float((tf.get(x) or {}).get('trend',0))>0);wall_ok=wall.get('direction') in {'bullish','neutral'} and float(wall.get('score',0))>=-.08;momentum_ok=ch3>=-.03 and ch5>=-.05;signal_ok=score>=52 and wall_ok and momentum_ok and (matrix_up>=2 or float(a.get('pulse',{}).get('pump_score',0))>=.45)
        if signal_ok:_stage_order(symbol,allocation,timeframe,a)

def start_paper(config,gateway_unused=None):
    base.tick=tick
    cfg=dict(config)
    pairs=list(cfg.get('pairs') or [])
    # The current test profile is one 25 USDT position. If the UI sends 100% for a single 50 USDT test balance, normalize it to 50%.
    if len(pairs)==1 and 'stake_usdt' not in cfg and float(cfg.get('capital',0) or 0)>TEST_STAKE_USDT:
        cfg['allocations']=[TEST_STAKE_USDT/float(cfg['capital'])*100.0]
        cfg['test_stake_usdt']=TEST_STAKE_USDT
    return base.start_paper(cfg,gateway_unused)

def stop_paper(gateway_unused=None):return base.stop_paper(gateway_unused)
def emergency_stop_paper(gateway_unused=None):return base.emergency_stop_paper(gateway_unused)
def snapshot():
    s=base.snapshot();s['strategy']={'test_stake_usdt':TEST_STAKE_USDT,'ideal_pnl_per_min':IDEAL_PNL_PER_MIN,'acceptable_pnl_per_min':ACCEPTABLE_PNL_PER_MIN,'floor_pnl_per_min':FLOOR_PNL_PER_MIN,'dynamic_scaling':'linear_by_position_size','reprice_cooldown_sec':REPRICE_COOLDOWN,'entry_timeout_sec':ENTRY_MAX_WAIT,'analysis_timeframes':['1m','3m','5m','15m','30m'],'ui_timeframes':['1m','3m','5m'],'wall_logic':'LIVE_ORDERBOOK_DYNAMIC'};return s
