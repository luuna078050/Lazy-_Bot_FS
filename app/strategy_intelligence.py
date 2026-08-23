"""Regime-aware multi-timeframe intelligence for Lazy Bot FS.

The same analytical core is used by Scalper and mirrored by Income. Execution
profiles differ, but the market model evaluates the full context: 4h/2h/1h/
30m/15m/5m/3m/1m, optional 30-second micro-flow, MA/RSI/Stochastic, volume,
trend smoothness, impulse-pullback-retest-breakout structure and live order-book
pressure. Quote currency is deliberately agnostic (USDT/USDC/etc.).
"""
from __future__ import annotations
from statistics import mean
from typing import Sequence

TF_WEIGHTS={"4h":.08,"2h":.10,"1h":.12,"30m":.12,"15m":.12,"5m":.14,"3m":.16,"1m":.16}
EXECUTION_TFS=("1m","3m","5m")
REGIME_TFS=("15m","30m","1h","2h","4h")


def _ma(v:Sequence[float],n:int)->float:
    return 0.0 if not v else sum(v[-n:])/min(n,len(v))


def _rsi(v:Sequence[float],n:int=14)->float:
    if len(v)<=n:return 50.0
    ds=[b-a for a,b in zip(v[-n-1:-1],v[-n:])]
    g=sum(max(x,0.0) for x in ds)/n;l=sum(max(-x,0.0) for x in ds)/n
    return 100.0 if l==0 else 100.0-100.0/(1.0+g/l)


def _stoch(h:Sequence[float],l:Sequence[float],c:Sequence[float],n:int=14)->tuple[float,float]:
    if len(c)<n:return 50.0,50.0
    def k_at(end:int)->float:
        hh=max(h[end-n+1:end+1]);ll=min(l[end-n+1:end+1])
        return 50.0 if hh==ll else (c[end]-ll)/(hh-ll)*100.0
    k=k_at(len(c)-1);ks=[k_at(i) for i in range(max(n-1,len(c)-3),len(c))]
    return k,(sum(ks)/len(ks) if ks else k)


def _slope(v:Sequence[float],n:int=5)->float:
    return 0.0 if len(v)<n or not v[-n] else (v[-1]/v[-n]-1.0)*100.0


def _atr_pct(h:Sequence[float],l:Sequence[float],c:Sequence[float],n:int=14)->float:
    if len(c)<2:return 0.0
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(max(1,len(c)-n),len(c))]
    return mean(trs)/c[-1]*100.0 if trs and c[-1] else 0.0


def _trend_smoothness(c:Sequence[float],n:int=8)->float:
    """How consistently the last n closes move in one direction, 0..1."""
    if len(c)<n+1:return 0.0
    ds=[c[i]-c[i-1] for i in range(len(c)-n,len(c))]
    nonzero=[x for x in ds if x!=0]
    if not nonzero:return 0.0
    up=sum(x>0 for x in nonzero)/len(nonzero);down=1.0-up
    return max(up,down)*2.0-1.0


def _structure(c:Sequence[float],lookback:int=12)->dict:
    """Detect impulse -> pullback -> retest/breakout without chasing a wick."""
    if len(c)<lookback+2:
        return {"state":"unknown","breakout":False,"retest":False,"score":0.0}
    recent=list(c[-lookback:]);prev=list(c[-lookback-2:-2])
    hi=max(prev);lo=min(prev);p=c[-1]
    # A real breakout needs a close beyond the previous range, not merely a wick.
    breakout_up=p>hi;breakout_down=p<lo
    trend=_trend_smoothness(c,8)
    peak=max(recent[:-2]);trough=min(recent[:-2])
    pullback_up=(recent[-3]<peak and p>recent[-3])
    pullback_down=(recent[-3]>trough and p<recent[-3])
    if breakout_up:
        return {"state":"breakout_up","breakout":True,"retest":pullback_up,"score":0.85 if pullback_up else 0.65}
    if breakout_down:
        return {"state":"breakout_down","breakout":True,"retest":pullback_down,"score":-0.85 if pullback_down else -0.65}
    if pullback_up and trend>0:return {"state":"pullback_up","breakout":False,"retest":True,"score":0.45}
    if pullback_down and trend>0:return {"state":"pullback_down","breakout":False,"retest":True,"score":-0.45}
    return {"state":"trend","breakout":False,"retest":False,"score":0.25*trend}


def timeframe_signal(data:dict)->dict:
    c=list(map(float,data.get("close",[])));h=list(map(float,data.get("high",c)));l=list(map(float,data.get("low",c)))
    if len(c)<3:return {"direction":"neutral","score":0.0,"confidence":0.0,"regime_hint":"unknown"}
    p=c[-1];ma7,ma25,ma99=_ma(c,7),_ma(c,25),_ma(c,99);r=_rsi(c);st_k,st_d=_stoch(h,l,c);sl=_slope(c);atr=_atr_pct(h,l,c);smooth=_trend_smoothness(c);structure=_structure(c)
    x=(.30 if p>ma7 else -.30)+(.22 if ma7>ma25 else -.22)+(.18 if ma25>ma99 else -.18)+max(-.16,min(.16,sl*.06))
    if r>=70:x+=.05 if sl>0 else -.12
    elif r<=30:x+=.12 if sl>0 else -.05
    if st_k>st_d and st_k<80:x+=.08
    elif st_k<st_d and st_k>20:x-=.08
    elif st_k>=80 and st_k<st_d:x-=.10
    elif st_k<=20 and st_k>st_d:x+=.10
    # Smooth movement is confirmation; choppy movement is deliberately discounted.
    x += max(-.08,min(.08,smooth*.08))
    x += max(-.10,min(.10,structure["score"]*.12))
    x=max(-1.0,min(1.0,x));d="bullish" if x>.15 else "bearish" if x<-.15 else "neutral";ma_spread=abs(ma7-ma25)/p*100.0 if p else 0.0
    return {"direction":d,"score":round(x,4),"confidence":round(min(1.0,abs(x)+.2),4),"price":p,"ma7":ma7,"ma25":ma25,"ma99":ma99,"rsi14":r,"stoch14_k":st_k,"stoch14_d":st_d,"slope5_pct":sl,"atr14_pct":atr,"ma_spread_pct":ma_spread,"trend_smoothness":round(smooth,4),"structure":structure}


def detect_regime(parts:dict[str,dict])->dict:
    available=[parts[t] for t in REGIME_TFS if t in parts]
    if not available:return {"regime":"unknown","confidence":0.0,"direction_score":0.0}
    scores=[float(x.get("score",0.0)) for x in available];direction_score=sum(scores)/len(scores);dispersion=max(scores)-min(scores) if scores else 0.0;neutral_share=sum(abs(x)<.18 for x in scores)/len(scores);ma_spread=mean(float(x.get("ma_spread_pct",0.0)) for x in available);atr=mean(float(x.get("atr14_pct",0.0)) for x in available);smooth=mean(float(x.get("trend_smoothness",0.0)) for x in available)
    if neutral_share>=.60 and dispersion<=.42 and ma_spread<=2.0:regime="flat"
    elif direction_score>=.18 and dispersion<=.65:regime="bull"
    elif direction_score<=-.18 and dispersion<=.65:regime="bear"
    else:regime="transition"
    confidence=min(1.0,.35+abs(direction_score)*.5+(1.0-min(1.0,dispersion))*.25+abs(smooth)*.10)
    return {"regime":regime,"confidence":round(confidence,4),"direction_score":round(direction_score,4),"dispersion":round(dispersion,4),"ma_spread_pct":round(ma_spread,4),"atr14_pct":round(atr,4),"trend_smoothness":round(smooth,4)}


def evaluate(timeframes:dict[str,dict],orderbook:dict|None=None,micro_30s:dict|None=None,volume_acceleration:float=0.0)->dict:
    parts={tf:timeframe_signal(timeframes[tf]) for tf in timeframes if tf in TF_WEIGHTS};w=sum(TF_WEIGHTS[t] for t in parts);mtf=sum(parts[t]["score"]*TF_WEIGHTS[t] for t in parts)/w if w else 0.0;micro=sum(parts.get(t,{}).get("score",0.0) for t in EXECUTION_TFS)/max(1,sum(t in parts for t in EXECUTION_TFS));regime=detect_regime(parts);ob=float((orderbook or {}).get("score",0.0));spoof=float((orderbook or {}).get("spoof_risk",0.0));ob_velocity=float((orderbook or {}).get("pressure_velocity",0.0));flow=max(-1.0,min(1.0,float(volume_acceleration)))
    micro30=0.0
    if micro_30s:
        micro30=float(micro_30s.get("score",micro_30s.get("direction_score",0.0)));micro30=max(-1.0,min(1.0,micro30))
    final=(mtf*.55+micro*.15+ob*.20+micro30*.05+flow*.05) if regime["regime"]=="flat" else (mtf*.50+micro*.25+ob*.15+micro30*.05+flow*.05)
    final += max(-.05,min(.05,ob_velocity*.05));final=max(-1.0,min(1.0,final))*(1.0-max(0.0,min(1.0,spoof))*.50);d="bullish" if final>.18 else "bearish" if final<-.18 else "neutral"
    return {"direction":d,"score":round(final,4),"mtf_score":round(mtf,4),"micro_score":round(micro,4),"micro_30s_score":round(micro30,4),"volume_flow":round(flow,4),"orderbook_score":round(ob,4),"orderbook_velocity":round(ob_velocity,4),"spoof_risk":round(spoof,4),"regime":regime,"timeframes":parts,"execution_horizon":"1-3m","quote_currency":"agnostic"}


def reassess_position(entry_price:float,current_price:float,age_minutes:float,analysis:dict,alternative_edge:float=0.0)->dict:
    if entry_price<=0 or current_price<=0:return {"action":"HOLD","reason":"invalid_price_data"}
    pnl_pct=(current_price/entry_price-1.0)*100.0;regime=analysis.get("regime",{}).get("regime","unknown");score=float(analysis.get("score",0.0));direction=analysis.get("direction","neutral");rsi=float(analysis.get("timeframes",{}).get("1h",{}).get("rsi14",50.0))
    if pnl_pct<0 and alternative_edge>.04:return {"action":"ROTATE","reason":"alternative_edge_exceeds_recovery_case","pnl_pct":pnl_pct,"alternative_edge":alternative_edge}
    if regime=="flat":
        if pnl_pct<0 and abs(score)<.20:return {"action":"RANGE_HOLD","reason":"underwater_inside_flat_regime","pnl_pct":pnl_pct,"age_minutes":age_minutes}
        return {"action":"HOLD","reason":"flat_regime_needs_range_resolution","pnl_pct":pnl_pct}
    if pnl_pct<0:
        if direction=="bullish" and score>.18:return {"action":"HOLD","reason":"recovery_structure_present","pnl_pct":pnl_pct}
        if direction=="bearish" and score<-.35 and rsi<45 and alternative_edge>.02:return {"action":"ROTATE","reason":"structure_broken_and_capital_has_better_use","pnl_pct":pnl_pct,"alternative_edge":alternative_edge}
        return {"action":"REASSESS","reason":"no_forced_exit_from_pnl_alone","pnl_pct":pnl_pct}
    if direction=="bearish" and score<-.35:return {"action":"EXIT","reason":"confirmed_reversal_after_profit","pnl_pct":pnl_pct}
    return {"action":"HOLD","reason":"position_structure_valid","pnl_pct":pnl_pct}
