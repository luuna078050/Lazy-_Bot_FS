"""Reliable low-request Binance market radar for Fast Scalper.

Uses one public WebSocket market-data stream only. No REST market polling,
so the radar cannot create the previous 418/429 REST request flood.
"""
from __future__ import annotations

import json
import math
import threading
import time
from typing import Any

import websocket

STABLE_BASES={"USDT","USDC","FDUSD","USDE","TUSD","DAI","USD1","USDS","EUR"}
FALLBACK=["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","TRXUSDT","LINKUSDT","AVAXUSDT","SUIUSDT","TONUSDT","LTCUSDT","DOTUSDT","BCHUSDT","NEARUSDT","APTUSDT","ATOMUSDT","UNIUSDT","FILUSDT"]
WS_URL="wss://data-stream.binance.vision/ws/!miniTicker@arr"

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

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread=threading.Thread(target=self._run,daemon=True,name="fast-scalper-market-radar")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.connected=False
        if self._ws:
            try:self._ws.close()
            except Exception:pass

    def _run(self):
        while not self._stop.is_set():
            try:
                self.last_error=None
                self._ws=websocket.WebSocketApp(
                    WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=20,ping_timeout=10)
            except Exception as exc:
                self.connected=False
                self.last_error=str(exc)[:240]
            if not self._stop.is_set():
                time.sleep(2)

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
            data=msg.get("data",msg)
            rows=data if isinstance(data,list) else [data]
            changed=False
            with self.lock:
                for d in rows:
                    if not isinstance(d,dict):
                        continue
                    s=str(d.get("s","")).upper()
                    if not s or not s.endswith("USDT") or s[:-4] in STABLE_BASES:
                        continue
                    self.tickers[s]=d
                    changed=True
                if changed:
                    self.last_update=time.time()
        except Exception as exc:
            self.last_error=str(exc)[:240]

    def snapshot(self,limit=15):
        self.start()
        # Give a newly started WebSocket a short window to deliver its first
        # mini-ticker batch. This fixes the empty-radar startup race.
        deadline=time.time()+6
        while time.time()<deadline:
            with self.lock:
                if self.tickers:
                    break
            time.sleep(.15)
        with self.lock:
            items=list(self.tickers.items())
        items=[(s,d) for s,d in items if s.endswith("USDT") and s[:-4] not in STABLE_BASES]
        items.sort(key=lambda x:float(x[1].get("q",0) or 0),reverse=True)
        if not items:
            return []
        rows=[]
        for s,d in items[:limit]:
            price=float(d.get("c",0) or 0)
            open_price=float(d.get("o",price) or price)
            vol=float(d.get("q",0) or 0)
            pct=(price/open_price-1)*100 if price and open_price else 0.0
            liquidity=min(1.0,max(0.0,math.log10(max(vol,1))/9))
            momentum=min(1.0,max(0.0,pct)/10)
            score=100*(.55*momentum+.45*liquidity)
            if pct>=1.0:
                signal="BUY"
            elif pct>0:
                signal="WATCH"
            else:
                signal="WAIT"
            target_pct=min(.006,max(.0035,abs(pct)/100*.8))
            rows.append({
                "symbol":s[:-4]+"/USDT",
                "price":price,
                "change_24h_pct":round(pct,3),
                "quote_volume_24h":vol,
                "score":round(score,2),
                "signal":signal,
                "estimated_entry":price,
                "estimated_exit":price*(1+target_pct),
                "estimated_stop":price*(1-.004),
                "change_3m_pct":0.0,
                "volume_ratio":1.0,
                "pump_events":0,
                "pump_score":round(max(0.0,min(1.0,momentum)),3),
                "hold_seconds":180,
            })
        rows.sort(key=lambda x:(x["score"],x["quote_volume_24h"]),reverse=True)
        return rows[:limit]

    def price(self,symbol):
        s=symbol.upper().replace('/','')
        with self.lock:
            d=self.tickers.get(s)
            return float(d.get("c",0) or 0) if d else 0.0

RADAR=MarketRadar(20)
