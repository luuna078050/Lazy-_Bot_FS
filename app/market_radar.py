"""Binance market radar for Fast Scalper.

Uses one public Binance WebSocket for ticker data and keeps a short local
price history so the 3m trading timeframe has an actual short-term direction
signal instead of relying on 24h change alone.
"""
from __future__ import annotations
import json, math, threading, time
from collections import deque
from typing import Any
import websocket

STABLE_BASES={"USDT","USDC","FDUSD","USDE","TUSD","DAI","USD1","USDS","EUR"}
SYMBOLS=("btcusdt","ethusdt","bnbusdt","solusdt","xrpusdt","dogeusdt","adausdt","trxusdt","linkusdt","suiusdt","avaxusdt","tonusdt","ltcusdt","dotusdt","atomusdt","nearusdt","aptusdt","arbusdt","opusdt","filusdt")
SUB_PARAMS=[f"{s}@ticker" for s in SYMBOLS]
WS_URLS=("wss://stream.binance.com:9443/ws","wss://stream.binance.com:443/ws","wss://data-stream.binance.vision/ws")

class MarketRadar:
    def __init__(self,top_n:int=20):
        self.top_n=top_n
        self.lock=threading.RLock()
        self.tickers:dict[str,dict[str,Any]]={}
        self.history:dict[str,deque[tuple[float,float]]]={s.upper():deque(maxlen=360) for s in SYMBOLS}
        self._ws=None; self._stop=threading.Event(); self._thread=None
        self.last_error=None; self.last_update=0.0; self.connected=False; self.url=""

    def start(self):
        if self._thread and self._thread.is_alive(): return
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
            got_data=False
            for url in WS_URLS:
                if self._stop.is_set(): break
                try:
                    self.url=url; self.last_error=None
                    ws=websocket.WebSocketApp(url,on_open=self._on_open,on_message=self._on_message,on_error=self._on_error,on_close=self._on_close)
                    self._ws=ws
                    ws.run_forever(ping_interval=20,ping_timeout=10,ping_payload="fs",suppress_origin=True,http_proxy_host=None,http_proxy_port=None)
                    if self.last_update>0:
                        got_data=True; break
                except Exception as exc:
                    self.connected=False; self.last_error=f"{type(exc).__name__}: {exc}"[:240]
                    print(f"[RADAR] {self.last_error}",flush=True)
                finally:
                    self.connected=False; self._ws=None
            if not self._stop.is_set(): time.sleep(1 if got_data else 2)

    def _on_open(self,ws):
        self.connected=True; self.last_error=None
        try:
            ws.send(json.dumps({"method":"SUBSCRIBE","params":SUB_PARAMS,"id":1}))
            print(f"[RADAR] connected {self.url}; subscribed={len(SUB_PARAMS)}",flush=True)
        except Exception as exc:
            self.last_error=f"subscribe: {exc}"[:240]; print(f"[RADAR] {self.last_error}",flush=True)
            try: ws.close()
            except Exception: pass

    def _on_close(self,_ws,code,msg):
        self.connected=False
        if code or msg:
            self.last_error=f"closed {code}: {msg}"[:240]; print(f"[RADAR] {self.last_error}",flush=True)

    def _on_error(self,_ws,error):
        self.connected=False; self.last_error=str(error)[:240]; print(f"[RADAR] websocket error: {self.last_error}",flush=True)

    def _on_message(self,_ws,raw):
        try:
            msg=json.loads(raw)
            if isinstance(msg,dict) and msg.get("result") is None and msg.get("id")==1:
                print("[RADAR] subscription acknowledged",flush=True); return
            data=msg.get("data",msg) if isinstance(msg,dict) else msg
            if not isinstance(data,dict): return
            s=str(data.get("s","")).upper()
            if s not in {x.upper() for x in SYMBOLS}: return
            try: px=float(data.get("c",0) or 0)
            except (TypeError,ValueError): return
            if px<=0:return
            now=time.time()
            with self.lock:
                self.tickers[s]=data
                h=self.history.setdefault(s,deque(maxlen=360))
                h.append((now,px))
                self.last_update=now
        except Exception as exc:
            self.last_error=f"message: {exc}"[:240]; print(f"[RADAR] {self.last_error}",flush=True)

    def _momentum_3m(self,s,price,now):
        h=self.history.get(s)
        if not h or len(h)<3:return None
        target=now-180
        old=None
        for ts,px in h:
            if ts<=target: old=px
            else: break
        if old is None:
            return (price/h[0][1]-1)*100
        return (price/old-1)*100 if old else None

    def snapshot(self,limit=15):
        self.start(); deadline=time.time()+8
        while time.time()<deadline:
            with self.lock:
                if self.tickers:break
            time.sleep(.15)
        now=time.time()
        with self.lock: items=list(self.tickers.items())
        items=[(s,d) for s,d in items if s.endswith("USDT") and s[:-4] not in STABLE_BASES]
        rows=[]
        for s,d in items:
            try:
                price=float(d.get("c",0) or 0); open_price=float(d.get("o",price) or price); vol=float(d.get("q",0) or 0)
                pct24=(price/open_price-1)*100 if price and open_price else 0.0
            except (TypeError,ValueError,ZeroDivisionError):continue
            with self.lock:
                hist=self.history.get(s.upper())
                history_age=(now-hist[0][0]) if hist else 0.0
            m3=self._momentum_3m(s.upper(),price,now)
            if m3 is None:m3=0.0
            liquidity=min(1.0,max(0.0,math.log10(max(vol,1))/10))
            momentum_score=min(1.0,max(0.0,m3)/0.8)
            confirmation=min(1.0,max(0.0,pct24)/5.0)
            score=100*(0.65*momentum_score+0.20*confirmation+0.15*liquidity)
            buy_ok=history_age>=30 and m3>=0.03 and pct24>-3.0
            signal="BUY" if buy_ok else ("WATCH" if m3>0 else "WAIT")
            target_pct=min(0.006,max(0.0035,abs(m3)/100*0.8))
            rows.append({"symbol":s[:-4]+"/USDT","price":price,"change_24h_pct":round(pct24,3),"quote_volume_24h":vol,"score":round(score,2),"signal":signal,"tf":"3m","estimated_entry":price,"estimated_exit":price*(1+target_pct),"estimated_stop":price*(1-.002),"change_3m_pct":round(m3,4),"volume_ratio":1.0,"pump_events":0,"pump_score":round(max(0.0,m3)/10,3),"hold_seconds":60,"history_age":round(history_age,1)})
        rows.sort(key=lambda x:(x["signal"]=="BUY",x["change_3m_pct"],x["score"],x["quote_volume_24h"]),reverse=True)
        return rows[:int(limit)]

    def price(self,symbol):
        s=symbol.upper().replace('/','')
        with self.lock:
            d=self.tickers.get(s)
            try:return float(d.get("c",0) or 0) if d else 0.0
            except (TypeError,ValueError):return 0.0

RADAR=MarketRadar(20)
