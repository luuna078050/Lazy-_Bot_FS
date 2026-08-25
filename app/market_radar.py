from __future__ import annotations
import json, math, threading, time
from collections import defaultdict, deque
from statistics import median
from typing import Any
import websocket

STABLE_BASES={"USDT","USDC","FDUSD","USDE","TUSD","DAI","USD1","USDS","EUR"}
FALLBACK=["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","TRXUSDT","LINKUSDT","AVAXUSDT","SUIUSDT","TONUSDT","LTCUSDT","DOTUSDT","BCHUSDT","NEARUSDT","APTUSDT","ATOMUSDT","UNIUSDT","FILUSDT"]
TF=("1m","3m","5m","15m","30m")

class MarketRadar:
    def __init__(self,top_n=20):
        self.top_n=max(10,min(int(top_n),20)); self.lock=threading.RLock(); self.tickers={}
        self.bars=defaultdict(lambda:defaultdict(lambda:deque(maxlen=240))); self.pulses=defaultdict(lambda:deque(maxlen=180))
        self.depth=defaultdict(lambda:{"bids":[],"asks":[]}); self.wall_history=defaultdict(lambda:deque(maxlen=180))
        self._ws=None; self._stop=threading.Event(); self._thread=None; self._ready=threading.Event()
        self.last_error=None; self.last_update=0.; self.connected=False; self.connection_url=""; self.message_count=0
        self._rank_cache=[]; self._rank_at=0.; self._rank_lock=threading.RLock()

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear(); self._thread=threading.Thread(target=self._run,daemon=True,name="fast-scalper-radar"); self._thread.start()

    def stop(self):
        self._stop.set(); self.connected=False
        if self._ws:
            try:self._ws.close()
            except Exception:pass

    def status(self):
        with self.lock:return {"connected":self.connected,"ready":self._ready.is_set(),"ticker_count":len(self.tickers),"last_update":self.last_update,"seconds_since_update":round(time.time()-self.last_update,1) if self.last_update else None,"message_count":self.message_count,"last_error":self.last_error,"data_source":"Binance public WebSocket","rest_polling":False,"ranking_age":round(time.time()-self._rank_at,1) if self._rank_at else None}

    def _top_symbols(self):
        with self.lock: rows=[(s,d) for s,d in self.tickers.items() if s.endswith("USDT") and s[:-4] not in STABLE_BASES and float(d.get("q",0) or 0)>=10000]
        rows.sort(key=lambda x:float(x[1].get("q",0) or 0),reverse=True); return [s for s,_ in rows[:self.top_n]] or FALLBACK[:self.top_n]

    def _build_url(self):
        ss=self._top_symbols(); streams=["!miniTicker@arr"]
        streams += [f"{s.lower()}@kline_{tf}" for s in ss for tf in TF]
        streams += [f"{s.lower()}@aggTrade" for s in ss]
        streams += [f"{s.lower()}@depth20@100ms" for s in ss]
        return "wss://stream.binance.com:443/stream?streams="+"/".join(streams)

    def _run(self):
        while not self._stop.is_set():
            self.connection_url=self._build_url()
            try:
                self._ws=websocket.WebSocketApp(self.connection_url,on_open=self._on_open,on_message=self._on_message,on_error=self._on_error,on_close=self._on_close); self._ws.run_forever(ping_interval=15,ping_timeout=10)
            except Exception as e:self.last_error=str(e)[:300]; self.connected=False
            if not self._stop.is_set():time.sleep(1)

    def _on_open(self,_):self.connected=True;self.last_error=None
    def _on_close(self,_,code=None,msg=None):self.connected=False
    def _on_error(self,_,e):self.connected=False;self.last_error=str(e)[:300]

    def _on_message(self,_,raw):
        try:
            d=json.loads(raw).get("data",{}); self.message_count+=1
            if isinstance(d,list):
                for x in d:self._mini(x)
            elif d.get("e")=="24hrMiniTicker":self._mini(d)
            elif d.get("e")=="kline":self._kline(d)
            elif d.get("e")=="aggTrade":self._trade(d)
            elif d.get("e")=="depthUpdate":self._depth(d)
        except Exception as e:self.last_error=str(e)[:300]

    def _mini(self,d):
        s=str(d.get("s","")).upper()
        if not s:return
        with self.lock:self.tickers[s]=dict(d);self.last_update=time.time();self._ready.set()

    def _kline(self,d):
        k=d.get("k",{});s=str(k.get("s","")).upper();tf=str(k.get("i","3m"))
        if not s or tf not in TF:return
        r={"ts":float(k.get("t",0))/1000,"open":float(k.get("o",0) or 0),"high":float(k.get("h",0) or 0),"low":float(k.get("l",0) or 0),"close":float(k.get("c",0) or 0),"quote_volume":float(k.get("q",0) or 0),"closed":bool(k.get("x"))}
        with self.lock:
            q=self.bars[s][tf]
            if q and q[-1]["ts"]==r["ts"]:q[-1]=r
            else:q.append(r)

    def _trade(self,d):
        s=str(d.get("s","")).upper();p=float(d.get("p",0) or 0);q=float(d.get("q",0) or 0)
        if not s or p<=0:return
        sec=int(time.time()); quote=p*q; buy=not bool(d.get("m",False))
        with self.lock:
            h=self.pulses[s]; b=h[-1] if h and h[-1]["sec"]==sec else {"sec":sec,"price":p,"quote":0.,"buy_quote":0.,"trades":0}
            if not h or b is not h[-1]:h.append(b)
            b["price"]=p;b["quote"]+=quote;b["buy_quote"]+=quote if buy else 0;b["trades"]+=1

    def _depth(self,d):
        s=str(d.get("s","")).upper()
        if not s:return
        with self.lock:self.depth[s]={"bids":d.get("b",[]),"asks":d.get("a",[])};self._record_walls(s)

    def _record_walls(self,s):
        book=self.depth[s];b=book["bids"];a=book["asks"]
        if not b or not a:return
        try:
            bid=max((float(x[0]),float(x[1])) for x in b if float(x[1])>0);ask=min((float(x[0]),float(x[1])) for x in a if float(x[1])>0);mid=(bid[0]+ask[0])/2
            def wall(levels):
                vals=[(float(x[0]),float(x[1])) for x in levels if float(x[1])>0]; med=median([x[1] for x in vals]) if vals else 0; cand=max(vals,key=lambda x:x[1]) if vals else (0,0); return cand[0],cand[1],(cand[1]/med if med else 1)
            bp,bq,br=wall(b);ap,aq,ar=wall(a);h=self.wall_history[s];h.append({"ts":time.time(),"mid":mid,"bid_price":bp,"bid_quote":bp*bq,"bid_ratio":br,"ask_price":ap,"ask_quote":ap*aq,"ask_ratio":ar})
        except Exception:pass

    @staticmethod
    def _clamp(v,a=0.,b=1.):return min(b,max(a,float(v)))

    def _tf(self,s,price):
        out={}
        for tf in TF:
            with self.lock:bars=list(self.bars[s][tf])
            if not bars:out[tf]={"change_pct":0.,"volume_ratio":1.,"trend":0.}
            else:
                base=float(bars[0]["open"] or price);ch=(price/base-1)*100 if base else 0;vols=[float(x["quote_volume"]) for x in bars[:-1] if x["quote_volume"]>0];vr=float(bars[-1]["quote_volume"] or 0)/(median(vols[-20:]) if vols else 1);out[tf]={"change_pct":round(ch,4),"volume_ratio":round(vr,2),"trend":1 if ch>0 else -1 if ch<0 else 0}
        return out

    def wall(self,s,price):
        with self.lock:h=list(self.wall_history[s])[-60:]
        if not h:return {"direction":"neutral","score":0.,"bid_wall":None,"ask_wall":None,"bid_shift_pct":0.,"ask_shift_pct":0.,"persistence":0.,"velocity":0.,"spoof_risk":0.}
        first,last=h[0],h[-1];bs=(last["bid_price"]/first["bid_price"]-1)*100 if first["bid_price"] else 0;as_=(last["ask_price"]/first["ask_price"]-1)*100 if first["ask_price"] else 0;bid=last["bid_quote"];ask=last["ask_quote"];imb=(bid-ask)/(bid+ask) if bid+ask else 0;score=max(-1,min(1,imb*.65+(bs-as_)*.35));direction="bullish" if score>.12 else "bearish" if score<-.12 else "neutral";spoof=min(1.,sum(1 for i in range(1,len(h)) if abs(h[i]["bid_quote"]-h[i-1]["bid_quote"])/(h[i]["bid_quote"] or 1)>.5)/max(1,len(h)-1));return {"direction":direction,"score":round(score,4),"bid_wall":last["bid_price"],"ask_wall":last["ask_price"],"bid_shift_pct":round(bs,4),"ask_shift_pct":round(as_,4),"persistence":round(min(1,len(h)/60),3),"velocity":round(((last["bid_price"]-first["bid_price"])-(last["ask_price"]-first["ask_price"]))/(price or 1),6),"spoof_risk":round(spoof,3)}

    def _pulse(self,s):
        with self.lock:h=list(self.pulses[s])
        if not h:return {"buy_ratio":.5,"trade_velocity":0.,"pump_score":0.,"signal":"WAIT"}
        p=[x["price"] for x in h];latest=p[-1];c3=(latest/p[-4]-1)*100 if len(p)>3 and p[-4]>0 else 0;last=h[-60:];buy=sum(x["buy_quote"] for x in last);q=sum(x["quote"] for x in last);br=buy/q if q else .5;tv=sum(x["trades"] for x in last);ps=min(1.,.5*self._clamp(max(0,c3)/.3)+.5*self._clamp((br-.5)/.2));return {"buy_ratio":round(br,4),"trade_velocity":round(tv/6,2),"pump_score":round(ps,3),"signal":"PUMP_NOW" if ps>=.65 and c3>=.08 else "NORMAL"}

    def analyze(self,s):
        with self.lock:d=dict(self.tickers.get(s) or {})
        price=float(d.get("c",0) or 0)
        if price<=0:return None
        tf=self._tf(s,price);wall=self.wall(s,price);pulse=self._pulse(s);score=50.;score+=sum(8 if tf[x]["trend"]>0 else -5 if tf[x]["trend"]<0 else 0 for x in TF);score+=wall["score"]*22;score+=pulse["pump_score"]*12;score=max(0,min(100,score));ideal=.30/50*100;ideal*=max(.4,min(1.5,score/70));acceptable=ideal*.77;floor=ideal*.50;projected=max(0.,ideal*(1-wall["spoof_risk"]));direction="LONG" if score>=52 and wall["direction"]!="bearish" else "WAIT";return {"symbol":s[:-4]+"/USDT","price":price,"score":round(score,2),"direction":direction,"tf":tf,"wall":wall,"pulse":pulse,"ideal_pnl_per_min_100":round(ideal,4),"acceptable_pnl_per_min_100":round(acceptable,4),"floor_pnl_per_min_100":round(floor,4),"projected_pnl_per_min_100":round(projected,4),"change_24h_pct":round((price/float(d.get("o",price) or price)-1)*100,3)}

    def snapshot(self,limit=20,force=False):
        self.start();now=time.time()
        with self._rank_lock:
            if not force and self._rank_cache and now-self._rank_at<10:return self._rank_cache[:limit]
        if not self._ready.wait(timeout=8):return self._rank_cache[:limit]
        rows=[self.analyze(s) for s in self._top_symbols()];rows=[x for x in rows if x];rows.sort(key=lambda x:(x["score"],x["projected_pnl_per_min_100"]),reverse=True)
        with self._rank_lock:self._rank_cache=rows[:20];self._rank_at=now
        return rows[:limit]

    def symbol_analysis(self,symbol):return self.analyze(symbol.upper().replace("/",""))

RADAR=MarketRadar(20);RADAR.start()
