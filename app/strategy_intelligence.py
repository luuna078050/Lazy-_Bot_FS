"""Multi-timeframe intelligence for the Fast Scalper.
Quote-currency agnostic: USDT/USDC/etc. are execution details, not strategy assumptions.
"""
from __future__ import annotations
from typing import Sequence

TF_WEIGHTS = {"4h": .08, "2h": .08, "1h": .10, "30m": .12, "15m": .12, "5m": .16, "3m": .16, "1m": .18}

def _ma(v: Sequence[float], n: int) -> float:
    return sum(v[-n:]) / n if len(v) >= n else sum(v) / max(1, len(v))

def _rsi(v: Sequence[float], n: int = 14) -> float:
    if len(v) <= n: return 50.0
    ds=[b-a for a,b in zip(v[-n-1:-1],v[-n:])]
    g=sum(max(x,0) for x in ds)/n; l=sum(max(-x,0) for x in ds)/n
    return 100.0 if l == 0 else 100.0-100.0/(1.0+g/l)

def _stoch(h: Sequence[float], l: Sequence[float], c: Sequence[float], n: int=14) -> float:
    if len(c)<n:return 50.0
    hi=max(h[-n:]);lo=min(l[-n:]);return 50.0 if hi==lo else (c[-1]-lo)/(hi-lo)*100.0

def _slope(v: Sequence[float], n: int=5) -> float:
    return 0.0 if len(v)<n or not v[-n] else (v[-1]/v[-n]-1)*100

def _smooth(v: Sequence[float], n: int=5) -> float:
    if len(v)<n+1:return 0.0
    ds=[(v[i]/v[i-1]-1)*100 for i in range(len(v)-n,len(v)) if v[i-1]]
    if not ds:return 0.0
    direction=sum(1 if x>0 else -1 if x<0 else 0 for x in ds)/len(ds)
    avg=sum(abs(x) for x in ds)/len(ds)
    consistency=1-min(1,(max(ds)-min(ds))/max(.0001,avg*4))
    return max(-1,min(1,direction*max(0,consistency)))

def timeframe_signal(data: dict) -> dict:
    c=list(map(float,data.get("close",[])));h=list(map(float,data.get("high",c)));l=list(map(float,data.get("low",c)))
    if len(c)<3:return {"direction":"neutral","score":0.0,"confidence":0.0}
    p=c[-1];ma7=_ma(c,7);ma25=_ma(c,25);ma99=_ma(c,99);r=_rsi(c);st=_stoch(h,l,c);sl=_slope(c);sm=_smooth(c)
    x=(.35 if p>ma7 else -.35)+(.25 if ma7>ma25 else -.25)+(.20 if ma25>ma99 else -.20)+max(-.20,min(.20,sl*.08))+sm*.15
    if r>=70 and sl<0:x-=.15
    if r<=30 and sl>0:x+=.15
    if st>=80 and sl<0:x-=.10
    if st<=20 and sl>0:x+=.10
    x=max(-1,min(1,x));d="bullish" if x>.15 else "bearish" if x<-.15 else "neutral"
    return {"direction":d,"score":round(x,4),"confidence":round(min(1,abs(x)+.2),4),"price":p,"ma7":ma7,"ma25":ma25,"ma99":ma99,"rsi14":r,"stoch14":st,"slope5_pct":sl,"smoothness":sm}

def evaluate(timeframes: dict[str,dict], orderbook: dict|None=None) -> dict:
    parts={tf:timeframe_signal(timeframes[tf]) for tf in timeframes if tf in TF_WEIGHTS}
    w=sum(TF_WEIGHTS[t] for t in parts);mtf=sum(parts[t]["score"]*TF_WEIGHTS[t] for t in parts)/w if w else 0
    micro=(parts.get("1m",{}).get("score",0)+parts.get("3m",{}).get("score",0))/2
    ob=float((orderbook or {}).get("score",0));spoof=float((orderbook or {}).get("spoof_risk",0))
    final=max(-1,min(1,mtf*.50+micro*.30+ob*.20))*(1-spoof*.50)
    d="bullish" if final>.18 else "bearish" if final<-.18 else "neutral"
    return {"direction":d,"score":round(final,4),"mtf_score":round(mtf,4),"micro_score":round(micro,4),"orderbook_score":round(ob,4),"spoof_risk":round(spoof,4),"timeframes":parts,"execution_horizon":"1-3m","quote_currency":"agnostic"}
