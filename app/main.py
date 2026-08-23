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
from .rocket_hunter import classify_candles, entry_plan
from .fast_scalper_config import FastScalperConfig, validate as validate_fast, recommended_profit
app=FastAPI(title='LazyBot FS',version='1.1.0')
def paper_config():
    risk=load_settings()
    return {'max_position':float(os.getenv('MAX_POSITION_USD',os.getenv('MAX_POSITION_USDT',5))),'risk_per_trade':float(os.getenv('RISK_PER_TRADE_USD',os.getenv('RISK_PER_TRADE_USDT',1))),'daily_loss_limit':float(os.getenv('DAILY_LOSS_LIMIT_USD',os.getenv('DAILY_LOSS_LIMIT_USDT',3))),'leverage':int(os.getenv('LEVERAGE',1)),'take_profit_pct':float(os.getenv('TAKE_PROFIT_PCT',.6)),'stop_loss_pct':float(os.getenv('STOP_LOSS_PCT',.3)),'stop_loss_enabled':risk['stop_loss_enabled'],'stop_loss_label':'Ограничение убытка (SL)','exit_mode':'STOP_LOSS' if risk['stop_loss_enabled'] else 'WAIT_FOR_RECOVERY'}
def profit_time_config():
    return {'mode':os.getenv('PROFIT_TARGET_MODE','money_time'),'target_profit_per_unit':float(os.getenv('PROFIT_TARGET_PER_UNIT','.25')),'minimum_profit_per_unit':float(os.getenv('PROFIT_FLOOR_PER_UNIT','.20')),'target_trade_interval_sec':int(os.getenv('TARGET_TRADE_INTERVAL_SEC','90')),'max_trade_hold_sec':int(os.getenv('MAX_TRADE_HOLD_SEC','180')),'estimated_round_trip_fee_pct':float(os.getenv('ESTIMATED_ROUND_TRIP_FEE_PCT','0'))}
def fast_scalper_config():
    capital=float(os.getenv('FAST_SCALPER_CAPITAL_USDT','30')); pairs=tuple(x.strip() for x in os.getenv('FAST_SCALPER_PAIRS','DGB/USDT,ZRO/USDT,TUT/USDT,USUAL/USDT,TURBO/USDT').split(',') if x.strip()); alloc=tuple(float(x) for x in os.getenv('FAST_SCALPER_ALLOCATIONS','20,20,20,20,20').split(',')); minp=float(os.getenv('FAST_SCALPER_MIN_PROFIT_USDT','0.20')); target=float(os.getenv('FAST_SCALPER_TARGET_PROFIT_USDT','0.30')); cfg=FastScalperConfig(capital,pairs,alloc,'3m',180,minp,target,os.getenv('FAST_SCALPER_STOP_LOSS_ENABLED','true').lower()=='true',float(os.getenv('FAST_SCALPER_STOP_LOSS_PCT','0.50'))); validate_fast(cfg); return {'capital_usdt':capital,'pairs':pairs,'allocations_pct':alloc,'allocation_usdt':[round(capital*x/100,8) for x in alloc],'timeframe':'3m','max_trade_seconds':180,'min_profit_usdt':minp,'target_profit_usdt':target,'stop_loss_enabled':cfg.stop_loss_enabled,'stop_loss_pct':cfg.stop_loss_pct,'recommended_profit':recommended_profit(capital/len(pairs),float(os.getenv('FAST_SCALPER_ROUND_TRIP_FEE_PCT','0')))}
@app.get('/api/health')
def health():return {'ok':True,'project':'LazyBot FS','mode':os.getenv('TRADING_MODE','live'),'timestamp':datetime.now(timezone.utc).isoformat()}
@app.get('/api/status')
def status():return {'project':'LazyBot FS','strategy':'Fast Scalper + Rocket Hunter','mode':os.getenv('TRADING_MODE','live'),'exchanges':configured_exchange_ids(),'symbol':os.getenv('SYMBOL','BTC/USDT'),'forecast_horizons_min':list(HORIZONS_MIN),'execution_horizon':'1-3m','timeframes':['4h','2h','1h','30m','15m','5m','3m','1m'],'indicators':['MA7','MA25','MA99','RSI14','Stochastic14','slope5','trend_smoothness'],'risk':paper_config(),'profit_time':profit_time_config(),'fast_scalper':fast_scalper_config(),'rocket_hunter_states':['IGNITION','RELOAD','ORBIT','WAIT'],'orderbook_module':'dynamic_walls_v2','live_trading':os.getenv('LIVE_TRADING','false').lower()=='true' and os.getenv('LIVE_TRADING_ARMED','false').lower()=='true','live_transfers':os.getenv('LIVE_TRANSFER_ARMED','false').lower()=='true'}
@app.get('/fast-scalper',response_class=HTMLResponse)
def fast_scalper_page():
    p=fast_scalper_config(); checks='checked' if p['stop_loss_enabled'] else ''; rows=''.join(f'<div class="row"><input value="{s}" class="pair"><input value="{p["allocations_pct"][i]}" class="alloc" type="number" min="1" max="100"><span>USDT <b class="usd">{p["capital_usdt"]*p["allocations_pct"][i]/100:.2f}</b></span></div>' for i,s in enumerate(p['pairs']))
    return f'''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LazyBot FS — Fast Scalper</title><style>body{{font-family:system-ui;background:#18202b;color:#eee;max-width:650px;margin:auto;padding:22px}}.card{{background:#232e3c;border-radius:16px;padding:18px;margin:12px 0}}input{{background:#303b4b;color:#fff;border:1px solid #465466;border-radius:10px;padding:10px;width:90px}}.pair{{width:150px}}button{{padding:13px 18px;border:0;border-radius:10px;font-weight:700}}.green{{color:#39d98a}}.muted{{color:#aab4c2}}.row{{display:flex;gap:10px;align-items:center;margin:10px 0}}.wide{{width:100%}}</style><h1>⚡ Fast Scalper</h1><div class="card"><b>Капитал бота</b><br><input id="capital" type="number" value="{p['capital_usdt']}" min="1"> USDT</div><div class="card"><h3>Торговые пары</h3>{rows}<p class="muted">Распределение должно быть ровно 100%. Бот может работать максимум с 5 активными парами.</p></div><div class="card"><h3>Фрейм</h3><b class="green">3 минуты</b><p class="muted">Одна сделка получает максимум 180 секунд. Realtime Rocket Hunter работает каждую секунду.</p></div><div class="card"><h3>Профит</h3><p>Минимальный: <input id="minp" type="number" step="0.01" value="{p['min_profit_usdt']}"> USDT</p><p>Целевой: <input id="target" type="number" step="0.01" value="{p['target_profit_usdt']}"> USDT</p><button onclick="recommend()">Предложить профит</button><p id="rec" class="green">Рекомендация для этой конфигурации: {p['recommended_profit']['minimum_profit_usdt']}–{p['recommended_profit']['target_profit_usdt']} USDT</p></div><div class="card"><label><input id="sl" type="checkbox" {checks}> Ограничение убытка (SL)</label><p class="muted">Если выключить — Fast Scalper не закрывает убыточную позицию только по SL.</p></div><div class="card"><button class="wide" onclick="saveCfg()">Сохранить конфигурацию</button><p id="msg"></p></div><script>function vals(){{return [...document.querySelectorAll('.alloc')].map(x=>+x.value)}}function recommend(){{const c=+capital.value;const fee=0;const min=Math.max(.20,fee*3),tar=Math.max(.30,fee*4);rec.textContent='Рекомендация: '+min.toFixed(2)+'–'+tar.toFixed(2)+' USDT NET на сделку';minp.value=min.toFixed(2);target.value=tar.toFixed(2)}}function saveCfg(){{const a=vals();if(Math.abs(a.reduce((x,y)=>x+y,0)-100)>.01){{msg.textContent='Ошибка: распределение должно быть 100%';return}}msg.textContent='Сохранено локально для запуска Fast Scalper 3m.';localStorage.setItem('fast_scalper_cfg',JSON.stringify({{capital:+capital.value,pairs:[...document.querySelectorAll('.pair')].map(x=>x.value),alloc:a,min:+minp.value,target:+target.value,sl:sl.checked}}))}}</script></html>'''
@app.get('/settings/risk',response_class=HTMLResponse)
def risk_settings_page():
    enabled=load_settings()['stop_loss_enabled'];checked='checked' if enabled else '';mode='STOP_LOSS' if enabled else 'WAIT_FOR_RECOVERY';p=profit_time_config()
    return f'''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LazyBot FS — скальпер</title><body style="font-family:system-ui;max-width:560px;margin:40px auto;padding:0 20px"><h2>Lazy Scalper</h2><label style="display:flex;gap:12px;align-items:center;font-size:18px"><input id="sl" type="checkbox" {checked} style="width:22px;height:22px"><span>Ограничение убытка (SL)</span></label><p id="mode">Режим: {mode}</p><hr><h3>Профит + скорость</h3><p>Профит на 1 единицу капитала: <b>{p['target_profit_per_unit']}</b></p><p>Минимум после целевого времени: <b>{p['minimum_profit_per_unit']}</b></p><p>Целевой интервал сделки: <b>{p['target_trade_interval_sec']} сек</b></p><p>Максимальный бюджет удержания: <b>{p['max_trade_hold_sec']} сек</b></p><script>const c=document.getElementById('sl'),m=document.getElementById('mode');c.onchange=async()=>{{const r=await fetch('/api/settings/risk/stop-loss',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{enabled:c.checked}})}});const d=await r.json();m.textContent='Режим: '+d.exit_mode;}};</script></body></html>'''
@app.get('/api/settings/risk')
def risk_settings():
    risk=load_settings();return {'stop_loss_enabled':risk['stop_loss_enabled'],'label':'Ограничение убытка (SL)','exit_mode':'STOP_LOSS' if risk['stop_loss_enabled'] else 'WAIT_FOR_RECOVERY'}
@app.post('/api/settings/risk/stop-loss')
def set_risk_stop_loss(payload:dict):
    if 'enabled' not in payload: raise HTTPException(status_code=400,detail='Field "enabled" is required')
    enabled=payload['enabled']
    if not isinstance(enabled,bool): raise HTTPException(status_code=400,detail='Field "enabled" must be boolean')
    risk=set_stop_loss_enabled(enabled);return {'ok':True,'stop_loss_enabled':risk['stop_loss_enabled'],'label':'Ограничение убытка (SL)','exit_mode':'STOP_LOSS' if risk['stop_loss_enabled'] else 'WAIT_FOR_RECOVERY'}
@app.get('/api/settings/profit-time')
def profit_time_settings():return profit_time_config()
@app.get('/api/settings/fast-scalper')
def fast_scalper_settings():return fast_scalper_config()
@app.post('/api/strategy/evaluate')
def strategy_evaluate(payload:dict):return evaluate(payload.get('timeframes',{}),payload.get('orderbook'))
@app.post('/api/rocket-hunter/evaluate')
def rocket_hunter_evaluate(payload:dict):
    candles=payload.get('candles',[]);state=classify_candles(candles);return {'state':state,'entry_plan':entry_plan(candles,state),'execution_horizon':'1-3m','rule':'do_not_force_entry_if_not_ignition'}
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
@app.get('/api/exchanges/entry-requirements')
def exchange_entry_requirements(exchange_id:str,symbol:str,capital_usdt:float=30.0,allocation_pct:float=20.0):
    try:
        req=gateway(exchange_id).market_entry_requirements(symbol)
        budget=capital_usdt*allocation_pct/100.0
        minimum=req.get('minimum_cost')
        req.update({'capital_usdt':capital_usdt,'allocation_pct':allocation_pct,'allocated_usdt':round(budget,8),'entry_possible_with_allocation':minimum is None or budget>=minimum,'allocation_warning':None if minimum is None or budget>=minimum else f"Выделено {budget:.8g} USDT, но минимальный вход {minimum:.8g} {req.get('quote')}. Нужно увеличить слот или выбрать другую пару."})
        return req
    except Exception as exc:raise HTTPException(status_code=400,detail=str(exc))
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
