import os
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from .forecast import HORIZONS_MIN, validate_horizon, forecast_targets
from .cross_validation import run_matrix
from .exchange_gateway import configured_exchange_ids, gateway, choose_best_spot
from .transfer_router import plan_cross_exchange
from .orderbook_pressure import analyze_orderbook
from .risk_settings import load_settings, set_stop_loss_enabled
from .strategy_intelligence import evaluate
app=FastAPI(title='LazyBot FS',version='0.8.0')
def paper_config():
    risk=load_settings()
    return {'max_position':float(os.getenv('MAX_POSITION_USD',os.getenv('MAX_POSITION_USDT',5))),'risk_per_trade':float(os.getenv('RISK_PER_TRADE_USD',os.getenv('RISK_PER_TRADE_USDT',1))),'daily_loss_limit':float(os.getenv('DAILY_LOSS_LIMIT_USD',os.getenv('DAILY_LOSS_LIMIT_USDT',3))),'leverage':int(os.getenv('LEVERAGE',1)),'take_profit_pct':float(os.getenv('TAKE_PROFIT_PCT',.6)),'stop_loss_pct':float(os.getenv('STOP_LOSS_PCT',.3)),'stop_loss_enabled':risk['stop_loss_enabled'],'stop_loss_label':'Ограничение убытка (SL)','exit_mode':'STOP_LOSS' if risk['stop_loss_enabled'] else 'WAIT_FOR_RECOVERY'}
def profit_time_config():
    return {'mode':os.getenv('PROFIT_TARGET_MODE','money_time'),'target_profit_per_unit':float(os.getenv('PROFIT_TARGET_PER_UNIT','.25')),'minimum_profit_per_unit':float(os.getenv('PROFIT_FLOOR_PER_UNIT','.20')),'target_trade_interval_sec':int(os.getenv('TARGET_TRADE_INTERVAL_SEC','90')),'max_trade_hold_sec':int(os.getenv('MAX_TRADE_HOLD_SEC','180')),'estimated_round_trip_fee_pct':float(os.getenv('ESTIMATED_ROUND_TRIP_FEE_PCT','0'))}
@app.get('/api/health')
def health():return {'ok':True,'project':'LazyBot FS','mode':os.getenv('TRADING_MODE','paper'),'timestamp':datetime.now(timezone.utc).isoformat()}
@app.get('/api/status')
def status():return {'project':'LazyBot FS','strategy':'Fast Scalper','mode':os.getenv('TRADING_MODE','paper'),'exchanges':configured_exchange_ids(),'symbol':os.getenv('SYMBOL','BTC/USDT'),'forecast_horizons_min':list(HORIZONS_MIN),'execution_horizon':'1-3m','timeframes':['4h','2h','1h','30m','15m','5m','3m','1m'],'indicators':['MA7','MA25','MA99','RSI14','Stochastic14','slope5','trend_smoothness'],'risk':paper_config(),'profit_time':profit_time_config(),'orderbook_module':'dynamic_walls_v2','quote_currency':'agnostic','live_trading':os.getenv('LIVE_TRADING','false').lower()=='true' and os.getenv('LIVE_TRADING_ARMED','false').lower()=='true','live_transfers':os.getenv('LIVE_TRANSFER_ARMED','false').lower()=='true'}
@app.get('/settings/risk',response_class=HTMLResponse)
def risk_settings_page():
    enabled=load_settings()['stop_loss_enabled'];checked='checked' if enabled else '';mode='STOP_LOSS' if enabled else 'WAIT_FOR_RECOVERY';p=profit_time_config()
    return f'''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LazyBot FS — скальпер</title><body style="font-family:system-ui;max-width:560px;margin:40px auto;padding:0 20px"><h2>Lazy Scalper</h2><label style="display:flex;gap:12px;align-items:center;font-size:18px"><input id="sl" type="checkbox" {checked} style="width:22px;height:22px"><span>Ограничение убытка (SL)</span></label><p id="mode">Режим: {mode}</p><hr><h3>Профит + скорость</h3><p>Профит на 1 единицу капитала: <b>{p['target_profit_per_unit']}</b></p><p>Минимум после целевого времени: <b>{p['minimum_profit_per_unit']}</b></p><p>Целевой интервал сделки: <b>{p['target_trade_interval_sec']} сек</b></p><p>Максимальный бюджет удержания: <b>{p['max_trade_hold_sec']} сек</b></p><p>Интервал — цель оборота, а не команда входить в плохую сделку.</p><script>const c=document.getElementById('sl'),m=document.getElementById('mode');c.onchange=async()=>{{const r=await fetch('/api/settings/risk/stop-loss',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{enabled:c.checked}})}});const d=await r.json();m.textContent='Режим: '+d.exit_mode;}};</script></body></html>'''
@app.get('/api/settings/risk')
def risk_settings():
    risk=load_settings();return {'stop_loss_enabled':risk['stop_loss_enabled'],'label':'Ограничение убытка (SL)','exit_mode':'STOP_LOSS' if risk['stop_loss_enabled'] else 'WAIT_FOR_RECOVERY'}
@app.post('/api/settings/risk/stop-loss')
def set_risk_stop_loss(payload:dict):
    if 'enabled' not in payload: raise HTTPException(status_code=400,detail='Field "enabled" is required')
    enabled=payload['enabled']
    if not isinstance(enabled,bool): raise HTTPException(status_code=400,detail='Field "enabled" must be boolean')
    risk=set_stop_loss_enabled(enabled)
    return {'ok':True,'stop_loss_enabled':risk['stop_loss_enabled'],'label':'Ограничение убытка (SL)','exit_mode':'STOP_LOSS' if risk['stop_loss_enabled'] else 'WAIT_FOR_RECOVERY'}
@app.get('/api/settings/profit-time')
def profit_time_settings():return profit_time_config()
@app.post('/api/strategy/evaluate')
def strategy_evaluate(payload:dict):return evaluate(payload.get('timeframes',{}),payload.get('orderbook'))
@app.get('/api/paper-test')
def paper_test(price:float=100.0,predicted_return_pct:float=.1):
    targets=forecast_targets(price,predicted_return_pct);return {'ok':True,'mode':'paper','horizons_min':list(HORIZONS_MIN),'targets':{str(h):targets[h] for h in HORIZONS_MIN},'all_horizons_valid':all(validate_horizon(h)==h for h in HORIZONS_MIN),'live_trading':False}
@app.get('/api/paper-test/matrix')
def paper_test_matrix():return run_matrix()
@app.get('/api/exchanges/capabilities')
def exchange_capabilities():
    result={}
    for eid in configured_exchange_ids():
        try:result[eid]=gateway(eid).public_capabilities()
        except Exception as exc:result[eid]={'exchange':eid,'available':False,'error':str(exc)[:300]}
    return result
@app.get('/api/exchanges/preflight')
def exchange_preflight(symbol:str):
    result={}
    for eid in configured_exchange_ids():
        try:result[eid]=gateway(eid).account_preflight(symbol)
        except Exception as exc:result[eid]={'exchange':eid,'eligible':False,'errors':[str(exc)[:300]]}
    return result
@app.get('/api/exchanges/route')
def exchange_route(symbol:str):return {'symbol':symbol,'venues':choose_best_spot(configured_exchange_ids(),symbol)}
@app.get('/api/exchanges/balance')
def exchange_balance(exchange_id:str):
    try:return gateway(exchange_id).fetch_balance()
    except Exception as exc:raise HTTPException(status_code=400,detail=str(exc))
@app.post('/api/exchanges/order')
def exchange_order(exchange_id:str,symbol:str,side:str,amount:float,price:float|None=None,order_type:str='limit',live:bool=False):
    try:
        if live and (os.getenv('LIVE_TRADING','false').lower()!='true' or os.getenv('LIVE_TRADING_ARMED','false').lower()!='true'):raise HTTPException(status_code=403,detail='Live trading is locked')
        return gateway(exchange_id).create_limit_order(symbol,side,amount,price,live=live) if order_type=='limit' else gateway(exchange_id).create_market_order(symbol,side,amount,live=live)
    except HTTPException:raise
    except Exception as exc:raise HTTPException(status_code=400,detail=str(exc))
@app.get('/api/transfers/plan')
def transfer_plan(symbol_buy:str,symbol_sell:str,asset:str,source_exchange:str,destination_exchange:str,amount:float):
    try:return plan_cross_exchange(symbol_buy,symbol_sell,asset,source_exchange,destination_exchange,amount)
    except Exception as exc:raise HTTPException(status_code=400,detail=str(exc))
@app.get('/api/orderbook/analyze')
def orderbook_analyze(exchange_id:str,symbol:str,limit:int=50):
    try:
        book=gateway(exchange_id).fetch_order_book(symbol,max(5,min(limit,500)));result=analyze_orderbook(symbol,book);result.update({'exchange':exchange_id,'symbol':symbol,'best_bid':book['bids'][0][0] if book.get('bids') else None,'best_ask':book['asks'][0][0] if book.get('asks') else None});return result
    except Exception as exc:raise HTTPException(status_code=400,detail=str(exc))
