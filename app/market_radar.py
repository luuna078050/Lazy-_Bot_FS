from __future__ import annotations
import json, threading, time
from collections import defaultdict, deque
from statistics import median
import websocket

STABLE={"USDT","USDC","FDUSD","USDE","TUSD","DAI","USD1","USDS","EUR"}
FALLBACK=["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","TRXUSDT"]
TF_ANALYSIS=("1m","3m","5m","15m","30m")

class MarketRadar:
    def __init__(self, top_n=8):
        self.top_n=8; self.lock=threading.RLock(); self.tickers={}; self.quotes={}
        self.bars=defaultdict(lambda:defaultdict(lambda:deque(maxlen=240))); self.pulses=defaultdict(lambda:deque(maxlen=120))
        self.depth=defaultdict(lambda:{"bids":[],"asks":[]}); self.wall_history=defaultdict(lambda:deque(maxlen=1800))
        self.last_update=0.0; self.connected=False; self.last_error=None; self.message_count=0
        self._ws=None; self._thread=None; self._stop=threading.Event(); self._ready=threading.Event(); self._rank_cache=[]; self._rank_at=0.0; self._stream_symbols=()
    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear(); self._thread=threading.Thread(target=self._run,daemon=True,name="fast-scalper-radar"); self._thread.start()
    def stop(self):
        self._stop.set(); self.connected=False
        if self._ws:
            try:self._ws.close()
            except Exception:pass
    def status(self):
        with self.lock:
            return {"connected":self.connected,"ready":self._ready.is_set(),"ticker_count":len(self.tickers),"quote_count":len(self.quotes),"last_update":self.last_update,"seconds_since_update":round(time.time()-self.last_update,1) if self.last_update else None,"message_count":self.message_count,"last_error":self.last_error,"data_source":"Binance public WebSocket","rest_polling":False,"deep_symbols":list(self._stream_symbols)}
    def _top_symbols(self):
        with self.lock:
            rows=[]
            for s,d in self.tickers.items():
                if not s.endswith("USDT") or s[:-4] in STABLE: continue
                q=float(d.get("q",0) or 0)
                if q<10000: continue
                ch=(float(d.get("c",0) or 0)/float(d.get("o",1) or 1)-1)*100
                rows.append((s,ch,q))
        rows.sort(key=lambda x:(x[1]>0,x[1],x[2]),reverse=True); return [x[0] for x in rows[:8]] or FALLBACK
    def _build_url(self):
        syms=self._top_symbols(); self._stream_symbols=tuple(syms)
        streams=["!miniTicker@arr"]+[f"{s.lower()}@bookTicker" for s in syms]+[f"{s.lower()}@depth20@100ms" for s in syms]+[f"{s.lower()}@kline_{tf}" for s in syms for tf in TF_ANALYSIS]
        return "wss://stream.binance.com:443/stream?streams="+"/".join(streams)
    def _run(self):
        while not self._stop.is_set():
            try:
                self._ws=websocket.WebSocketApp(self._build_url(),on_open=self._on_open,on_message=self._on_message,on_error=self._on_error,on_close=self._on_close); self._ws.run_forever(ping_interval=20,ping_timeout=10)
            except Exception as e:self.last_error=str(e)[:300]; self.connected=False
            if not self._stop.is_set(): time.sleep(2)
    def _on_open(self,_): self.connected=True; self.last_error=None
    def _on_close(self,_,code=None,msg=None): self.connected=False
    def _on_error(self,_,e): self.connected=False; self.last_error=str(e)[:300]
    def _on_message(self,_,raw):
        try:
            d=json.loads(raw).get("data",{}); self.message_count+=1
            if isinstance(d,list):
                for x in d:self._mini(x)
            elif d.get("e")=="24hrMiniTicker":self._mini(d)
            elif d.get("e")=="bookTicker":self._book(d)
            elif d.get("e")=="kline":self._kline(d)
            elif d.get("e")=="aggTrade":self._trade(d)
            elif d.get("e")=="depthUpdate":self._depth(d)
        except Exception as e:self.last_error=str(e)[:300]
    def _mini(self,d):
        s=str(d.get("s","")).upper()
        if not s:return
        with self.lock:self.tickers[s]=dict(d); self.last_update=time.time(); self._ready.set()
    def _book(self,d):
        s=str(d.get("s","")).upper()
        if not s:return
        with self.lock:self.quotes[s]={"bid":float(d.get("b",0) or 0),"bid_qty":float(d.get("B",0) or 0),"ask":float(d.get("a",0) or 0),"ask_qty":float(d.get("A",0) or 0),"ts":time.time()}
    def _kline(self,d):
        k=d.get("k",{}); s=str(k.get("s","")).upper(); tf=str(k.get("i",""))
        if not s or tf not in TF_ANALYSIS:return
        r={"ts":float(k.get("t",0))/1000,"open":float(k.get("o",0) or 0),"high":float(k.get("h",0) or 0),"low":float(k.get("l",0) or 0),"close":float(k.get("c",0) or 0),"quote_volume":float(k.get("q",0) or 0),"closed":bool(k.get("x"))}
        with self.lock:
            q=self.bars[s][tf]
            if q and q[-1]["ts"]==r["ts"]:q[-1]=r
            else:q.append(r)
    def _trade(self,d):
        s=str(d.get("s","")).upper(); p=float(d.get("p",0) or 0); q=float(d.get("q",0) or 0)
        if not s or p<=0:return
        sec=int(time.time()); quote=p*q; buy=not bool(d.get("m",False))
        with self.lock:
            h=self.pulses[s]; b=h[-1] if h and h[-1]["sec"]==sec else {"sec":sec,"price":p,"quote":0.0,"buy_quote":0.0,"trades":0}
            if not h or b is not h[-1]:h.append(b)
            b["price"]=p; b["quote"]+=quote; b["buy_quote"]+=quote if buy else 0; b["trades"]+=1
    def _depth(self,d):
        s=str(d.get("s","")).upper()
        if not s:return
        with self.lock:self.depth[s]={"bids":d.get("b",[]),"asks":d.get("a",[])}; self._record_wall(s)
    def _record_wall(self,s):
        book=self.depth[s]; b=book["bids"]; a=book["asks"]
        if not b or not a:return
        try:
            now=time.time()
            if self.wall_history[s] and now-self.wall_history[s][-1]["ts"]<1:return
            bids=[(float(x[0]),float(x[1])) for x in b if float(x[1])>0]; asks=[(float(x[0]),float(x[1])) for x in a if float(x[1])>0]
            if not bids or not asks:return
            bp,bq=max(bids,key=lambda x:x[1]); ap,aq=max(asks,key=lambda x:x[1]); self.wall_history[s].append({"ts":now,"mid":(bp+ap)/2,"bid_price":bp,"bid_quote":bp*bq,"ask_price":ap,"ask_quote":ap*aq})
        except Exception:pass
    def _tf(self,s,price):
        out={}
        for tf in TF_ANALYSIS:
            with self.lock:bars=list(self.bars[s][tf])
            if not bars:out[tf]={"change_pct":0.0,"volume_ratio":1.0,"trend":0}
            else:
                base=float(bars[0]["open"] or price); ch=(price/base-1)*100 if base else 0; vols=[x["quote_volume"] for x in bars[:-1] if x["quote_volume"]>0]; vr=float(bars[-1]["quote_volume"] or 0)/(median(vols[-20:]) if vols else 1); out[tf]={"change_pct":round(ch,4),"volume_ratio":round(vr,2),"trend":1 if ch>0 else -1 if ch<0 else 0}
        return out
    def _pulse(self,s):
        with self.lock:h=list(self.pulses[s])
        if not h:return {"pump_score":0.0,"buy_ratio":.5,"trade_velocity":0.0,"freeze_risk":.7,"hold_seconds":180}
        p=[x["price"] for x in h]; c3=(p[-1]/p[-4]-1)*100 if len(p)>3 and p[-4]>0 else 0; last=h[-60:]; buy=sum(x["buy_quote"] for x in last); q=sum(x["quote"] for x in last); br=buy/q if q else .5; tv=sum(x["trades"] for x in last); ps=min(1,.5*max(0,min(1,c3/.3))+.5*max(0,min(1,(br-.5)/.2)))
        return {"pump_score":round(ps,3),"buy_ratio":round(br,4),"trade_velocity":round(tv/6,2),"freeze_risk":.25 if tv>20 else .7,"hold_seconds":20 if ps>=.65 and c3>=.08 else 180}
    def _wall(self,s):
        with self.lock:h=list(self.wall_history[s])
        if not h:return {"direction":"neutral","score":0.0,"spoof_risk":0.0}
        x=h[-1]; imb=(x["bid_quote"]-x["ask_quote"])/(x["bid_quote"]+x["ask_quote"]) if x["bid_quote"]+x["ask_quote"] else 0; score=max(-1,min(1,imb)); direction="bullish" if score>.12 else "bearish" if score<-.12 else "neutral"; return {"direction":direction,"score":round(score,4),"bid_wall":x["bid_price"],"ask_wall":x["ask_price"],"spoof_risk":0.0}
    def analyze(self,symbol):
        s=symbol.upper().replace("/","")
        with self.lock:d=dict(self.tickers.get(s) or {}); q=dict(self.quotes.get(s) or {})
        price=float(d.get("c",0) or q.get("ask",0) or q.get("bid",0) or 0)
        if price<=0:return None
        matrix=self._tf(s,price); wall=self._wall(s); pulse=self._pulse(s); score=50+sum(7 if matrix[x]["trend"]>0 else -4 if matrix[x]["trend"]<0 else 0 for x in TF_ANALYSIS)+wall["score"]*22+pulse["pump_score"]*10; score=max(0,min(100,score)); direction="LONG" if score>=52 and wall["direction"]!="bearish" else "WAIT"
        return {"symbol":s[:-4]+"/USDT","price":price,"bid":q.get("bid",price),"ask":q.get("ask",price),"score":round(score,2),"direction":direction,"tf":{k:matrix[k] for k in ("1m","3m","5m")},"matrix":matrix,"wall":wall,"pulse":pulse,"change_24h_pct":round((price/float(d.get("o",price) or price)-1)*100,3)}
    def snapshot(self,limit=15,force=False):
        self.start(); now=time.time()
        if not force and self._rank_cache and now-self._rank_at<5:return self._rank_cache[:limit]
        if not self._ready.wait(timeout=5):return self._rank_cache[:limit]
        rows=[self.analyze(s) for s in self._top_symbols()]; rows=[x for x in rows if x]; rows.sort(key=lambda x:(x["score"],x["change_24h_pct"]),reverse=True); self._rank_cache=rows; self._rank_at=now; return rows[:limit]
    def symbol_analysis(self,symbol):return self.analyze(symbol)

RADAR=MarketRadar(8)
RADAR.start()
