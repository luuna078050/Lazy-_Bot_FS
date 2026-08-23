"""Small-capital real/paper runner for LazyBot FS.
Default is PAPER. LIVE requires two explicit env flags. Spot only, no leverage,
no withdrawals. Radar: top 10 from a liquid universe; five fixed capital slots
10/10/20/20/30%, leaving 10% reserve. Entry requires MTF + order-book confirmation;
exits use TP/SL plus confirmed reversal, while a temporary red position is not
closed merely because its PnL is negative.
"""
from __future__ import annotations
import json,os,time
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from app.strategy_intelligence import evaluate
from app.orderbook_pressure import analyze_orderbook
from app.exchange_gateway import gateway
load_dotenv()
QUOTE=os.getenv("QUOTE_CURRENCY","USDT").upper();CAPITAL=float(os.getenv("TEST_CAPITAL_USDT","20"));SCAN_LIMIT=int(os.getenv("SCAN_UNIVERSE","30"));RADAR_LIMIT=int(os.getenv("RADAR_LIMIT","10"));MAX_POSITIONS=min(5,int(os.getenv("MAX_POSITIONS","5")));SLOT_PCTS=[10,10,20,20,30];TP=float(os.getenv("TAKE_PROFIT_PCT","0.6"))/100;SL=float(os.getenv("STOP_LOSS_PCT","0.3"))/100;MIN_SCORE=float(os.getenv("ENTRY_SCORE","0.30"));POLL=int(os.getenv("POLL_SECONDS","20"));STATE=Path(os.getenv("SCALPER_STATE","scalper_state.json"))

def _live()->bool:return os.getenv("TRADING_MODE","paper").lower()=="live" and os.getenv("LIVE_TRADING","false").lower()=="true" and os.getenv("LIVE_TRADING_ARMED","false").lower()=="true"
def _load_state()->dict[str,Any]:
    if STATE.exists():
        try:return json.loads(STATE.read_text())
        except Exception:pass
    return {"positions":{},"realized_pnl":0.0,"day":time.strftime("%Y-%m-%d"),"trades":[]}
def _save_state(s):STATE.write_text(json.dumps(s,indent=2,ensure_ascii=False))
def _series(ex,symbol,tf,limit=160):
    rows=ex.exchange.fetch_ohlcv(symbol,timeframe=tf,limit=limit)
    return {"close":[float(x[4]) for x in rows],"high":[float(x[2]) for x in rows],"low":[float(x[3]) for x in rows],"volume":[float(x[5]) for x in rows]}
def _tf_data(ex,symbol):
    out={tf:_series(ex,symbol,tf) for tf in ("1m","3m","5m","15m","30m","1h","4h")};h=_series(ex,symbol,"1h",limit=320);n=len(h["close"])-len(h["close"])%2
    out["2h"]={k:[sum(v[i:i+2])/2 if k=="close" else max(v[i:i+2]) if k=="high" else min(v[i:i+2]) if k=="low" else sum(v[i:i+2]) for i in range(0,n,2)] for k,v in h.items()};return out
def _universe(ex):
    markets=ex.load_markets();tickers=ex.exchange.fetch_tickers();rows=[]
    for symbol,t in tickers.items():
        m=markets.get(symbol,{})
        if not m.get("spot") or not m.get("active",True) or m.get("quote")!=QUOTE:continue
        if m.get("base") in {"USDT","USDC","FDUSD","TUSD","BUSD","DAI"}:continue
        qv=float(t.get("quoteVolume") or 0);price=float(t.get("last") or 0)
        if qv>0 and price>0:rows.append((qv,symbol))
    rows.sort(reverse=True);return [s for _,s in rows[:SCAN_LIMIT]]
def _allocation(score,free_slots):
    preferred=30 if score>=.55 else 20 if score>=.40 else 10
    return next((p for p in sorted(free_slots,reverse=True) if p<=preferred),None)

def run_once(ex,state):
    if state.get("day")!=time.strftime("%Y-%m-%d"):state["day"]=time.strftime("%Y-%m-%d");state["realized_pnl"]=0.0;state["trades"]=[]
    if state["realized_pnl"]<=-float(os.getenv("DAILY_LOSS_LIMIT_USDT","3")):return {"halt":"daily_loss_limit"}
    ranked=[]
    for symbol in _universe(ex):
        try:
            data=_tf_data(ex,symbol);book=ex.exchange.fetch_order_book(symbol,limit=50);ob=analyze_orderbook(symbol,book);a=evaluate(data,{"score":ob["score"],"spoof_risk":ob["spoof_risk"],"pressure_velocity":ob["pressure_velocity"]},None,0.0);ranked.append((float(a["score"]),symbol,a))
        except Exception:continue
    ranked.sort(reverse=True,key=lambda x:x[0]);radar=ranked[:RADAR_LIMIT];rank_map={s:(sc,a) for sc,s,a in ranked}
    now={s:{"score":round(sc,4),"direction":a["direction"],"regime":a["regime"]["regime"],"ob":a["orderbook_score"],"structure":a["timeframes"].get("3m",{}).get("structure",{}).get("score",0)} for sc,s,a in radar}
    for symbol,pos in list(state["positions"].items()):
        try:
            last=float(ex.exchange.fetch_ticker(symbol)["last"]);entry=float(pos["entry"]);pnl=(last/entry-1)*100;sc,a=rank_map.get(symbol,(0.0,{}));confirmed_reversal=sc<-.35 and a.get("direction")=="bearish"
            reason="tp_sl" if last>=entry*(1+TP) or last<=entry*(1-SL) else "confirmed_reversal" if confirmed_reversal and pnl>=0 else None
            if reason:
                amount=float(pos["amount"]);res=ex.create_market_order(symbol,"sell",amount,live=_live());state["realized_pnl"]+=amount*entry*(pnl/100);state["trades"].append({"ts":time.time(),"symbol":symbol,"exit":last,"pnl_pct":pnl,"reason":reason,"order":res});del state["positions"][symbol]
            else:pos.update({"last":last,"pnl_pct":pnl,"score":sc})
        except Exception:continue
    used=set(state["positions"]);used_pcts={int(p.get("allocation_pct",0)) for p in state["positions"].values()};free_slots=[p for p in SLOT_PCTS if p not in used_pcts];free=max(0,min(MAX_POSITIONS-len(used),len(free_slots)))
    for score,symbol,a in radar:
        if free<=0 or symbol in used or score<MIN_SCORE or a["direction"]!="bullish":continue
        regime=a["regime"]["regime"];structure=a["timeframes"].get("3m",{}).get("structure",{});ob=float(a["orderbook_score"])
        if regime=="bear" or ob<0 or (regime=="flat" and float(structure.get("score",0))<.40):continue
        allocation=_allocation(score,free_slots)
        if allocation is None:continue
        budget=CAPITAL*allocation/100;price=float(ex.exchange.fetch_ticker(symbol)["last"]);amount=ex.amount_to_precision(symbol,budget/price)
        if amount<=0:continue
        try:
            res=ex.create_market_order(symbol,"buy",amount,live=_live());state["positions"][symbol]={"entry":price,"amount":amount,"allocation_pct":allocation,"score":score,"opened":time.time()};used.add(symbol);free_slots.remove(allocation);free-=1
        except Exception:continue
    _save_state(state);return {"live":_live(),"capital":CAPITAL,"radar":now,"positions":state["positions"],"realized_pnl":state["realized_pnl"]}
def main():
    ex=gateway(os.getenv("EXCHANGE","binance"));state=_load_state();print(f"LazyBot FS | {'LIVE' if _live() else 'PAPER'} | capital={CAPITAL} {QUOTE}")
    while True:
        try:print(json.dumps(run_once(ex,state),ensure_ascii=False,default=str))
        except KeyboardInterrupt:break
        except Exception as exc:print(json.dumps({"error":str(exc)}))
        time.sleep(POLL)
if __name__=="__main__":main()
