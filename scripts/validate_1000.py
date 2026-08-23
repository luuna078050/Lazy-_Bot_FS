"""Historical validation for the new 1-3m Fast Scalper profile.
Uses Binance spot OHLCV; order-book history is intentionally not fabricated.
"""
from __future__ import annotations
import json, time, urllib.parse, urllib.request
from statistics import mean
BINANCE='https://api.binance.com/api/v3/klines'

def fetch(symbol='TUTUSDC',days=14):
    end=int(time.time()*1000);start=end-days*86400000;out=[]
    while start<end:
        q=urllib.parse.urlencode({'symbol':symbol,'interval':'1m','limit':1000,'startTime':start,'endTime':end})
        with urllib.request.urlopen(BINANCE+'?'+q,timeout=30) as r:batch=json.load(r)
        if not batch:break
        out += batch; nxt=int(batch[-1][0])+60000
        if nxt<=start:break
        start=nxt;time.sleep(.08)
    return out

def rsi(v,n=14):
    if len(v)<=n:return 50
    d=[v[i]-v[i-1] for i in range(len(v)-n,len(v))];g=sum(max(x,0) for x in d)/n;l=sum(max(-x,0) for x in d)/n
    return 100 if l==0 else 100-100/(1+g/l)

def score(c,h,l):
    if len(c)<100:return 0
    ma7=mean(c[-7:]);ma25=mean(c[-25:]);ma99=mean(c[-99:]);sl=(c[-1]/c[-5]-1)*100
    hi=max(h[-14:]);lo=min(l[-14:]);st=50 if hi==lo else (c[-1]-lo)/(hi-lo)*100
    x=(.35 if c[-1]>ma7 else -.35)+(.25 if ma7>ma25 else -.25)+(.20 if ma25>ma99 else -.20)+max(-.20,min(.20,sl*.08))
    if rsi(c)>=70 and sl<0:x-=.15
    if rsi(c)<=30 and sl>0:x+=.15
    if st>=80 and sl<0:x-=.10
    if st<=20 and sl>0:x+=.10
    return max(-1,min(1,x))

def run(profile):
    rows=fetch();cl=[float(x[4]) for x in rows];hi=[float(x[2]) for x in rows];lo=[float(x[3]) for x in rows]
    horizon=3 if profile=='scalper' else 5;threshold=.20 if profile=='scalper' else .18;fee=.003
    trades=[];i=120
    while i+horizon<len(cl) and len(trades)<1000:
        s=score(cl[:i+1],hi[:i+1],lo[:i+1])
        side=1 if s>=threshold else -1 if s<=-threshold else 0
        if not side:i+=1;continue
        entry=cl[i];exitp=cl[i+horizon];ret=(exitp/entry-1)*side-fee
        trades.append(ret);i+=horizon
    wins=sum(x>0 for x in trades);gross=sum(trades);avg=mean(trades) if trades else 0
    eq=1;peak=1;dd=0
    for x in trades:
        eq*=1+x;peak=max(peak,eq);dd=min(dd,eq/peak-1)
    return {'profile':profile,'symbol':'TUTUSDC','bars':len(cl),'trades':len(trades),'horizon_min':horizon,'threshold':threshold,'fees_plus_slippage_roundtrip_pct':fee*100,'win_rate_pct':wins/len(trades)*100 if trades else 0,'avg_net_return_pct':avg*100,'total_simple_net_return_pct':gross*100,'compounded_return_pct':(eq-1)*100,'max_drawdown_pct':dd*100,'orderbook_backtest':'not fabricated; live depth module validated separately'}
if __name__=='__main__':
    out=[run('scalper'),run('income')];print(json.dumps(out,indent=2));open('validation_1000_result.json','w').write(json.dumps(out,indent=2))
