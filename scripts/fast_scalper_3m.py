"""LazyBot FS — Fast Scalper 3m/short-pump runner."""
from __future__ import annotations
import json, os, signal, time
from pathlib import Path
from dotenv import load_dotenv
from app.realtime_pulse import RealtimePulse
from app.fast_scalper_config import FastScalperConfig, validate, recommended_profit
from app.exchange_gateway import gateway
load_dotenv(); CONFIG_FILE=Path(os.getenv('FAST_SCALPER_CONFIG_FILE','fast_scalper_config.json')); STATE=Path(os.getenv('FAST_SCALPER_STATE_FILE','fast_scalper_3m_state.json')); CONTROL=Path(os.getenv('FAST_SCALPER_CONTROL_FILE','fast_scalper_control.json'))
def read_cfg():
 env=os.environ
 if env.get('FAST_SCALPER_CAPITAL_USDT') or env.get('FAST_SCALPER_PAIRS'):
  capital=float(env.get('FAST_SCALPER_CAPITAL_USDT','100')); pairs=tuple(x.strip().upper().replace('-','/') for x in env.get('FAST_SCALPER_PAIRS','').split(',') if x.strip()); alloc=tuple(float(x) for x in env.get('FAST_SCALPER_ALLOCATIONS',','.join(str(100/len(pairs)) for _ in pairs)).split(',')); return capital,pairs,alloc,float(env.get('FAST_SCALPER_MIN_PROFIT_USDT','0.20')),float(env.get('FAST_SCALPER_TARGET_PROFIT_USDT','0.30')),env.get('FAST_SCALPER_STOP_LOSS_ENABLED','true').lower()=='true',float(env.get('FAST_SCALPER_STOP_LOSS_PCT','0.50'))
 if CONFIG_FILE.exists():
  try:
   d=json.loads(CONFIG_FILE.read_text()); return float(d['capital_usdt']),tuple(d['pairs']),tuple(float(x) for x in d['allocations_pct']),float(d['min_profit_usdt']),float(d['target_profit_usdt']),bool(d.get('stop_loss_enabled',True)),float(d.get('stop_loss_pct',0.50))
  except Exception: pass
 return 100.0,('BTC/USDT','ETH/USDT'),(50.0,50.0),0.20,0.30,True,0.50
CAPITAL,SYMBOLS,ALLOCS,MIN_PROFIT,TARGET_PROFIT,SL_ENABLED,SL_PCT=read_cfg()
if not 1<=len(SYMBOLS)<=5: raise ValueError('Fast Scalper supports 1–5 selected pairs')
if len(ALLOCS)!=len(SYMBOLS) or abs(sum(ALLOCS)-100)>0.01: raise ValueError('Pair allocations must total 100%')
MAX_HOLD=180; PUMP_HOLD=20; FEE_PCT=float(os.getenv('FAST_SCALPER_ROUND_TRIP_FEE_PCT','0.20'))/100; LIVE=os.getenv('FAST_SCALPER_LIVE','false').lower()=='true' and os.getenv('LIVE_TRADING','false').lower()=='true' and os.getenv('LIVE_TRADING_ARMED','false').lower()=='true'
CFG=FastScalperConfig(CAPITAL,SYMBOLS,ALLOCS,'3m',MAX_HOLD,MIN_PROFIT,TARGET_PROFIT,SL_ENABLED,SL_PCT); validate(CFG); EX=gateway('binance'); STOP_REQUESTED=False
def load_state():
 if STATE.exists():
  try:return json.loads(STATE.read_text())
  except Exception:pass
 return {'mode':'LIVE' if LIVE else 'PAPER','capital':CAPITAL,'free_capital':CAPITAL,'realized_pnl':0.0,'positions':{},'orders':{},'trades':[],'started_at':time.time(),'error':None}
def save(s): STATE.parent.mkdir(parents=True,exist_ok=True); STATE.write_text(json.dumps(s,indent=2,ensure_ascii=False))
def pnl(pos,price):
 amount=float(pos['amount']); gross=amount*(price-float(pos['entry'])); fees=(float(pos['capital'])+amount*price)*FEE_PCT/2; return gross-fees
def live_order(side,symbol,amount): return EX.create_market_order(symbol,side,amount,live=LIVE)
def close(s,symbol,price,reason,now):
 pos=s['positions'][symbol]; amount=float(pos['amount']); sell_amount=amount*(1-FEE_PCT/2)
 if LIVE:
  EX.load_markets(); sell_amount=float(EX.exchange.amount_to_precision(symbol,sell_amount))
  if sell_amount<=0:return
  order=live_order('sell',symbol,sell_amount); price=float(order.get('average') or order.get('price') or price); amount=float(order.get('filled') or sell_amount); s['orders'][symbol]={'symbol':symbol,'side':'SELL','requested_amount':sell_amount,'filled_amount':amount,'remaining_amount':max(0,sell_amount-amount),'status':order.get('status','CLOSED'),'order_id':order.get('id')}
 profit=pnl({**pos,'amount':amount},price); s['realized_pnl']+=profit; s['free_capital']+=float(pos['capital'])+profit; s['trades'].append({'symbol':symbol,'entry':pos['entry'],'exit':price,'capital':pos['capital'],'amount':amount,'pnl':profit,'hold_sec':now-float(pos['opened']),'reason':reason,'signal':pos.get('signal'),'fills':pos.get('fills',[]),'ts':now}); del s['positions'][symbol]
def command():
 try:
  if CONTROL.exists(): return json.loads(CONTROL.read_text()).get('command','RUN')
 except Exception: pass
 return 'RUN'
def emergency(s):
 now=time.time()
 for symbol in list(s['positions']):
  try:price=float(EX.exchange.fetch_ticker(symbol).get('last') or s['positions'][symbol]['entry'])
  except Exception:price=float(s['positions'][symbol]['entry'])
  try:close(s,symbol,price,'EMERGENCY_STOP',now)
  except Exception as exc:s['error']=str(exc)[:300]
 s['orders'].clear();save(s)
def _sigterm(_sig,_frame):
 global STOP_REQUESTED; STOP_REQUESTED=True
signal.signal(signal.SIGTERM,_sigterm)
s=load_state(); pulse=RealtimePulse(SYMBOLS,window_seconds=12); pulse.start()
if LIVE:
 try:
  EX.load_markets(); bal=EX.fetch_balance(); free=float((bal.get('free') or {}).get('USDT') or 0)
  if CAPITAL>free+1e-9: raise RuntimeError(f'capital {CAPITAL} exceeds free USDT balance {free}')
 except Exception as exc:s['error']=str(exc)[:300];save(s);raise
rec=recommended_profit(CAPITAL/len(SYMBOLS),FEE_PCT*100); print(json.dumps({'mode':'LIVE' if LIVE else 'PAPER','exchange':'binance','capital':CAPITAL,'pairs':SYMBOLS,'allocations_pct':ALLOCS,'timeframe':'3m','pump_hold_sec':PUMP_HOLD,'trade_budget_sec':MAX_HOLD,'minimum_profit_usdt':MIN_PROFIT,'target_profit_usdt':TARGET_PROFIT,'recommended':rec,'stop_loss':SL_ENABLED,'pulse':'1s','live_orders':LIVE},ensure_ascii=False),flush=True)
try:
 while not STOP_REQUESTED:
  cmd=command()
  if cmd=='EMERGENCY_STOP': emergency(s); break
  if cmd=='STOP': break
  now=time.time(); snaps=pulse.snapshot()
  for symbol,pos in list(s['positions'].items()):
   raw=snaps.get(symbol.replace('/','')) or snaps.get(symbol)
   if not raw:continue
   price=float(raw['price']); age=now-float(pos['opened']); profit=pnl(pos,price); reason=None; hold=float(pos.get('hold_sec',MAX_HOLD))
   if profit>=TARGET_PROFIT:reason='TARGET_PROFIT'
   elif age>=90 and profit>=MIN_PROFIT and hold>20:reason='MIN_PROFIT_AT_90S'
   elif age>=hold:reason='PUMP_20S_EXIT' if pos.get('signal')=='PUMP' else ('3M_TIME_EXIT' if profit>=0 else 'CRITICAL_EXIT')
   elif SL_ENABLED and price<=float(pos['entry'])*(1-SL_PCT):reason='STOP_LOSS'
   if reason:
    try:close(s,symbol,price,reason,now)
    except Exception as exc:s['error']=str(exc)[:300]
  for idx,symbol in enumerate(SYMBOLS):
   raw=snaps.get(symbol.replace('/','')) or snaps.get(symbol)
   if not raw or symbol in s['positions'] or raw.get('state') not in {'IGNITION','EARLY_ROCKET'}:continue
   score=float(raw.get('score',0)); c2=float(raw.get('price_change_2s',0)); vr=float(raw.get('volume_ratio',0)); br=float(raw.get('buy_ratio',0.5))
   if score<0.45 or c2<0.0006 or vr<1.5 or br<0.55:continue
   signal_type='PUMP' if raw.get('state')=='IGNITION' else 'ROCKET'; capital=CAPITAL*ALLOCS[idx]/100
   if capital>s['free_capital']+1e-9:continue
   price=float(raw['price']); amount=capital/price
   try:
    EX.load_markets(); amount=float(EX.exchange.amount_to_precision(symbol,amount))
    if amount<=0:continue
    order=live_order('buy',symbol,amount); actual_price=float(order.get('average') or order.get('price') or price); actual_amount=float(order.get('filled') or amount); s['free_capital']-=capital; s['orders'][symbol]={'symbol':symbol,'side':'BUY','requested_amount':amount,'filled_amount':actual_amount,'remaining_amount':max(0,amount-actual_amount),'status':order.get('status','FILLED'),'order_id':order.get('id'),'fills':order.get('trades',[]) or []}; s['positions'][symbol]={'entry':actual_price,'capital':capital,'amount':actual_amount,'opened':now,'score':score,'state':raw['state'],'signal':signal_type,'hold_sec':PUMP_HOLD if signal_type=='PUMP' else MAX_HOLD,'allocation_pct':ALLOCS[idx],'fills':order.get('trades',[]) or []}; print(json.dumps({'event':'ENTRY','mode':'LIVE' if LIVE else 'PAPER','symbol':symbol,'capital':capital,'price':actual_price,'amount':actual_amount,'score':score,'signal':signal_type},ensure_ascii=False),flush=True)
   except Exception as exc:s['error']=str(exc)[:300]
  s['updated_at']=now;save(s);time.sleep(1)
finally:
 pulse.stop();save(s)
