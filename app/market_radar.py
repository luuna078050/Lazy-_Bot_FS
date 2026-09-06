"""Fast Scalper Binance market radar.

One persistent public WebSocket connection, no REST market polling.
The feed is only market data; no trading/account API is used here.
"""
from __future__ import annotations

import json
import math
import threading
import time
from typing import Any

import websocket

STABLE_BASES={"USDT","USDC","FDUSD","USDE","TUSD","DAI","USD1","USDS","EUR"}
WS_URLS=(
    "wss://stream.binance.com:443/ws/!ticker@arr",
    "wss://stream.binance.com:9443/ws/!ticker@arr",
    "wss://data-stream.binance.vision/ws/!ticker@arr",
)

class MarketRadar:
    def __init__(self, top_n:int=20):
        self.top_n=top_n
        self.lock=threading.RLock()
        self.tickers:dict[str,dict[str,Any]]={}
        self._ws=None
        self._stop=threading.Event()
        self._thread=None
        self.last_error=None
        self.last_update=0.0
        self.connected=False
        self.url=""

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread=threading.Thread(target=self._run,daemon=True,name="fast-scalper-market-radar")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.connected=False
        ws=self._ws
        if ws:
            try: ws.close()
            except Exception: pass
        self._ws=None

    def _run(self):
        while not self._stop.is_set():
            connected_once=False
            for url in WS_URLS:
                if self._stop.is_set():
                    break
                try:
                    self.url=url
                    self.last_error=None
                    ws=websocket.WebSocketApp(
                        url,
                        on_open=self._on_open,
                        on_message=self._on_message,
                        on_error=self._on_error,
                        on_close=self._on_close,
                    )
                    self._ws=ws
                    ws.run_forever(ping_interval=20,ping_timeout=10,suppress_origin=True)
                    if self.last_update:
                        connected_once=True
                        break
                except Exception as exc:
                    self.connected=False
                    self.last_error=f"{type(exc).__name__}: {exc}"[:240]
                finally:
                    self.connected=False
                    self._ws=None
            if not self._stop.is_set():
                time.sleep(2 if connected_once else 3)

    def _on_open(self,_ws):
        self.connected=True
        self.last_error=None

    def _on_close(self,_ws,_code,_msg):
        self.connected=False

    def _on_error(self,_ws,error):
        self.connected=False
        self.last_error=str(error)[:240]

    def _on_message(self,_ws,raw):
        try:
            msg=json.loads(raw)
            data=msg.get("data",msg) if isinstance(msg,dict) else msg
            rows=data if isinstance(data,list) else [data]
            changed=False
            with self.lock:
                for d in rows:
                    if not isinstance(d,dict):
                        continue
                    s=str(d.get("s","")).upper()
                    if not s.endswith("USDT") or s[:-4] in STABLE_BASES:
                        continue
                    try:
                        price=float(d.get("c",0) or 0)
                    except (TypeError,ValueError):
                        continue
                    if price<=0:
                        continue
                    self.tickers[s]=d
                    changed=True
                if changed:
                    self.last_update=time.time()
        except Exception as exc:
            self.last_error=f"message: {exc}"[:240]

    def snapshot(self,limit=15):
        self.start()
        deadline=time.time()+8
        while time.time()<deadline:
            with self.lock:
                if self.tickers:
                    break
            time.sleep(0.15)
        with self.lock:
            items=list(self.tickers.items())
        items=[(s,d) for s,d in items if s.endswith("USDT") and s[:-4] not in STABLE_BASES]
        items.sort(key=lambda x:float(x[1].get("q",0) or 0),reverse=True)
        rows=[]
        for s,d in items[:max(1,int(limit))]:
            try:
                price=float(d.get("c",0) or 0)
                open_price=float(d.get("o",price) or price)
                vol=float(d.get("q",0) or 0)
                pct=(price/open_price-1)*100 if price and open_price else 0.0
            except (TypeError,ValueError,ZeroDivisionError):
                continue
            liquidity=min(1.0,max(0.0,math.log10(max(vol,1))/10))
            momentum=min(1.0,max(0.0,pct)/10)
            score=100*(0.55*momentum+0.45*liquidity)
            signal="BUY" if pct>=1.0 else ("WATCH" if pct>0 else "WAIT")
            target_pct=min(0.006,max(0.0035,abs(pct)/100*0.8))
            rows.append({
                "symbol":s[:-4]+"/USDT","price":price,"change_24h_pct":round(pct,3),
                "quote_volume_24h":vol,"score":round(score,2),"signal":signal,
                "estimated_entry":price,"estimated_exit":price*(1+target_pct),
                "estimated_stop":price*(1-0.004),"change_3m_pct":0.0,
                "volume_ratio":1.0,"pump_events":0,"pump_score":round(momentum,3),
                "hold_seconds":180,
            })
        rows.sort(key=lambda x:(x["score"],x["quote_volume_24h"]),reverse=True)
        return rows[:int(limit)]

    def price(self,symbol):
        s=symbol.upper().replace('/','')
        with self.lock:
            d=self.tickers.get(s)
            try:
                return float(d.get("c",0) or 0) if d else 0.0
            except (TypeError,ValueError):
                return 0.0

RADAR=MarketRadar(20)
