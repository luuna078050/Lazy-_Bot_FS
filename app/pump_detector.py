from __future__ import annotations
import statistics
from typing import Sequence


def analyze_3m_ohlcv(rows: Sequence[Sequence[float]]) -> dict:
    if len(rows) < 10:
        return {'pump_events': 0, 'pump_score': 0.0, 'change_3m_pct': 0.0, 'change_9m_pct': 0.0, 'volume_ratio': 1.0, 'signal': 'NO_DATA', 'hold_seconds': 180}
    closes=[float(x[4]) for x in rows]
    vols=[float(x[5]) for x in rows]
    events=0
    for i in range(10,len(rows)):
        prev=closes[i-1]
        ret=closes[i]/prev-1 if prev else 0
        baseline=statistics.median(vols[max(0,i-10):i]) or 1.0
        if ret>=0.008 and vols[i]/baseline>=1.8: events+=1
    last=closes[-1]; prev=closes[-2]
    change3=last/prev-1 if prev else 0
    change9=last/closes[-4]-1 if closes[-4] else 0
    baseline=statistics.median(vols[-11:-1]) or 1.0
    vr=vols[-1]/baseline
    score=min(1.0,0.45*min(1.0,events/5)+0.30*min(1.0,max(0,vr-1)/4)+0.25*min(1.0,max(0,change3)/0.012))
    signal='PUMP_NOW' if change3>=0.004 and vr>=1.8 and score>=0.55 else ('PUMP_HISTORY' if events>=2 else 'NORMAL')
    return {'pump_events':events,'pump_score':round(score,3),'signal':signal,'change_3m_pct':round(change3*100,4),'change_9m_pct':round(change9*100,4),'volume_ratio':round(vr,2),'hold_seconds':20 if signal=='PUMP_NOW' else 180}
