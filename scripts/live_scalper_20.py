"""LazyBot FS capital allocation and profit/time controller.

Capital is supplied by the user as the bot's account balance, separate from
exchange account balance. Automatic allocation is frozen during validation.
When enabled later, the strategy may dynamically size positions from signal
quality, with a hard automatic per-position cap of 40% of bot balance.

Profit targeting is expressed in money and time, not percentages:
- target profit per one unit of allocated capital;
- lower acceptable profit floor at the target interval;
- desired completed-trade interval;
- maximum holding time for a still-valid non-losing position.

The interval is a throughput target, not a forced-trade guarantee. The bot
uses multi-pair selection to increase turnover instead of entering weak trades
just to satisfy a clock.
"""
from __future__ import annotations
import json,os,time
from pathlib import Path
from dotenv import load_dotenv
from app.exit_policy import decide_exit
from app.profit_timing import ProfitTimeProfile, should_rotate, should_take_profit
from app.risk_settings import load_settings
from app.strategy_intelligence import evaluate
from app.orderbook_pressure import analyze_orderbook
from app.exchange_gateway import gateway
load_dotenv()
QUOTE=os.getenv("QUOTE_CURRENCY","USDT").upper();BOT_BALANCE=float(os.getenv("BOT_ACCOUNT_BALANCE",os.getenv("TEST_CAPITAL_USDT","20")));ACCOUNT_BALANCE_VIEW=float(os.getenv("ACCOUNT_BALANCE_VIEW","0"));SCAN_LIMIT=int(os.getenv("SCAN_UNIVERSE","30"));RADAR_LIMIT=int(os.getenv("RADAR_LIMIT","10"));MAX_POSITIONS=min(5,int(os.getenv("MAX_POSITIONS","5")))
AUTO_ALLOCATION_ENABLED=os.getenv("AUTO_ALLOCATION_ENABLED","false").lower()=="true";AUTO_ALLOCATION_MAX_PCT=min(40.0,float(os.getenv("AUTO_ALLOCATION_MAX_PCT","40")));VALIDATION_DAYS=int(os.getenv("ALLOCATION_VALIDATION_DAYS","14"));COMMERCIAL_MIN_EFFECTIVENESS=float(os.getenv("COMMERCIAL_MIN_EFFECTIVENESS","0.75"));PROFIT_SHARE=float(os.getenv("LAZY_PROFIT_SHARE","0.001"))
TP=float(os.getenv("TAKE_PROFIT_PCT","0.6"))/100;SL=float(os.getenv("STOP_LOSS_PCT","0.3"))/100;MIN_SCORE=float(os.getenv("ENTRY_SCORE","0.30"));POLL=int(os.getenv("POLL_SECONDS","20"));STATE=Path(os.getenv("SCALPER_STATE","scalper_state.json"))
PROFIT_TARGET_MODE=os.getenv("PROFIT_TARGET_MODE","money_time").lower();PROFIT_TARGET_PER_UNIT=float(os.getenv("PROFIT_TARGET_PER_UNIT","0.25"));PROFIT_FLOOR_PER_UNIT=float(os.getenv("PROFIT_FLOOR_PER_UNIT","0.20"));TARGET_TRADE_INTERVAL_SEC=int(os.getenv("TARGET_TRADE_INTERVAL_SEC","90"));MAX_TRADE_HOLD_SEC=int(os.getenv("MAX_TRADE_HOLD_SEC","180"));ESTIMATED_ROUND_TRIP_FEE_PCT=float(os.getenv("ESTIMATED_ROUND_TRIP_FEE_PCT","0"));PROFIT_PROFILE=ProfitTimeProfile(PROFIT_TARGET_PER_UNIT,PROFIT_FLOOR_PER_UNIT,TARGET_TRADE_INTERVAL_SEC,MAX_TRADE_HOLD_SEC,ESTIMATED_ROUND_TRIP_FEE_PCT/100)

def _live():return os.getenv("TRADING_MODE","paper").lower()=="live" and os.getenv("LIVE_TRADING","false").lower()=="true" and os.getenv("LIVE_TRADING_ARMED","false").lower()=="true"
def _load_state():
    if STATE.exists():
        try:return json.loads(STATE.read_text())
        except Exception:pass
    return {"positions":{},"realized_pnl":0.0,"day":time.strftime("%Y-%m-%d"),"trades":[],"allocation_validation_start":time.time(),"commercial_mode":False,"strategy_effectiveness":0.0}
def _save_state(s):STATE.write_text(json.dumps(s,indent=2,ensure_ascii=False))
def _series(ex,symbol,tf,limit=160):
    rows=ex.exchange.fetch_ohlcv(symbol,timeframe=tf,limit=limit);return {"close":[float(x[4]) for x in rows],"high":[float(x[2]) for x in rows],"low":[float(x[3]) for x in rows],"volume":[float(x[5]) for x in rows]}
def _tf_data(ex,symbol):
    out={tf:_series(ex,symbol,tf) for tf in ("1m","3m","5m","15m","30m","1h","4h")};h=_series(ex,symbol,"1h",limit=320);n=len(h["close"])-len(h["close"])%2;out["2h"]={k:[sum(v[i:i+2])/2 if k=="close" else max(v[i:i+2]) if k=="high" else min(v[i:i+2]) if k=="low" else sum(v[i:i+2]) for i in range(0,n,2)] for k,v in h.items()};return out
def _universe(ex):
    markets=ex.load_markets();tickers=ex.exchange.fetch_tickers();rows=[]
    for symbol,t in tickers.items():
        m=markets.get(symbol,{})
        if not m.get("spot") or not m.get("active",True) or m.get("quote")!=QUOTE:continue
        if m.get("base") in {"USDT","USDC","FDUSD","TUSD","BUSD","DAI"}:continue
        qv=float(t.get("quoteVolume") or 0);price=float(t.get("last") or 0)
        if qv>0 and price>0:rows.append((qv,symbol))
    rows.sort(reverse=True);return [s for _,s in rows[:SCAN_LIMIT]]
def _allocation(score,validation_days):
    if not AUTO_ALLOCATION_ENABLED or validation_days<VALIDATION_DAYS:return None
    preferred=40 if score>=.65 else 30 if score>=.55 else 20 if score>=.40 else 10
    return min(preferred,AUTO_ALLOCATION_MAX_PCT)
def _effective_commercial(state):return float(state.get("strategy_effectiveness",0))>=COMMERCIAL_MIN_EFFECTIVENESS
def _position_net_profit(entry, last, amount):
    gross=amount*(last-entry)
    notional=((entry*amount)+(last*amount))/2
    fees=notional*(ESTIMATED_ROUND_TRIP_FEE_PCT/100)
    return gross-fees

def run_once(ex,state):
    start=float(state.get("allocation_validation_start") or time.time());state["allocation_validation_start"]=start;validation_days=(time.time()-start)/86400
    risk=load_settings();stop_loss_enabled=bool(risk["stop_loss_enabled"])
    state["risk_policy"]={"stop_loss_enabled":stop_loss_enabled,"label":"Ограничение убытка (SL)","exit_mode":"STOP_LOSS" if stop_loss_enabled else "WAIT_FOR_RECOVERY"}
    state["profit_time_policy"]={"mode":PROFIT_TARGET_MODE,"target_profit_per_unit":PROFIT_TARGET_PER_UNIT,"minimum_profit_per_unit":PROFIT_FLOOR_PER_UNIT,"target_trade_interval_sec":TARGET_TRADE_INTERVAL_SEC,"max_trade_hold_sec":MAX_TRADE_HOLD_SEC,"estimated_round_trip_fee_pct":ESTIMATED_ROUND_TRIP_FEE_PCT}
    state["allocation_policy"]={"auto_enabled":AUTO_ALLOCATION_ENABLED,"validation_days":round(validation_days,2),"required_days":VALIDATION_DAYS,"max_auto_position_pct":AUTO_ALLOCATION_MAX_PCT,"status":"LOCKED" if not AUTO_ALLOCATION_ENABLED or validation_days<VALIDATION_DAYS else "ENABLED"}
    state["commercial_policy"]={"minimum_effectiveness":COMMERCIAL_MIN_EFFECTIVENESS,"measured_effectiveness":float(state.get("strategy_effectiveness",0)),"status":"ENABLED" if _effective_commercial(state) else "LOCKED","profit_share":PROFIT_SHARE}
    if state.get("day")!=time.strftime("%Y-%m-%d"):state["day"]=time.strftime("%Y-%m-%d");state["realized_pnl"]=0.0;state["trades"]=[]
    if state["realized_pnl"]<=-float(os.getenv("DAILY_LOSS_LIMIT_USDT","3")):return {"halt":"daily_loss_limit","bot_balance":BOT_BALANCE,"risk_policy":state["risk_policy"]}
    ranked=[]
    for symbol in _universe(ex):
        try:
            data=_tf_data(ex,symbol);book=ex.exchange.fetch_order_book(symbol,limit=50);ob=analyze_orderbook(symbol,book);a=evaluate(data,{"score":ob["score"],"spoof_risk":ob["spoof_risk"],"pressure_velocity":ob["pressure_velocity"]},None,0.0);ranked.append((float(a["score"]),symbol,a))
        except Exception:continue
    ranked.sort(reverse=True,key=lambda x:x[0]);radar=ranked[:RADAR_LIMIT];rank_map={s:(sc,a) for sc,s,a in ranked};now={s:{"score":round(sc,4),"direction":a["direction"],"regime":a["regime"]["regime"],"ob":a["orderbook_score"],"structure":a["timeframes"].get("3m",{}).get("structure",{}).get("score",0)} for sc,s,a in radar}
    for symbol,pos in list(state["positions"].items()):
        try:
            last=float(ex.exchange.fetch_ticker(symbol)["last"]);entry=float(pos["entry"]);amount=float(pos["amount"]);age=time.time()-float(pos.get("opened",time.time()));allocated_capital=float(pos.get("allocated_capital",float(pos.get("allocation_pct",0))*BOT_BALANCE/100));net_profit=_position_net_profit(entry,last,amount);pnl=(last/entry-1)*100;sc,a=rank_map.get(symbol,(0.0,{}));confirmed_reversal=sc<-.35 and a.get("direction")=="bearish"
            money_tp=PROFIT_TARGET_MODE=="money_time" and should_take_profit(net_profit=net_profit,allocated_capital=allocated_capital,age_sec=age,profile=PROFIT_PROFILE)
            rotate=PROFIT_TARGET_MODE=="money_time" and should_rotate(net_profit=net_profit,allocated_capital=allocated_capital,age_sec=age,profile=PROFIT_PROFILE,entry_still_valid=True)
            reason="money_time_target" if money_tp else ("time_recycle" if rotate else decide_exit(entry,last,None if PROFIT_TARGET_MODE=="money_time" else TP,SL,stop_loss_enabled,confirmed_reversal))
            if reason:
                res=ex.create_market_order(symbol,"sell",amount,live=_live());state["realized_pnl"]+=net_profit;state["trades"].append({"ts":time.time(),"symbol":symbol,"exit":last,"pnl_pct":pnl,"net_profit":net_profit,"allocated_capital":allocated_capital,"profit_per_unit":net_profit/allocated_capital if allocated_capital else 0,"hold_sec":age,"target_interval_sec":TARGET_TRADE_INTERVAL_SEC,"lazy_profit_share":max(0,net_profit)*PROFIT_SHARE,"reason":reason,"order":res});del state["positions"][symbol]
            else:pos.update({"last":last,"pnl_pct":pnl,"net_profit":net_profit,"score":sc,"age_sec":age,"profit_target_net":PROFIT_PROFILE.target_net_profit(allocated_capital),"profit_floor_net":PROFIT_PROFILE.minimum_net_profit(allocated_capital)})
        except Exception:continue
    if not AUTO_ALLOCATION_ENABLED or validation_days<VALIDATION_DAYS:
        _save_state(state);return {"live":_live(),"bot_balance":BOT_BALANCE,"account_balance_view":ACCOUNT_BALANCE_VIEW,"allocated":sum(float(p.get("allocation_pct",0)) for p in state["positions"].values()),"free":BOT_BALANCE-sum(float(p.get("allocation_pct",0))*BOT_BALANCE/100 for p in state["positions"].values()),"risk_policy":state["risk_policy"],"profit_time_policy":state["profit_time_policy"],"allocation_policy":state["allocation_policy"],"commercial_policy":state["commercial_policy"],"radar":now,"positions":state["positions"],"realized_pnl":state["realized_pnl"]}
    used=set(state["positions"]);used_pct=sum(float(p.get("allocation_pct",0)) for p in state["positions"].values());free=max(0,MAX_POSITIONS-len(used))
    for score,symbol,a in radar:
        if free<=0 or symbol in used or score<MIN_SCORE or a["direction"]!="bullish":continue
        regime=a["regime"]["regime"];structure=a["timeframes"].get("3m",{}).get("structure",{});ob=float(a["orderbook_score"])
        if regime=="bear" or ob<0 or (regime=="flat" and float(structure.get("score",0))<.40):continue
        allocation=_allocation(score,validation_days)
        if allocation is None or used_pct+allocation>100:continue
        budget=BOT_BALANCE*allocation/100;price=float(ex.exchange.fetch_ticker(symbol)["last"]);amount=float(ex.exchange.amount_to_precision(symbol,budget/price))
        if amount<=0:continue
        try:
            res=ex.create_market_order(symbol,"buy",amount,live=_live());allocated_capital=amount*price;state["positions"][symbol]={"entry":price,"amount":amount,"allocation_pct":allocation,"allocated_capital":allocated_capital,"score":score,"opened":time.time(),"profit_target_net":PROFIT_PROFILE.target_net_profit(allocated_capital),"profit_floor_net":PROFIT_PROFILE.minimum_net_profit(allocated_capital),"target_interval_sec":TARGET_TRADE_INTERVAL_SEC};used.add(symbol);used_pct+=allocation;free-=1
        except Exception:continue
    _save_state(state);return {"live":_live(),"bot_balance":BOT_BALANCE,"account_balance_view":ACCOUNT_BALANCE_VIEW,"allocated_pct":used_pct,"free":BOT_BALANCE*(1-used_pct/100),"risk_policy":state["risk_policy"],"profit_time_policy":state["profit_time_policy"],"allocation_policy":state["allocation_policy"],"commercial_policy":state["commercial_policy"],"radar":now,"positions":state["positions"],"realized_pnl":state["realized_pnl"]}
def main():
    ex=gateway(os.getenv("EXCHANGE","binance"));state=_load_state();print(f"LazyBot FS | {'LIVE' if _live() else 'PAPER'} | bot_balance={BOT_BALANCE} {QUOTE} | auto-allocation={'ON' if AUTO_ALLOCATION_ENABLED else 'LOCKED'} | profit/time={PROFIT_TARGET_PER_UNIT:.4f}/{PROFIT_FLOOR_PER_UNIT:.4f} per unit | interval={TARGET_TRADE_INTERVAL_SEC}s | profit_share={PROFIT_SHARE:.4f}")
    while True:
        try:print(json.dumps(run_once(ex,state),ensure_ascii=False,default=str))
        except KeyboardInterrupt:break
        except Exception as exc:print(json.dumps({"error":str(exc)}))
        time.sleep(POLL)
if __name__=="__main__":main()
