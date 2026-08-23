"""Dynamic order-book microstructure for Lazy Bot Scalper."""
from __future__ import annotations
from collections import defaultdict,deque
from dataclasses import dataclass
from time import time
from typing import Iterable,Sequence
Level=tuple[float,float]
@dataclass(frozen=True)
class Wall:
    side:str;price:float;amount:float;relative_size:float;distance_pct:float
@dataclass(frozen=True)
class OrderBookSignal:
    direction:str;score:float;confidence:float;bid_ask_imbalance:float
    nearest_bid_wall:Wall|None;nearest_ask_wall:Wall|None;spoof_risk:float
    persistence:float;bid_wall_shift_pct:float;ask_wall_shift_pct:float;pressure_velocity:float
class OrderBookAnalyzer:
    def __init__(self,history_size:int=20,wall_multiplier:float=3.0):
        self.history_size=max(3,history_size);self.wall_multiplier=max(1.5,wall_multiplier);self._history=defaultdict(lambda:deque(maxlen=self.history_size))
    @staticmethod
    def _clean(levels:Iterable[Sequence[float]])->list[Level]:
        out=[]
        for row in levels:
            try:
                p,a=float(row[0]),float(row[1])
                if p>0 and a>=0:out.append((p,a))
            except(TypeError,ValueError,IndexError):continue
        return out
    def _walls(self,side,levels,mid):
        amounts=sorted(a for _,a in levels if a>0)
        if not amounts or mid<=0:return []
        med=amounts[len(amounts)//2];thr=med*self.wall_multiplier
        return sorted([Wall(side,p,a,a/med,abs(p-mid)/mid*100) for p,a in levels if a>=thr],key=lambda w:w.distance_pct)
    @staticmethod
    def _weighted_volume(levels,mid):return sum(a/(1+abs(p-mid)/mid*100) for p,a in levels) if mid else 0
    def analyze(self,symbol,bids,asks,timestamp=None):
        bc,ac=self._clean(bids),self._clean(asks)
        if not bc or not ac:raise ValueError('Both bids and asks are required')
        bb=max(p for p,_ in bc);ba=min(p for p,_ in ac);mid=(bb+ba)/2
        bv,av=self._weighted_volume(bc,mid),self._weighted_volume(ac,mid);imb=(bv-av)/(bv+av) if bv+av else 0
        bw,aw=self._walls('bid',bc,mid),self._walls('ask',ac,mid);hist=self._history[symbol];prev=hist[-1] if hist else None
        prev_walls=prev.get('walls',{}) if prev else {};cur={(w.side,round(w.price,12)):w.amount for w in bw+aw}
        disappeared=sum(a for k,a in prev_walls.items() if k not in cur)/(sum(prev_walls.values()) or 1) if prev_walls else 0
        spoof=min(1,disappeared*1.5);persist=min(len(hist)+1,self.history_size)/self.history_size
        def shift(side,walls):
            if not prev:return 0.0
            candidates=[(p,a) for (s,p),a in prev_walls.items() if s==side]
            if not candidates or not walls:return 0.0
            old=min(candidates,key=lambda x:abs(x[0]-walls[0].price))[0]
            return (walls[0].price-old)/old*100 if old else 0.0
        bs,as_=shift('bid',bw),shift('ask',aw)
        wall_bias=(min(.35,max(0,bw[0].relative_size-1)/20) if bw else 0)-(min(.35,max(0,aw[0].relative_size-1)/20) if aw else 0)
        raw=max(-1,min(1,imb*.75+wall_bias*.25));score=raw*(1-spoof*.6)
        old_score=float(prev.get('score',0)) if prev else 0;velocity=score-old_score
        direction='bullish' if score>.18 else 'bearish' if score<-.18 else 'neutral';confidence=min(1,abs(score)*1.25+persist*.15)
        hist.append({'ts':timestamp or time(),'walls':cur,'score':score})
        return OrderBookSignal(direction,round(score,4),round(confidence,4),round(imb,4),bw[0] if bw else None,aw[0] if aw else None,round(spoof,4),round(persist,4),round(bs,5),round(as_,5),round(velocity,4))
orderbook_analyzer=OrderBookAnalyzer()
def analyze_orderbook(symbol,order_book,timestamp=None):
    s=orderbook_analyzer.analyze(symbol,order_book.get('bids',[]),order_book.get('asks',[]),timestamp);r=s.__dict__.copy()
    r['nearest_bid_wall']=s.nearest_bid_wall.__dict__ if s.nearest_bid_wall else None;r['nearest_ask_wall']=s.nearest_ask_wall.__dict__ if s.nearest_ask_wall else None;return r
