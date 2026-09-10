"""Fast Scalper market radar.

Radar universe: 100 liquid USDT spot pairs. Selection is driven primarily by
short-term price movement (30s/1m/2m/4m), controlled volatility and repeatable
scalp activity. 24h statistics are used only for liquidity/context, not as the
main directional signal. Pump/reversal behaviour is penalized and exposed as
an explicit risk warning.
"""
from __future__ import annotations

import json
import math
import threading
import time
import urllib.request
from collections import deque
from typing import Any

import websocket

STABLE_BASES={"USDT","USDC","FDUSD","USDE","TUSD","DAI","USD1","USDS","EUR"}
WS_URLS=("wss://stream.binance.com:9443/ws","wss://stream.binance.com:443/ws","wss://data-stream.binance.vision/ws")
REST_URL="https://api.binance.com/api/v3/ticker/24hr"
UNIVERSE_SIZE=100
HISTORY_SECONDS=300

class MarketRadar:
    def __init__(self,top_n:int=15):
        self.top_n=top_n
        self.lock=threading.RLock()
        self.tickers:dict[str,dict[str,Any]]={}
        self.history:dict[str,deque[tuple[float,float]]]={}
        self.symbols:tuple[str,...]=()
        self.last_error=None
        self.last_update=0.0
        self.connected=False
        self.url=""
        self._ws=None
        self._stop=threading.Event()
        self._thread=None
        self._universe_loaded_at=0.0
        self._load_universe(force=True)

    def _load_universe(self,force=False):
        if not force and self.symbols and time.time()-self._universe_loaded_at<300:
            return
        try:
            req=urllib.request.Request(REST_URL,headers={"User-Agent":"FastScalperRadar/0.01"})
            with urllib.request.urlopen(req,timeout=8) as r:
                data=json.loads(r.read().decode("utf-8"))
            candidates=[]
            for d in data if isinstance(data,list) else []:
                s=str(d.get("symbol","")).upper()
                if not s.endswith("USDT") or s[:-4] in STABLE_BASES:
                    continue
                if str(d.get("status","TRADING")).upper()!="TRADING":
                    continue
                try:
                    q=float(d.get("quoteVolume",0) or 0)
                except (TypeError,ValueError):
                    continue
                if q<=0:
                    continue
                candidates.append((q,s.lower()))
            candidates.sort(reverse=True)
            symbols=tuple(s for _,s in candidates[:UNIVERSE_SIZE])
            if symbols:
                with self.lock:
                    self.symbols=symbols
                    for s in symbols:
                        self.history.setdefault(s.upper(),deque(maxlen=360))
                    self._universe_loaded_at=time.time()
                print(f"[RADAR] universe loaded: {len(symbols)} USDT pairs",flush=True)
        except Exception as exc:
            self.last_error=f"universe: {type(exc).__name__}: {exc}"[:240]
            print(f"[RADAR] {self.last_error}",flush=True)

    def start(self):
        self._load_universe()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread=threading.Thread(target=self._run,daemon=True,name="fast-scalper-market-radar")
        self._thread.start()

    def stop(self):
        self._stop.set(); self.connected=False
        ws=self._ws
        if ws:
            try: ws.close()
            except Exception: pass
        self._ws=None

    def _run(self):
        while not self._stop.is_set():
            self._load_universe()
            with self.lock:
                symbols=list(self.symbols)
            if not symbols:
                time.sleep(2)
                continue
            got_data=False
            params=[f"{s}@ticker" for s in symbols]
            for url in WS_URLS:
                if self._stop.is_set(): break
                try:
                    self.url=url; self.last_error=None
                    ws=websocket.WebSocketApp(url,on_open=lambda w,p=params:self._on_open(w,p),on_message=self._on_message,on_error=self._on_error,on_close=self._on_close)
                    self._ws=ws
                    ws.run_forever(ping_interval=20,ping_timeout=10,ping_payload="fs",suppress_origin=True,http_proxy_host=None,http_proxy_port=None)
                    if self.last_update>0:
                        got_data=True; break
                except Exception as exc:
                    self.connected=False; self.last_error=f"{type(exc).__name__}: {exc}"[:240]
                    print(f"[RADAR] {self.last_error}",flush=True)
                finally:
                    self.connected=False; self._ws=None
            if not self._stop.is_set():
                time.sleep(1 if got_data else 2)

    def _on_open(self,ws,params):
        self.connected=True; self.last_error=None
        try:
            ws.send(json.dumps({"method":"SUBSCRIBE","params":params,"id":1}))
            print(f"[RADAR] connected {self.url}; subscribed={len(params)}",flush=True)
        except Exception as exc:
            self.last_error=f"subscribe: {exc}"[:240]
            print(f"[RADAR] {self.last_error}",flush=True)
            try: ws.close()
            except Exception: pass

    def _on_close(self,_ws,code,msg):
        self.connected=False
        if code or msg:
            self.last_error=f"closed {code}: {msg}"[:240]
            print(f"[RADAR] {self.last_error}",flush=True)

    def _on_error(self,_ws,error):
        self.connected=False; self.last_error=str(error)[:240]
        print(f"[RADAR] websocket error: {self.last_error}",flush=True)

    def _on_message(self,_ws,raw):
        try:
            msg=json.loads(raw)
            if isinstance(msg,dict) and msg.get("result") is None and msg.get("id")==1:
                print("[RADAR] subscription acknowledged",flush=True); return
            data=msg.get("data",msg) if isinstance(msg,dict) else msg
            if not isinstance(data,dict): return
            s=str(data.get("s","")).upper()
            with self.lock:
                if s not in {x.upper() for x in self.symbols}: return
            try: px=float(data.get("c",0) or 0)
            except (TypeError,ValueError): return
            if px<=0:return
            now=time.time()
            with self.lock:
                self.tickers[s]=data
                h=self.history.setdefault(s,deque(maxlen=360))
                h.append((now,px))
                cutoff=now-HISTORY_SECONDS
                while h and h[0][0]<cutoff:
                    h.popleft()
                self.last_update=now
        except Exception as exc:
            self.last_error=f"message: {exc}"[:240]
            print(f"[RADAR] {self.last_error}",flush=True)

    @staticmethod
    def _return(h,price,now,seconds):
        if not h:return 0.0
        target=now-seconds
        old=None
        for ts,px in h:
            if ts<=target: old=px
            else: break
        if old is None:
            old=h[0][1]
        return (price/old-1)*100 if old else 0.0

    @staticmethod
    def _volatility(h,now):
        if not h or len(h)<8:return 0.0
        start=now-120
        pts=[(ts,px) for ts,px in h if ts>=start and px>0]
        if len(pts)<8:return 0.0
        returns=[]
        prev=pts[0][1]
        for _,px in pts[1:]:
            if prev>0: returns.append((px/prev-1)*100)
            prev=px
        if len(returns)<5:return 0.0
        mean=sum(returns)/len(returns)
        return math.sqrt(sum((x-mean)**2 for x in returns)/len(returns))*math.sqrt(max(1,len(returns)))

    @staticmethod
    def _activity(h,now):
        if not h:return 0.0
        pts=[(ts,px) for ts,px in h if ts>=now-240 and px>0]
        if len(pts)<5:return 0.0
        moves=[]
        prev=pts[0][1]
        for _,px in pts[1:]:
            if prev>0:moves.append(abs(px/prev-1)*100)
            prev=px
        if not moves:return 0.0
        # More repeated movement is better than one isolated spike.
        active=sum(1 for x in moves if x>=0.01)
        return min(1.0,(active/max(1,len(moves)))*3.0)

    @staticmethod
    def _risk(m30,m60,m120,m240,vol,activity):
        peak=max(abs(m30),abs(m60),abs(m120),abs(m240))
        acceleration=max(0.0,abs(m30)*2-abs(m120))
        one_sided=(m30>0 and m60>0 and m120>0) or (m30<0 and m60<0 and m120<0)
        if peak>=3.0 or acceleration>=1.5:
            return "EXTREME", "SPIKE/PUMP RISK"
        if peak>=1.5 and one_sided:
            return "HIGH", "HIGH VOLATILITY"
        if vol>=0.8 and activity<0.30:
            return "HIGH", "ERRATIC VOLATILITY"
        if vol>=0.35:
            return "MEDIUM", "HIGH VOLATILITY"
        return "LOW", ""

    def snapshot(self,limit=15):
        self.start(); deadline=time.time()+8
        while time.time()<deadline:
            with self.lock:
                if self.tickers:break
            time.sleep(.15)
        now=time.time()
        with self.lock:
            items=list(self.tickers.items())
        rows=[]
        for s,d in items:
            try:
                price=float(d.get("c",0) or 0)
                open_price=float(d.get("o",price) or price)
                vol24=float(d.get("q",0) or 0)
                high=float(d.get("h",price) or price)
                low=float(d.get("l",price) or price)
                pct24=(price/open_price-1)*100 if price and open_price else 0.0
            except (TypeError,ValueError,ZeroDivisionError):
                continue
            with self.lock:
                hist=self.history.get(s.upper())
                h=list(hist) if hist else []
                history_age=(now-h[0][0]) if h else 0.0
            if not h or history_age<20:continue
            m30=self._return(h,price,now,30)
            m60=self._return(h,price,now,60)
            m120=self._return(h,price,now,120)
            m240=self._return(h,price,now,240)
            vol=self._volatility(h,now)
            activity=self._activity(h,now)
            risk,risk_warning=self._risk(m30,m60,m120,m240,vol,activity)
            liquidity=min(1.0,max(0.0,math.log10(max(vol24,1))/10))
            impulse=min(1.0,max(0.0,abs(m60))/0.8)
            persistence=min(1.0,max(0.0,(abs(m30)+abs(m60)+abs(m120))/2.4))
            controlled_vol=min(1.0,max(0.0,vol/0.8))
            risk_penalty={"LOW":1.0,"MEDIUM":0.88,"HIGH":0.58,"EXTREME":0.15}[risk]
            direction=1 if m60>0 else (-1 if m60<0 else 0)
            directional_quality=min(1.0,max(0.0,(direction*m30+direction*m60+direction*m120)/1.2)) if direction else 0.0
            score=100*(0.30*impulse+0.22*persistence+0.18*controlled_vol+0.15*activity+0.10*liquidity+0.05*directional_quality)*risk_penalty
            signal="BUY" if score>=55 and m30>0 and m60>0 and risk!="EXTREME" else ("WATCH" if score>=35 else "WAIT")
            target_pct=min(0.006,max(0.0035,abs(m60)/100*0.8))
            rows.append({
                "symbol":s[:-4]+"/USDT","price":price,"change_24h_pct":round(pct24,3),"quote_volume_24h":vol24,
                "score":round(score,2),"signal":signal,"tf":"1-4m","estimated_entry":price,
                "estimated_exit":price*(1+target_pct),"estimated_stop":price*(1-0.002),
                "change_3m_pct":round(m120,4),"change_30s_pct":round(m30,4),"change_1m_pct":round(m60,4),
                "change_2m_pct":round(m120,4),"change_4m_pct":round(m240,4),"volatility":round(vol,4),
                "scalp_activity":round(activity,3),"volume_ratio":round(liquidity,3),"pump_events":1 if risk=="EXTREME" else 0,
                "pump_score":round(max(0.0,abs(m30)*0.5+max(0.0,abs(m30)*2-abs(m120))),3),
                "risk":risk,"risk_warning":risk_warning,"hold_seconds":60,"history_age":round(history_age,1),
                "universe_size":len(self.symbols),"target_pct":round(target_pct*100,3)
            })
        rows.sort(key=lambda x:(x["signal"]=="BUY",x["score"],abs(x["change_1m_pct"]),x["scalp_activity"],x["quote_volume_24h"]),reverse=True)
        return rows[:int(limit)]

    def price(self,symbol):
        s=symbol.upper().replace('/','')
        with self.lock:
            d=self.tickers.get(s)
            try:return float(d.get("c",0) or 0) if d else 0.0
            except (TypeError,ValueError):return 0.0

RADAR=MarketRadar(15)
