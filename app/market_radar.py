from __future__ import annotations
import json, math, threading, time
from collections import defaultdict, deque
from statistics import median, pstdev
from typing import Any
import websocket

STABLE_BASES={"USDT","USDC","FDUSD","USDE","TUSD","DAI","USD1","USDS","EUR"}
MIN_24H_QUOTE=50_000.0
TOP150=150; STAGE1=80; STAGE2=40; STAGE3=25; FINAL=15

class MarketRadar:
 def __init__(self,top_n:int=FINAL):
  self.top_n=top_n; self.lock=threading.RLock(); self.tickers={}; self.bars=defaultdict(lambda:deque(maxlen=20)); self.pulses=defaultdict(lambda:deque(maxlen=90)); self._ws=None; self._stop=threading.Event(); self._thread=None; self._ready=threading.Event(); self.connected=False; self.last_error=None; self.last_update=0.0; self.message_count=0; self.stage_counts={"universe":0,"top150":0,"stage1":0,"stage2":0,"stage3":0,"top15":0}; self.last_snapshot=0.0
 def start(self):
  if self._thread and self._thread.is_alive(): return
  self._stop.clear(); self._thread=threading.Thread(target=self._run,daemon=True,name="fast-scalper-market-radar"); self._thread.start()
 def stop(self):
  self._stop.set(); self.connected=False
  if self._ws:
   try:self._ws.close()
   except Exception:pass
 def status(self):
  with self.lock:return {"connected":self.connected,"ready":self._ready.is_set(),"ticker_count":len(self.tickers),"last_update":self.last_update,"seconds_since_update":round(time.time()-self.last_update,1) if self.last_update else None,"message_count":self.message_count,"last_error":self.last_error,"data_source":"Binance public WebSocket","rest_polling":False,"stage_counts":dict(self.stage_counts)}
 def _build_url(self,symbols=None):
  streams=["!miniTicker@arr"]
  if symbols:
   streams += [f"{s.lower()}@kline_1m" for s in symbols]; streams += [f"{s.lower()}@aggTrade" for s in symbols]
  return "wss://stream.binance.com:443/stream?streams="+"/".join(streams)
 def _top_symbols(self):
  with self.lock: rows=[(s,float(d.get("q",0) or 0)) for s,d in self.tickers.items() if s.endswith("USDT") and s[:-4] not in STABLE_BASES and float(d.get("q",0) or 0)>=MIN_24H_QUOTE]
  rows.sort(key=lambda x:x[1],reverse=True); return [s for s,_ in rows[:TOP150]]
 def _run(self):
  while not self._stop.is_set():
   try:
    symbols=self._top_symbols(); url=self._build_url(symbols if len(symbols)>=50 else None)
    self._ws=websocket.WebSocketApp(url,on_open=self._on_open,on_message=self._on_message,on_error=self._on_error,on_close=self._on_close)
    self._ws.run_forever(ping_interval=15,ping_timeout=10)
   except Exception as exc:
    self.connected=False; self.last_error=f"{type(exc).__name__}: {exc}"[:300]
   if not self._stop.is_set():time.sleep(1.0)
 def _on_open(self,_ws):self.connected=True;self.last_error=None;print("RADAR_WS_CONNECTED",flush=True)
 def _on_close(self,_ws,code=None,msg=None):
  self.connected=False
  if code:self.last_error=f"WebSocket closed: {code} {msg or ''}".strip()
 def _on_error(self,_ws,error):self.connected=False;self.last_error=str(error)[:300];print(f"RADAR_WS_ERROR {self.last_error}",flush=True)
 def _on_message(self,_ws,raw):
  try:
   msg=json.loads(raw); data=msg.get("data",msg)
   with self.lock:self.message_count+=1
   if isinstance(data,list):
    for row in data:
     if isinstance(row,dict):self._mini(row)
    return
   if not isinstance(data,dict):return
   event=data.get("e")
   if event=="24hrMiniTicker":self._mini(data)
   elif event=="kline":self._kline(data)
   elif event=="aggTrade":self._trade(data)
  except Exception as exc:self.last_error=f"message: {exc}"[:300]
 def _mini(self,d):
  s=str(d.get("s","")).upper()
  if not s:return
  with self.lock:
   self.tickers[s]=dict(d); self.last_update=time.time()
   if s.endswith("USDT") and s[:-4] not in STABLE_BASES:self._ready.set()
 def _kline(self,d):
  k=d.get("k",{}); s=str(k.get("s","")).upper()
  if not s:return
  try:r={"ts":float(k.get("t",0))/1000,"open":float(k.get("o",0) or 0),"high":float(k.get("h",0) or 0),"low":float(k.get("l",0) or 0),"close":float(k.get("c",0) or 0),"quote_volume":float(k.get("q",0) or 0)}
  except (TypeError,ValueError):return
  with self.lock:
   b=self.bars[s]
   if b and b[-1]["ts"]==r["ts"]:b[-1]=r
   else:b.append(r)
 def _trade(self,d):
  s=str(d.get("s","")).upper()
  try:p=float(d.get("p",0) or 0);q=float(d.get("q",0) or 0)
  except (TypeError,ValueError):return
  if not s or p<=0 or q<=0:return
  sec=int(time.time()); quote=p*q
  with self.lock:
   h=self.pulses[s]
   if h and h[-1]["sec"]==sec:b=h[-1]
   else:b={"sec":sec,"price":p,"quote":0.0,"buy_quote":0.0,"trades":0};h.append(b)
   b["price"]=p;b["quote"]+=quote;b["buy_quote"]+=quote if not bool(d.get("m",False)) else 0.0;b["trades"]+=1
 def _change(self,bars,n):
  if len(bars)<=n or bars[-1]["close"]<=0 or bars[-1-n]["open"]<=0:return 0.0
  return (bars[-1]["close"]/bars[-1-n]["open"]-1)*100
 def _metrics(self,symbol,price):
  with self.lock:bars=list(self.bars.get(symbol,()));pulse=list(self.pulses.get(symbol,()))
  m1=self._change(bars,1);m2=self._change(bars,2);m4=self._change(bars,4);ranges=[];vols=[]
  for b in bars[-8:]:
   if b["close"]>0:ranges.append((b["high"]-b["low"])/b["close"]*100)
   vols.append(max(0,b["quote_volume"]))
  risk=pstdev(ranges) if len(ranges)>=3 else (ranges[-1] if ranges else 0.0); base=median(vols[:-1]) if len(vols)>=3 else 0.0;vr=vols[-1]/base if base>0 else 1.0
  p30=0.0; pvol=0.0;br=0.5
  if pulse:
   latest=pulse[-1]; idx=max(0,len(pulse)-31)
   if pulse[idx]["price"]>0:p30=(latest["price"]/pulse[idx]["price"]-1)*100
   pvol=sum(x["quote"] for x in pulse[-30:])/max(1,len(pulse[-30:]));br=latest["buy_quote"]/latest["quote"] if latest["quote"]>0 else .5
  return {"change_1m_pct":m1,"change_2m_pct":m2,"change_4m_pct":m4,"risk_pct":risk,"volume_ratio":vr,"change_30s_pct":p30,"pulse_volume":pvol,"buy_ratio":br}
 def _pulse_score(self,m):
  return min(1,max(0,.35*min(1,max(0,m["change_30s_pct"])/.20)+.30*min(1,max(0,m["change_1m_pct"])/.40)+.20*min(1,max(0,m["volume_ratio"]-1)/3)+.15*min(1,max(0,(m["buy_ratio"]-.5)/.30))))
 def _score(self,t,m):
  q=max(1,float(t.get("q",0) or 0));liq=min(1,max(0,math.log10(q)/9));mom=min(1,max(0,(.45*m["change_1m_pct"]+.35*m["change_2m_pct"]+.20*m["change_4m_pct"])/1.2));act=min(1,max(0,m["volume_ratio"]-1)/3);pulse=self._pulse_score(m);pen=min(.45,max(0,m["risk_pct"])/4);raw=.30*liq+.28*mom+.22*act+.20*pulse;return max(0,min(100,100*raw*(1-pen)))
 def snapshot(self,limit=FINAL):
  self.start()
  if not self._ready.wait(timeout=8):return []
  with self.lock:items=[(s,d) for s,d in self.tickers.items() if s.endswith("USDT") and s[:-4] not in STABLE_BASES]
  items.sort(key=lambda x:float(x[1].get("q",0) or 0),reverse=True);top150=items[:TOP150]
  self.stage_counts["universe"]=len(items);self.stage_counts["top150"]=len(top150);rows=[]
  for s,d in top150:
   try:p=float(d.get("c",0) or 0);q=float(d.get("q",0) or 0)
   except (TypeError,ValueError):continue
   if p<=0 or q<MIN_24H_QUOTE:continue
   m=self._metrics(s,p);score=self._score(d,m)
   if q<1_000_000:continue
   if m["risk_pct"]>2.5 and m["change_1m_pct"]<.5:continue
   rows.append((s,d,m,score))
  rows.sort(key=lambda x:(x[3],float(x[1].get("q",0) or 0)),reverse=True);s1=rows[:STAGE1];self.stage_counts["stage1"]=len(s1)
  s1=[x for x in s1 if x[2]["volume_ratio"]>=.8 or x[2]["change_1m_pct"]>.08];s2=s1[:STAGE2];self.stage_counts["stage2"]=len(s2)
  s2=[x for x in s2 if x[2]["change_2m_pct"]>-.35 and x[2]["change_4m_pct"]>-.80];s3=s2[:STAGE3];self.stage_counts["stage3"]=len(s3);s3.sort(key=lambda x:x[3],reverse=True);final=s3[:FINAL];self.stage_counts["top15"]=len(final)
  out=[]
  for s,d,m,score in final:
   p=float(d.get("c",0) or 0);sig="BUY" if m["change_1m_pct"]>0 and m["change_2m_pct"]>0 else ("WATCH" if m["change_1m_pct"]>0 else "WAIT");target=min(.012,max(.0035,abs(m["change_2m_pct"])/100*.8))
   out.append({"symbol":s[:-4]+"/USDT","price":p,"change_24h_pct":round((p/float(d.get("o",p) or p)-1)*100,3),"quote_volume_24h":float(d.get("q",0) or 0),"score":round(score,2),"signal":sig,"estimated_entry":p,"estimated_exit":p*(1+target),"estimated_stop":p*(1-.004),"change_3m_pct":round((m["change_2m_pct"]+m["change_1m_pct"])/2,4),"volume_ratio":round(m["volume_ratio"],2),"pump_events":0,"pump_score":round(self._pulse_score(m),3),"hold_seconds":180})
  self.last_snapshot=time.time();return out[:max(1,int(limit))]
 def price(self,symbol):
  s=symbol.upper().replace('/','')
  with self.lock:
   d=self.tickers.get(s)
   try:return float(d.get("c",0) or 0) if d else 0.0
   except (TypeError,ValueError):return 0.0
RADAR=MarketRadar(FINAL)
