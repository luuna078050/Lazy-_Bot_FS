"""Low-request Binance market radar.

The scanner deliberately avoids REST polling loops. Binance public market data is
consumed through one WebSocket connection: all-market mini tickers for the
universe and kline/aggTrade streams for the currently most liquid USDT pairs.
This prevents the dashboard from causing the REST 418/429 request flood seen
with the previous implementation.
"""
from __future__ import annotations
import json
import threading
import time
from collections import defaultdict, deque
from statistics import median
from typing import Any

import websocket

STABLE_BASES={"USDT","USDC","FDUSD","USDE","TUSD","DAI","USD1","USDS","EUR"}
FALLBACK=["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","TRXUSDT","LINKUSDT","AVAXUSDT","SUIUSDT","TONUSDT","LTCUSDT","DOTUSDT","BCHUSDT","NEARUSDT","APTUSDT","ATOMUSDT","UNIUSDT","FILUSDT"]

class MarketRadar:
    def __init__(self, top_n:int=20):
        self.top_n=top_n; self.lock=threading.RLock(); self.tickers={}; self.bars=defaultdict(lambda:deque(maxlen=60)); self.pulses=defaultdict(lambda:deque(maxlen=20)); self._ws=None; self._stop=threading.Event(); self._thread=None; self.last_error=None; self.last_update=0.0
    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._thread=threading.Thread(target=self._run,daemon=True,name="fast-scalper-market-radar"); self._thread.start()
    def stop(self):
        self._stop.set()
        if self._ws:
            try:self._ws.close()
            except Exception:pass
    def _top_symbols(self):
        with self.lock:
            rows=[(s,d) for s,d in self.tickers.items() if s.endswith("USDT") and s[:-4] not in STABLE_BASES and float(d.get("q",0) or 0)>=10000]
        rows.sort(key=lambda x:float(x[1].get("q",0) or 0),reverse=True)
        return [s for s,_ in rows[:self.top_n]] or FALLBACK[:self.top_n]
    def _run(self):
        while not self._stop.is_set():
            symbols=self._top_symbols()
            streams=["!miniTicker@arr"]+[f"{s.lower()}@kline_3m" for s in symbols]+[f"{s.lower()}@aggTrade" for s in symbols]
            url="wss://stream.binance.com:9443/stream?streams="+"/".join(streams)
            try:
                self._ws=websocket.WebSocketApp(url,on_message=self._on_message,on_error=self._on_error)
                self._ws.run_forever(ping_interval=15,ping_timeout=10)
            except Exception as exc:self.last_error=str(exc)[:240]
            if not self._stop.is_set():time.sleep(1)
    def _on_error(self,_ws,error): self.last_error=str(error)[:240]
    def _on_message(self,_ws,raw):
        try:
            msg=json.loads(raw); data=msg.get("data",msg)
            event=data.get("e")
            if isinstance(data,list):
                for row in data:self._mini(row)
                return
            if event=="24hrMiniTicker":self._mini(data); return
            if event=="kline":self._kline(data); return
            if event=="aggTrade":self._trade(data)
        except Exception: return
    def _mini(self,d):
        s=str(d.get("s","")).upper();
        if not s:return
        with self.lock:self.tickers[s]=dict(d);self.last_update=time.time()
    def _kline(self,d):
        k=d.get("k",{});s=str(k.get("s","")).upper()
        if not s:return
        row={"ts":float(k.get("t",0))/1000,"open":float(k.get("o",0) or 0),"high":float(k.get("h",0) or 0),"low":float(k.get("l",0) or 0),"close":float(k.get("c",0) or 0),"quote_volume":float(k.get("q",0) or 0),"closed":bool(k.get("x"))}
        with self.lock:
            bars=self.bars[s]
            if bars and bars[-1]["ts"]==row["ts"]:bars[-1]=row
            else:bars.append(row)
    def _trade(self,d):
        s=str(d.get("s","")).upper();p=float(d.get("p",0) or 0);q=float(d.get("q",0) or 0)
        if not s or p<=0:return
        now=int(time.time());buy=not bool(d.get("m",False));quote=p*q
        with self.lock:
            h=self.pulses[s]
            if h and h[-1]["sec"]==now:b=h[-1]
            else:
                b={"sec":now,"price":p,"quote":0.0,"buy_quote":0.0,"trades":0};h.append(b)
            b["price"]=p;b["quote"]+=quote;b["buy_quote"]+=quote if buy else 0;b["trades"]+=1
    def _pulse(self,s):
        with self.lock:h=list(self.pulses.get(s,()))
        if not h:return {"pump_events":0,"pump_score":0.0,"signal":"WAIT","change_3m_pct":0.0,"volume_ratio":1.0,"hold_seconds":180}
        prices=[x["price"] for x in h]; latest=prices[-1]
        def ch(n):return (latest/prices[-1-n]-1)*100 if len(prices)>n and prices[-1-n]>0 else 0.0
        vols=[x["quote"] for x in h];base=median(vols[:-1]) if len(vols)>2 else 0;vr=vols[-1]/base if base>0 else 1.0;br=h[-1]["buy_quote"]/h[-1]["quote"] if h[-1]["quote"] else .5
        events=sum(1 for i in range(1,len(h)) if h[i]["quote"]>max(1,median([x["quote"] for x in h[max(0,i-5):i]]))*1.8 and (h[i]["price"]/h[i-1]["price"]-1)>=.001)
        c3=ch(3);score=min(1.0,.40*min(1,max(0,c3)/1.2)+.35*min(1,max(0,vr-1)/4)+.25*max(0,min(1,(br-.5)/.35)))
        signal="PUMP_NOW" if c3>=.4 and vr>=1.8 and br>=.56 and score>=.5 else "PUMP_HISTORY" if events>=2 else "NORMAL"
        return {"pump_events":events,"pump_score":round(score,3),"signal":signal,"change_3m_pct":round(c3,4),"volume_ratio":round(vr,2),"hold_seconds":20 if signal=="PUMP_NOW" else 180}
    def snapshot(self,limit=20):
        self.start()
        with self.lock:items=list(self.tickers.items())
        items=[(s,d) for s,d in items if s.endswith("USDT") and s[:-4] not in STABLE_BASES]
        items.sort(key=lambda x:float(x[1].get("q",0) or 0),reverse=True)
        rows=[]
        for s,d in items[:limit]:
            price=float(d.get("c",0) or 0);pct=(price/float(d.get("o",price) or price)-1)*100 if price else 0;vol=float(d.get("q",0) or 0);pm=self._pulse(s)
            liquidity=min(1.0,max(0.0,__import__('math').log10(max(vol,1))/8));momentum=min(1.0,max(0,pct)/20);score=100*(.35*pm["pump_score"]+.25*momentum+.25*liquidity+.15*min(1,max(0,pm["change_3m_pct"])/1.2))
            entry=price; target_pct=min(.012,max(.0035,abs(pm["change_3m_pct"])/100*(1.25 if pm["signal"]=="PUMP_NOW" else .8))); rows.append({"symbol":s[:-4]+"/USDT","price":price,"change_24h_pct":round(pct,3),"quote_volume_24h":vol,"score":round(score,2),"estimated_entry":entry,"estimated_exit":entry*(1+target_pct),"estimated_stop":entry*(1-.006 if pm["signal"]=="PUMP_NOW" else .004),**pm})
        rows.sort(key=lambda x:(x["score"],x["quote_volume_24h"]),reverse=True)
        return rows

RADAR=MarketRadar(20)
