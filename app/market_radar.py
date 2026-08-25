"""Binance WebSocket market radar for Fast Skalper.

Ranking is calculated locally from Binance public WebSocket market data.
Binance live market activity is the input layer; Fast Skalper calculates its
own hot-market opportunity, turnover and risk matrix on top.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import defaultdict, deque
from statistics import median
from typing import Any

import websocket

STABLE_BASES = {"USDT", "USDC", "FDUSD", "USDE", "TUSD", "DAI", "USD1", "USDS", "EUR"}
FALLBACK = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT", "SUIUSDT", "TONUSDT",
    "LTCUSDT", "DOTUSDT", "BCHUSDT", "NEARUSDT", "APTUSDT", "ATOMUSDT",
    "UNIUSDT", "FILUSDT",
]


class MarketRadar:
    def __init__(self, top_n: int = 20):
        self.top_n = max(10, min(int(top_n), 20))
        self.lock = threading.RLock()
        self.tickers: dict[str, dict[str, Any]] = {}
        self.bars = defaultdict(lambda: deque(maxlen=60))
        self.pulses = defaultdict(lambda: deque(maxlen=120))
        self._ws = None
        self._stop = threading.Event()
        self._thread = None
        self._ready = threading.Event()
        self.last_error: str | None = None
        self.last_update = 0.0
        self.connected = False
        self.connection_url = ""
        self.message_count = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="fast-scalper-market-radar")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set(); self.connected = False
        if self._ws:
            try: self._ws.close()
            except Exception: pass

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {"connected": self.connected, "ready": self._ready.is_set(), "ticker_count": len(self.tickers),
                    "last_update": self.last_update, "seconds_since_update": round(time.time()-self.last_update,1) if self.last_update else None,
                    "message_count": self.message_count, "last_error": self.last_error,
                    "data_source": "Binance public WebSocket", "rest_polling": False, "connection_url": self.connection_url}

    def _top_symbols(self) -> list[str]:
        with self.lock:
            rows=[(s,d) for s,d in self.tickers.items() if s.endswith("USDT") and s[:-4] not in STABLE_BASES and float(d.get("q",0) or 0)>=10_000]
        rows.sort(key=lambda x: float(x[1].get("q",0) or 0), reverse=True)
        return [s for s,_ in rows[:self.top_n]] or FALLBACK[:self.top_n]

    def _build_url(self) -> str:
        symbols=self._top_symbols(); streams=["!miniTicker@arr"]
        streams += [f"{s.lower()}@kline_3m" for s in symbols]
        streams += [f"{s.lower()}@aggTrade" for s in symbols]
        return "wss://stream.binance.com:443/stream?streams=" + "/".join(streams)

    def _run(self) -> None:
        while not self._stop.is_set():
            url=self._build_url(); self.connection_url=url
            try:
                self._ws=websocket.WebSocketApp(url,on_open=self._on_open,on_message=self._on_message,on_error=self._on_error,on_close=self._on_close)
                self._ws.run_forever(ping_interval=15,ping_timeout=10)
            except Exception as exc:
                self.last_error=str(exc)[:300]; self.connected=False
            if not self._stop.is_set(): time.sleep(1.0)

    def _on_open(self,_ws): self.connected=True; self.last_error=None; print("RADAR_WS_CONNECTED",flush=True)
    def _on_close(self,_ws,close_status_code=None,close_msg=None):
        self.connected=False; print(f"RADAR_WS_CLOSED {close_status_code} {close_msg or ''}",flush=True)
        if close_status_code: self.last_error=f"WebSocket closed: {close_status_code} {close_msg or ''}".strip()
    def _on_error(self,_ws,error): self.connected=False; self.last_error=str(error)[:300]; print(f"RADAR_WS_ERROR {self.last_error}",flush=True)

    def _on_message(self,_ws,raw):
        try:
            msg=json.loads(raw); data=msg.get("data",msg); self.message_count+=1
            if isinstance(data,list):
                for row in data: self._mini(row)
                return
            event=data.get("e")
            if event=="24hrMiniTicker": self._mini(data)
            elif event=="kline": self._kline(data)
            elif event=="aggTrade": self._trade(data)
        except Exception as exc: self.last_error=str(exc)[:300]

    def _mini(self,d):
        s=str(d.get("s","")).upper()
        if not s:return
        with self.lock:
            self.tickers[s]=dict(d); self.last_update=time.time()
            if not self._ready.is_set() and s.endswith("USDT") and s[:-4] not in STABLE_BASES:self._ready.set()

    def _kline(self,d):
        k=d.get("k",{}); s=str(k.get("s","")).upper()
        if not s:return
        row={"ts":float(k.get("t",0))/1000,"open":float(k.get("o",0) or 0),"high":float(k.get("h",0) or 0),"low":float(k.get("l",0) or 0),"close":float(k.get("c",0) or 0),"quote_volume":float(k.get("q",0) or 0),"closed":bool(k.get("x"))}
        with self.lock:
            bars=self.bars[s]
            if bars and bars[-1]["ts"]==row["ts"]: bars[-1]=row
            else: bars.append(row)

    def _trade(self,d):
        s=str(d.get("s","")).upper(); p=float(d.get("p",0) or 0); q=float(d.get("q",0) or 0)
        if not s or p<=0:return
        sec=int(time.time()); buy=not bool(d.get("m",False)); quote=p*q
        with self.lock:
            h=self.pulses[s]
            if h and h[-1]["sec"]==sec: bucket=h[-1]
            else:
                bucket={"sec":sec,"price":p,"quote":0.0,"buy_quote":0.0,"trades":0}; h.append(bucket)
            bucket["price"]=p; bucket["quote"]+=quote; bucket["buy_quote"]+=quote if buy else 0.0; bucket["trades"]+=1

    @staticmethod
    def _clamp(v,lo=0.0,hi=1.0): return min(hi,max(lo,float(v)))

    def _pulse(self,symbol):
        with self.lock: h=list(self.pulses.get(symbol,()))
        if not h:
            return {"pump_events":0,"pump_score":0.0,"signal":"WAIT","pulse_change_3s_pct":0.0,"pulse_volume_ratio":1.0,"buy_ratio":0.5,"trade_velocity":0.0,"quote_velocity_1m":0.0,"velocity_surge":0.0,"freeze_risk":1.0,"hold_seconds":180}
        prices=[x["price"] for x in h]; latest=prices[-1]
        def ch(n): return 0.0 if len(prices)<=n or prices[-1-n]<=0 else (latest/prices[-1-n]-1)*100
        vols=[x["quote"] for x in h]; base=median(vols[:-1]) if len(vols)>2 else 0.0; vr=vols[-1]/base if base>0 else 1.0
        br=h[-1]["buy_quote"]/h[-1]["quote"] if h[-1]["quote"] else 0.5
        last60=h[-60:]; trades=sum(x["trades"] for x in last60); quote=sum(x["quote"] for x in last60)
        prev60=h[-120:-60]; prev_trades=sum(x["trades"] for x in prev60) if prev60 else 0; prev_quote=sum(x["quote"] for x in prev60) if prev60 else 0
        velocity_surge=(trades/prev_trades) if prev_trades>0 else (2.0 if trades>0 else 0.0)
        velocity_score=self._clamp((math.log1p(trades)-math.log1p(10))/math.log1p(990))
        quote_velocity=quote
        quiet=max(0,60-len([x for x in last60 if x["trades"]>0])); quiet_ratio=quiet/60
        freeze_risk=self._clamp(0.65*quiet_ratio+0.35*(1.0-self._clamp((velocity_surge-0.5)/2.5)))
        events=0
        for i in range(1,len(h)):
            prior=[x["quote"] for x in h[max(0,i-5):i]]; prior_med=median(prior) if prior else 0
            jump=h[i]["price"]/h[i-1]["price"]-1 if h[i-1]["price"]>0 else 0
            if prior_med>0 and h[i]["quote"]>prior_med*1.8 and jump>=0.001:events+=1
        c3=ch(3)
        pump_score=min(1.0,0.40*self._clamp(max(0,c3)/0.30)+0.35*self._clamp(max(0,vr-1)/4)+0.25*self._clamp((br-0.5)/0.35))
        signal="PUMP_NOW" if c3>=0.12 and vr>=1.8 and br>=0.56 and pump_score>=0.50 else ("PUMP_HISTORY" if events>=2 else "NORMAL")
        return {"pump_events":events,"pump_score":round(pump_score,3),"signal":signal,"pulse_change_3s_pct":round(c3,4),"pulse_volume_ratio":round(vr,2),"buy_ratio":round(br,4),"trade_velocity":round(velocity_score*100,2),"quote_velocity_1m":round(quote_velocity,2),"velocity_surge":round(velocity_surge,2),"freeze_risk":round(freeze_risk,3),"hold_seconds":20 if signal=="PUMP_NOW" else 180}

    def _timeframe_metrics(self,symbol,price):
        with self.lock: bars=list(self.bars.get(symbol,()))
        if not bars or price<=0:return {"change_1m_pct":0.0,"change_3m_pct":0.0,"change_5m_pct":0.0,"volume_ratio":1.0,"volume_surge":0.0,"stability":0.0}
        closes=[float(x["close"] or 0) for x in bars if float(x["close"] or 0)>0]; current=bars[-1]; base3=float(current["open"] or price)
        change3=(price/base3-1)*100 if base3>0 else 0; change5=((price/closes[-2])-1)*100 if len(closes)>=2 and closes[-2]>0 else change3; change1=change3/3
        prev=[float(x["quote_volume"] or 0) for x in bars[-6:-1] if float(x["quote_volume"] or 0)>0]; baseline=median(prev) if prev else 0; cv=float(current["quote_volume"] or 0); vr=cv/baseline if baseline>0 else 1; surge=self._clamp((vr-1)/3)
        rc=[]
        for i in range(max(1,len(closes)-5),len(closes)):
            if closes[i-1]>0:rc.append(closes[i]/closes[i-1]-1)
        if len(rc)>=2:
            avg=sum(rc)/len(rc); var=sum((x-avg)**2 for x in rc)/len(rc); stability=self._clamp(1-math.sqrt(var)/0.01)
        else: stability=0
        return {"change_1m_pct":round(change1,4),"change_3m_pct":round(change3,4),"change_5m_pct":round(change5,4),"volume_ratio":round(vr,2),"volume_surge":round(surge,4),"stability":round(stability,4)}

    def _hot_market_score(self,pct24,tf,pulse,liquidity):
        trend24=self._clamp(max(0,pct24)/12); short=self._clamp(max(0,tf["change_3m_pct"])/1); flow=self._clamp((pulse["buy_ratio"]-0.5)/0.18); surge=tf["volume_surge"]; now=1 if pulse["signal"]=="PUMP_NOW" else (0.55 if pulse["signal"]=="PUMP_HISTORY" else 0)
        return self._clamp(0.25*trend24+0.25*short+0.20*flow+0.20*surge+0.10*now)

    def _opportunity_score(self,hot,tf,pulse,liquidity,pct24):
        momentum=self._clamp(max(0,tf["change_3m_pct"])/1); acceleration=self._clamp((tf["change_3m_pct"]-tf["change_5m_pct"]*0.6)/0.8); flow=self._clamp((pulse["buy_ratio"]-0.5)/0.18); surge=tf["volume_surge"]; velocity=self._clamp(pulse["trade_velocity"]/100); stability=tf["stability"]; trend=self._clamp(max(0,pct24)/12); freeze=1-pulse["freeze_risk"]
        extension=self._clamp(max(0,abs(tf["change_3m_pct"])-1.2)/1.5); rr=self._clamp(0.65*(1-extension)+0.35*stability)
        components={"hot":hot,"momentum":momentum,"acceleration":acceleration,"flow":flow,"volume_surge":surge,"trade_velocity":velocity,"liquidity":liquidity,"stability":stability,"risk_reward":rr,"trend_24h":trend,"freeze_safety":freeze}
        score=100*(0.12*hot+0.13*momentum+0.08*acceleration+0.13*flow+0.15*surge+0.15*velocity+0.05*liquidity+0.06*stability+0.08*rr+0.02*trend+0.03*freeze)
        return round(self._clamp(score,0,100),2),components

    def snapshot(self,limit=20):
        self.start()
        if not self._ready.wait(timeout=8):return []
        with self.lock:items=list(self.tickers.items())
        items=[(s,d) for s,d in items if s.endswith("USDT") and s[:-4] not in STABLE_BASES]
        items.sort(key=lambda x:float(x[1].get("q",0) or 0),reverse=True)
        rows=[]
        for s,d in items[:max(10,min(limit,self.top_n))]:
            price=float(d.get("c",0) or 0)
            if price<=0:continue
            open24=float(d.get("o",price) or price); pct24=(price/open24-1)*100 if open24>0 else 0; volume24=float(d.get("q",0) or 0); liquidity=self._clamp(math.log10(max(volume24,1))/8)
            tf=self._timeframe_metrics(s,price); pulse=self._pulse(s); hot=self._hot_market_score(pct24,tf,pulse,liquidity); score,components=self._opportunity_score(hot,tf,pulse,liquidity,pct24)
            target_pct=min(0.012,max(0.0025,abs(tf["change_3m_pct"])/100*(1.10 if pulse["signal"]=="PUMP_NOW" else 0.75))); stop_pct=0.006 if pulse["signal"]=="PUMP_NOW" else 0.004
            # Expected net throughput estimate on $100. It is a forecast, not a guarantee.
            gross_3m=100*target_pct; fee=0.20; expected_net=max(0,gross_3m-fee); expected_per_min=expected_net/3.0
            velocity_factor=max(0.25,pulse["trade_velocity"]/70); freeze_factor=max(0.15,1-pulse["freeze_risk"]); expected_per_min*=velocity_factor*freeze_factor
            rows.append({"symbol":s[:-4]+"/USDT","price":price,"change_24h_pct":round(pct24,3),"quote_volume_24h":volume24,"score":score,"hot_market_score":round(hot*100,2),"ranking_components":components,"estimated_entry":price,"estimated_exit":price*(1+target_pct),"estimated_stop":price*(1-stop_pct),"estimated_target_pct":round(target_pct*100,4),"expected_pnl_per_min_100":round(expected_per_min,4),"estimated_pnl_usdt_100":round(expected_net,4),**tf,**pulse})
        rows.sort(key=lambda x:(x["score"],x["expected_pnl_per_min_100"],x["trade_velocity"]),reverse=True)
        return rows[:max(10,min(limit,self.top_n))]

RADAR=MarketRadar(20)
RADAR.start()


def _boot_radar_check():
    def _check():
        try:
            rows=RADAR.snapshot(20); top=rows[0]["symbol"] if rows else "NONE"; print(f"RADAR_RANKING_READY count={len(rows)} top={top}",flush=True)
        except Exception as exc: print(f"RADAR_RANKING_ERROR {str(exc)[:300]}",flush=True)
    threading.Thread(target=_check,daemon=True,name="radar-boot-check").start()

_boot_radar_check()
