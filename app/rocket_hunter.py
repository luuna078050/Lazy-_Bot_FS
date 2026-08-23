"""Rocket Hunter for Lazy Scalper.

Principle: catch ignition, not an exhausted rocket. Existing market snapshots
remain supported; candle-level state adds IGNITION/RELOAD/ORBIT/WAIT semantics.
"""
from __future__ import annotations
from dataclasses import dataclass
from statistics import mean
@dataclass(frozen=True)
class RocketSnapshot:
    symbol: str; price: float; volume_24h: float; volume_1h: float; volume_5m: float; volume_3m: float; volume_1m: float
    price_change_1m: float; price_change_3m: float; price_change_5m: float; trades_5m: int; spread_bps: float; depth_usd: float
    buy_imbalance: float; ma7_slope: float; ma25_slope: float; rsi: float; stoch_k: float; stoch_d: float; higher_tf_score: float
@dataclass(frozen=True)
class RocketSignal:
    symbol: str; score: float; phase: str; price: float; expected_horizon_min: int; entry_quality: float; liquidity_quality: float; acceleration: float; reasons: tuple[str, ...]
def _clip(x: float, lo: float=0.0, hi: float=1.0)->float:return max(lo,min(hi,x))
def scan(s: RocketSnapshot)->RocketSignal:
    base_5m=max(s.volume_1h/12.0,1.0);rel_5m=s.volume_5m/base_5m;rel_3m=s.volume_3m/max(s.volume_1h/20.0,1.0);rel_1m=s.volume_1m/max(s.volume_1h/60.0,1.0)
    acceleration=_clip((rel_1m-1.0)/3.0)*.35+_clip((rel_3m-1.0)/2.5)*.35+_clip((rel_5m-1.0)/2.0)*.30
    price_accel=.30*_clip(s.price_change_1m/.02)+.40*_clip(s.price_change_3m/.05)+.30*_clip(s.price_change_5m/.08)
    momentum=.55*price_accel+.45*acceleration;exhaustion=0.0
    if s.rsi>78:exhaustion+=.30
    if s.stoch_k>90 and s.stoch_k<s.stoch_d:exhaustion+=.30
    if s.price_change_5m>.15:exhaustion+=.25
    early=max(0.0,momentum-exhaustion);trend=_clip((s.ma7_slope*20.0+s.ma25_slope*10.0)/2.0);micro=.45*_clip(abs(s.buy_imbalance))+.30*_clip(s.depth_usd/max(s.volume_1h*.01,1.0))+.25*_clip(1.0-s.spread_bps/30.0);higher=_clip((s.higher_tf_score+1.0)/2.0)
    score=max(0.0,min(1.0,.38*early+.20*trend+.18*micro+.14*higher+(.05 if 0<s.price<.001 else 0)-exhaustion*.20))
    phase="EARLY_ROCKET" if score>=.72 and acceleration>=.55 and momentum>=.50 else "IGNITION" if score>=.55 and momentum>=.38 else "WATCH" if score>=.40 else "IGNORE"
    reasons=[]
    if acceleration>=.14:reasons.append("volume_acceleration")
    if price_accel>=.45:reasons.append("price_acceleration")
    if s.buy_imbalance>.20:reasons.append("buyer_imbalance")
    if s.spread_bps<=12:reasons.append("tight_spread")
    if exhaustion>.35:reasons.append("late_entry_risk")
    return RocketSignal(s.symbol,round(score,4),phase,s.price,3,round(early,4),round(micro,4),round(acceleration,4),tuple(reasons))
def rank(snapshots:list[RocketSnapshot],max_candidates:int=20)->list[RocketSignal]:
    signals=[scan(s) for s in snapshots];signals.sort(key=lambda x:(x.phase not in ('EARLY_ROCKET','IGNITION'),-x.score));return signals[:max_candidates]
def classify_candles(candles:list[dict])->dict:
    if len(candles)<8:return {'state':'WAIT','score':0.0,'entry_ready':False,'reason':'not_enough_bars'}
    c=[float(x['close']) for x in candles];v=[float(x.get('volume',0)) for x in candles];h=[float(x['high']) for x in candles];last=c[-1];short_move=(last/c[-4]-1)*100 if c[-4] else 0;prev_move=(c[-4]/c[-8]-1)*100 if c[-8] else 0;base=mean(v[-8:-3]) or 1;vr=v[-1]/base;breakout=last>max(h[-6:-1]);pullback=c[-2]<max(c[-6:-2]) and last>c[-2];accelerating=short_move>.8 and short_move>prev_move*.65
    score=min(1.0,max(0.0,min(.4,max(0,short_move/2*.4))+min(.3,max(0,(vr-1)/2*.3))+(.2 if breakout else .12 if pullback else 0)+(.1 if accelerating else 0)))
    if breakout and accelerating and vr>=1.5:state,ready,reason='IGNITION',True,'breakout_plus_acceleration_plus_volume'
    elif pullback and vr>=1.2 and short_move>0:state,ready,reason='RELOAD',False,'impulse_cooling_retest_watch'
    elif prev_move>2 and short_move<.2 and vr<1:state,ready,reason='ORBIT',False,'impulse_exhausted'
    else:state,ready,reason='WAIT',False,'no_clean_ignition'
    return {'state':state,'score':round(score,4),'entry_ready':ready,'reason':reason,'short_move_pct':round(short_move,4),'previous_move_pct':round(prev_move,4),'volume_ratio':round(vr,3),'price':last}
def entry_plan(candles:list[dict],state:dict)->dict:
    if len(candles)<3:return {'entry':None,'target_1':None,'target_2':None,'invalidation':None,'status':'NO_DATA'}
    high=max(float(x['high']) for x in candles[-3:]);low=min(float(x['low']) for x in candles[-3:]);rng=max(high-low,float(candles[-1]['close'])*.001)
    if state.get('state')!='IGNITION':return {'entry':None,'target_1':None,'target_2':None,'invalidation':round(low,10),'status':'WAIT_FOR_IGNITION'}
    entry=high;return {'entry':round(entry,10),'target_1':round(entry+rng*.8,10),'target_2':round(entry+rng*1.5,10),'invalidation':round(max(low,entry-rng*.65),10),'status':'TRIGGER_ON_BREAKOUT'}
