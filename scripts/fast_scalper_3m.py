"""LazyBot FS — Fast Scalper 3m runner.

PAPER is the default. LIVE requires FAST_SCALPER_LIVE=true plus the existing
LIVE_TRADING/LIVE_TRADING_ARMED guards. The execution profile is 2-3 user-
selected Binance Spot USDT pairs, fixed allocations summing to 100%, 3-minute
trade budget, absolute USDT profit targets, and one-second Rocket Hunter pulse.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
from dotenv import load_dotenv
from app.realtime_pulse import RealtimePulse
from app.fast_scalper_config import FastScalperConfig, validate, recommended_profit
from app.exchange_gateway import gateway

load_dotenv()
CAPITAL=float(os.getenv("FAST_SCALPER_CAPITAL_USDT","100"))
SYMBOLS=tuple(x.strip().upper().replace("-","/") for x in os.getenv("FAST_SCALPER_PAIRS","DGB/USDT,ZRO/USDT,TUT/USDT").split(",") if x.strip())
ALLOCS=tuple(float(x) for x in os.getenv("FAST_SCALPER_ALLOCATIONS","30,30,40").split(","))
MIN_PROFIT=float(os.getenv("FAST_SCALPER_MIN_PROFIT_USDT","0.20"))
TARGET_PROFIT=float(os.getenv("FAST_SCALPER_TARGET_PROFIT_USDT","0.30"))
MAX_HOLD=180
SL_ENABLED=os.getenv("FAST_SCALPER_STOP_LOSS_ENABLED","true").lower()=="true"
SL_PCT=float(os.getenv("FAST_SCALPER_STOP_LOSS_PCT","0.50"))/100
FEE_PCT=float(os.getenv("FAST_SCALPER_ROUND_TRIP_FEE_PCT","0.20"))/100
LIVE=os.getenv("FAST_SCALPER_LIVE","false").lower()=="true" and os.getenv("LIVE_TRADING","false").lower()=="true" and os.getenv("LIVE_TRADING_ARMED","false").lower()=="true"
STATE=Path(os.getenv("FAST_SCALPER_STATE_FILE","fast_scalper_3m_state.json"))
CFG=FastScalperConfig(CAPITAL,SYMBOLS,ALLOCS,"3m",MAX_HOLD,MIN_PROFIT,TARGET_PROFIT,SL_ENABLED,SL_PCT*100)
validate(CFG)
EX=gateway("binance")

def load_state():
    if STATE.exists():
        try:return json.loads(STATE.read_text())
        except Exception:pass
    return {"free_capital":CAPITAL,"realized_pnl":0.0,"positions":{},"trades":[]}

def save(s): STATE.write_text(json.dumps(s,indent=2,ensure_ascii=False))

def pnl(pos,price):
    amount=float(pos["amount"]); gross=amount*(price-float(pos["entry"])); fees=(float(pos["capital"])+amount*price)*FEE_PCT/2; return gross-fees

def live_order(side,symbol,amount):
    if not LIVE: return {"dry_run":True,"side":side,"symbol":symbol,"amount":amount}
    return EX.create_market_order(symbol,side,amount,live=True)

def close(s,symbol,price,reason,now):
    pos=s["positions"][symbol]; amount=float(pos["amount"]); sell_amount=amount*(1.0-FEE_PCT/2.0)
    if LIVE:
        market=EX.load_markets(); sell_amount=float(EX.exchange.amount_to_precision(symbol,sell_amount));
        if sell_amount<=0: return
        order=live_order("sell",symbol,sell_amount); actual_price=float(order.get("average") or order.get("price") or price); actual_filled=float(order.get("filled") or sell_amount); price=actual_price; amount=actual_filled
    profit=pnl({**pos,"amount":amount},price); s["realized_pnl"]+=profit; s["free_capital"]+=float(pos["capital"])+profit
    s["trades"].append({"symbol":symbol,"entry":pos["entry"],"exit":price,"capital":pos["capital"],"amount":amount,"pnl":profit,"hold_sec":now-float(pos["opened"]),"reason":reason,"ts":now})
    del s["positions"][symbol]

def main():
    state=load_state(); pulse=RealtimePulse(SYMBOLS,window_seconds=12); pulse.start()
    rec=recommended_profit(CAPITAL/len(SYMBOLS),FEE_PCT*100)
    print(json.dumps({"mode":"LIVE" if LIVE else "PAPER","exchange":"binance","capital":CAPITAL,"pairs":SYMBOLS,"allocations_pct":ALLOCS,"timeframe":"3m","trade_budget_sec":MAX_HOLD,"minimum_profit_usdt":MIN_PROFIT,"target_profit_usdt":TARGET_PROFIT,"recommended":rec,"stop_loss":SL_ENABLED,"pulse":"1s","live_orders":LIVE},ensure_ascii=False))
    try:
        while True:
            now=time.time(); snaps=pulse.snapshot()
            # EXIT FIRST: capital turnover is the primary Fast Scalper metric.
            for symbol,pos in list(state["positions"].items()):
                raw=snaps.get(symbol.replace('/','')) or snaps.get(symbol)
                if not raw: continue
                price=float(raw["price"]); age=now-float(pos["opened"]); profit=pnl(pos,price)
                try:
                    if profit>=TARGET_PROFIT: close(state,symbol,price,"TARGET_PROFIT",now)
                    elif age>=90 and profit>=MIN_PROFIT: close(state,symbol,price,"MIN_PROFIT_AT_90S",now)
                    elif age>=MAX_HOLD and profit>=0: close(state,symbol,price,"3M_TIME_EXIT",now)
                    elif SL_ENABLED and price<=float(pos["entry"])*(1-SL_PCT): close(state,symbol,price,"STOP_LOSS",now)
                except Exception as exc: print(json.dumps({"event":"EXIT_ERROR","symbol":symbol,"error":str(exc)},ensure_ascii=False))
            # Entry: one position per configured pair, using its assigned capital.
            for idx,symbol in enumerate(SYMBOLS):
                key=symbol.replace('/',''); raw=snaps.get(key) or snaps.get(symbol)
                if not raw or symbol in state["positions"]: continue
                if raw.get("state") not in {"IGNITION","EARLY_ROCKET"}: continue
                if float(raw.get("score",0))<0.62 or float(raw.get("price_change_2s",0))<0.0012 or float(raw.get("volume_ratio",0))<1.5 or float(raw.get("buy_ratio",0.5))<0.55: continue
                capital=CAPITAL*ALLOCS[idx]/100
                if capital>state["free_capital"]+1e-9: continue
                price=float(raw["price"]); amount=capital/price
                try:
                    market=EX.load_markets(); amount=float(EX.exchange.amount_to_precision(symbol,amount));
                    if amount<=0: continue
                    order=live_order("buy",symbol,amount)
                    actual_price=float(order.get("average") or order.get("price") or price); actual_amount=float(order.get("filled") or amount)
                    state["free_capital"]-=capital; state["positions"][symbol]={"entry":actual_price,"capital":capital,"amount":actual_amount,"opened":now,"score":float(raw["score"]),"state":raw["state"],"allocation_pct":ALLOCS[idx]}
                    print(json.dumps({"event":"ENTRY","mode":"LIVE" if LIVE else "PAPER","symbol":symbol,"capital":capital,"price":actual_price,"amount":actual_amount,"score":raw["score"],"state":raw["state"]},ensure_ascii=False))
                except Exception as exc: print(json.dumps({"event":"ENTRY_ERROR","symbol":symbol,"error":str(exc)},ensure_ascii=False))
            save(state); print(json.dumps({"event":"STATUS","free_capital":state["free_capital"],"realized_pnl":state["realized_pnl"],"open_positions":state["positions"]},ensure_ascii=False)); time.sleep(1)
    except KeyboardInterrupt:
        pulse.stop();save(state);print("Stopped; state saved")

if __name__=="__main__": main()
