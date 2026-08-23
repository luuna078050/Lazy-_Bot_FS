import os, math
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
from .paper_engine import start_paper, stop_paper, snapshot as paper_snapshot

app=FastAPI(title='LazyBot FS',version='1.3.0')

def paper_config():
    risk=load_settings()
    return {'max_position':float(os.getenv('MAX_POSITION_USD',os.getenv('MAX_POSITION_USDT',5))),'risk_per_trade':float(os.getenv('RISK_PER_TRADE_USD',os.getenv('RISK_PER_TRADE_USDT',1))),'daily_loss_limit':float(os.getenv('DAILY_LOSS_LIMIT_USD',os.getenv('DAILY_LOSS_LIMIT_USDT',3))),'leverage':int(os.getenv('LEVERAGE',1)),'take_profit_pct':float(os.getenv('TAKE_PROFIT_PCT',.6)),'stop_loss_pct':float(os.getenv('STOP_LOSS_PCT',.3)),'stop_loss_enabled':risk['stop_loss_enabled'],'stop_loss_label':'Ограничение убытка (SL)','exit_mode':'STOP_LOSS' if risk['stop_loss_enabled'] else 'WAIT_FOR_RECOVERY'}

def profit_time_config():
    return {'mode':os.getenv('PROFIT_TARGET_MODE','money_time'),'target_profit_per_unit':float(os.getenv('PROFIT_TARGET_PER_UNIT','.25')),'minimum_profit_per_unit':float(os.getenv('PROFIT_FLOOR_PER_UNIT','.20')),'target_trade_interval_sec':int(os.getenv('TARGET_TRADE_INTERVAL_SEC','90')),'max_trade_hold_sec':int(os.getenv('MAX_TRADE_HOLD_SEC','180')),'estimated_round_trip_fee_pct':float(os.getenv('ESTIMATED_ROUND_TRIP_FEE_PCT','0'))}

def free_quote_balance(exchange_id='binance',quote='USDT'):
    try:
        bal=gateway(exchange_id).fetch_balance(); free=bal.get('free',{}) or {}; value=free.get(quote)
        if value is None: value=(bal.get(quote,{}) or {}).get('free',0)
        return float(value or 0)
    except Exception:return None

def fast_scalper_config(capital=None):
    pairs=tuple(x.strip() for x in os.getenv('FAST_SCALPER_PAIRS','').split(',') if x.strip())
    alloc_raw=[x.strip() for x in os.getenv('FAST_SCALPER_ALLOCATIONS','20,20,20,20,20').split(',') if x.strip()]
    alloc=tuple(float(x) for x in alloc_raw) if alloc_raw else (20,20,20,20,20)
    while len(pairs)<5: pairs=pairs+('',)
    while len(alloc)<5: alloc=alloc+(20,)
    pairs=tuple(pairs[:5]); alloc=tuple(alloc[:5])
    minp=float(os.getenv('FAST_SCALPER_MIN_PROFIT_USDT','0.20')); target=float(os.getenv('FAST_SCALPER_TARGET_PROFIT_USDT','0.30'))
    if capital is None: capital=float(os.getenv('FAST_SCALPER_CAPITAL_USDT','0'))
    active=[x for x in pairs if x]
    if not active: active=['BTC/USDT']
    cfg=FastScalperConfig(capital,tuple(active),tuple(alloc[:len(active)]),'3m',180,minp,target,os.getenv('FAST_SCALPER_STOP_LOSS_ENABLED','true').lower()=='true',float(os.getenv('FAST_SCALPER_STOP_LOSS_PCT','0.50')))
    validate_fast(cfg)
    return {'capital_usdt':capital,'pairs':pairs,'allocations_pct':alloc,'allocation_usdt':[round(capital*x/100,8) for x in alloc],'timeframe':'3m','max_trade_seconds':180,'min_profit_usdt':minp,'target_profit_usdt':target,'stop_loss_enabled':cfg.stop_loss_enabled,'stop_loss_pct':cfg.stop_loss_pct,'recommended_profit':recommended_profit(capital/len(active),float(os.getenv('FAST_SCALPER_ROUND_TRIP_FEE_PCT','0'))) if capital>0 else {'minimum_profit_usdt':minp,'target_profit_usdt':target,'estimated_fee_usdt':0}}

def budget_state(exchange_id='binance',requested=0):
    free=free_quote_balance(exchange_id,'USDT'); req=float(requested or 0)
    return {'exchange':exchange_id,'quote':'USDT','requested_budget_usdt':req,'free_balance_usdt':free,'budget_allowed':free is not None and req>=0 and req<=free,'warning':None if free is None else (None if req<=free else f'Бюджет {req:.8f} USDT превышает свободный баланс {free:.8f} USDT.')}

@app.get('/api/health')
def health():return {'ok':True,'project':'LazyBot FS','mode':os.getenv('TRADING_MODE','paper'),'timestamp':datetime.now(timezone.utc).isoformat()}
@app.get('/api/status')
def status():return {'project':'LazyBot FS','strategy':'Fast Scalper + Rocket Hunter','mode':os.getenv('TRADING_MODE','paper'),'exchanges':configured_exchange_ids(),'symbol':os.getenv('SYMBOL','BTC/USDT'),'forecast_horizons_min':list(HORIZONS_MIN),'execution_horizon':'1-3m','timeframes':['4h','2h','1h','30m','3m','1m'],'indicators':['MA7','MA25','MA99','RSI14','Stochastic14','slope5','trend_smoothness'],'risk':paper_config(),'profit_time':profit_time_config(),'fast_scalper':fast_scalper_config(),'rocket_hunter_states':['IGNITION','RELOAD','ORBIT','WAIT'],'orderbook_module':'dynamic_walls_v2','live_trading':os.getenv('LIVE_TRADING','false').lower()=='true' and os.getenv('LIVE_TRADING_ARMED','false').lower()=='true','live_transfers':os.getenv('LIVE_TRANSFER_ARMED','false').lower()=='true'}
@app.get('/api/budget')
def budget(requested:float=0,exchange_id:str='binance'):return budget_state(exchange_id,requested)

@app.get('/api/recommendations')
def recommendations(limit:int=20,quote:str='USDT'):
    try:
        g=gateway('binance'); markets=g.load_markets(); quote=quote.upper()
        symbols=[s for s,m in markets.items() if m.get('spot') and m.get('active',True) and m.get('quote')==quote and '/' in s]
        stable={'USDT','USDC','FDUSD','USDE','TUSD','DAI','USD1'}
        symbols=[s for s in symbols if markets[s].get('base') not in stable]
        tickers=g.exchange.fetch_tickers(symbols)
        rows=[]
        for s,t in tickers.items():
            last=float(t.get('last') or 0); pct=float(t.get('percentage') or 0); vol=float(t.get('quoteVolume') or 0)
            if last<=0 or vol<=10000: continue
            cheap=max(0.0,1.0-math.log10(max(last,1e-9))/4.0)
            momentum=max(-5,min(5,pct))
            liquidity=min(5,math.log10(max(vol,1))/3)
            score=momentum*1.6+liquidity*1.3+cheap*1.0
            rows.append({'symbol':s,'price':last,'change_24h_pct':pct,'quote_volume_24h':vol,'score':round(score,3),'reason':('импульс + ликвидность' if pct>0 else 'ликвидность + возможный отскок')})
        rows.sort(key=lambda x:x['score'],reverse=True)
        return {'ok':True,'count':min(limit,20),'generated_at':datetime.now(timezone.utc).isoformat(),'recommendations':rows[:max(1,min(limit,20))]}
    except Exception as exc: raise HTTPException(status_code=400,detail=str(exc)[:300])

@app.post('/api/paper/start')
def paper_start(payload:dict):
    try:return start_paper(payload,gateway)
    except Exception as exc:raise HTTPException(status_code=400,detail=str(exc))
@app.post('/api/paper/stop')
def paper_stop():return stop_paper(gateway)
@app.get('/api/paper/status')
def paper_status():return paper_snapshot()

@app.get('/fast-scalper',response_class=HTMLResponse)
def fast_scalper_page():
    p=fast_scalper_config(); checks='checked' if p['stop_loss_enabled'] else ''
    rows=''.join(f'<div class="row"><input id="pair{i}" placeholder="Пара {i+1}" value="{p["pairs"][i]}" class="pair"><input id="alloc{i}" value="{p["allocations_pct"][i]}" class="alloc" type="number" min="0" max="100" step="1"><span class="slot">USDT <b class="usd">{p["capital_usdt"]*p["allocations_pct"][i]/100:.2f}</b></span><button class="small" onclick="clearSlot({i})">×</button></div>' for i in range(5))
    return f'''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LazyBot FS</title><style>
body{{font-family:system-ui;background:#111827;color:#f3f4f6;max-width:680px;margin:auto;padding:18px}}h1{{font-size:28px}}.card{{background:#202b3b;border-radius:18px;padding:18px;margin:14px 0}}input{{background:#374151;color:#fff;border:1px solid #526174;border-radius:11px;padding:12px;box-sizing:border-box}}.pair{{width:42%}}.alloc{{width:18%}}button{{border:0;border-radius:12px;padding:13px 16px;font-weight:800;cursor:pointer}}.mode{{display:flex;gap:10px}}.mode button{{flex:1}}.paper{{background:#60a5fa}}.live{{background:#22c55e}}.stop{{background:#ef4444;color:#fff;width:100%}}.primary{{background:#a78bfa;width:100%;margin-top:10px}}.small{{padding:7px 10px;background:#4b5563;color:#fff}}.row{{display:flex;gap:8px;align-items:center;margin:10px 0}}.slot{{flex:1;color:#cbd5e1}}.muted{{color:#aeb8c7}}.green{{color:#4ade80}}.red{{color:#f87171}}.yellow{{color:#facc15}}.rec{{display:flex;justify-content:space-between;gap:8px;padding:9px;border-bottom:1px solid #344154}}.rec button{{padding:7px 10px;background:#4b5563;color:#fff}}.status{{font-size:18px;font-weight:700}}.metric{{display:inline-block;margin:5px 12px 5px 0}}table{{width:100%;font-size:13px;border-collapse:collapse}}td,th{{padding:7px;border-bottom:1px solid #394659;text-align:left}}#results{{display:none}}
</style><h1>⚡ LazyBot FS</h1><p class="muted">Fast Scalper 3m • Binance Spot • Android</p>
<div class="card"><h2>Режим</h2><div class="mode"><button class="paper" onclick="setMode('paper')">▶ PAPER — тест</button><button class="live" onclick="setMode('live')">▶ LIVE — реальные деньги</button></div><button class="stop" onclick="stopBot()">■ Остановить бота</button><p id="status" class="status">⚪ Бот остановлен</p><p id="modeNote" class="muted">PAPER не использует реальные деньги и не требует API-ключей.</p></div>
<div class="card"><h2>Binance</h2><input id="api" class="wide" placeholder="API Key"><br><br><input id="secret" class="wide" placeholder="Secret Key"><p class="muted">Для PAPER ключи не нужны. Для LIVE: Spot Trading + IP restriction, Withdrawals выключены.</p></div>
<div class="card"><h2>Капитал бота</h2><input id="capital" type="number" value="{p['capital_usdt']}" min="0" step="0.01" class="wide"> USDT <p id="free" class="green">Для PAPER бюджет задаётся тобой. Для LIVE будет проверен свободный USDT-баланс.</p></div>
<div class="card"><h2>Пары и доли — 5 слотов</h2>{rows}<p id="allocMsg" class="muted">Доли должны давать 100%. Пары можно менять вручную.</p><button class="primary" onclick="saveCfg()">Сохранить конфигурацию</button></div>
<div class="card"><h2>20 рекомендуемых пар</h2><p class="muted">Это предложения алгоритма, а не закреплённые константы. Нажми «Выбрать», чтобы поместить пару в первый свободный слот.</p><button class="primary" onclick="loadRecommendations()">↻ Обновить анализ</button><div id="recs" class="muted">Нажми «Обновить анализ».</div></div>
<div class="card"><h2>Профит</h2><p>Минимальный NET: <input id="minp" type="number" step="0.01" value="{p['min_profit_usdt']}"> USDT</p><p>Целевой NET: <input id="target" type="number" step="0.01" value="{p['target_profit_usdt']}"> USDT</p><button onclick="recommendProfit()">Предложить профит</button><p id="recProfit" class="green"></p><label><input id="sl" type="checkbox" {checks}> Ограничение убытка (SL)</label></div>
<div class="card"><button class="primary" onclick="startBot()">▶ ЗАПУСТИТЬ БОТА</button><p id="msg"></p></div>
<div id="results" class="card"><h2>Результаты PAPER</h2><div class="metric">Старт: <b id="startBal">0</b> USDT</div><div class="metric">Баланс: <b id="bal">0</b> USDT</div><div class="metric">NET P/L: <b id="pnl">0</b> USDT</div><div class="metric">Сделок: <b id="count">0</b></div><h3>Открытые позиции</h3><div id="open">Нет</div><h3>Последние сделки</h3><div id="trades">Нет сделок</div></div>
<script>
let mode='paper', poll=null;
function setMode(m){{mode=m;document.getElementById('modeNote').textContent=m==='paper'?'PAPER не использует реальные деньги и не требует API-ключей.':'LIVE использует реальные деньги только при включённом LIVE_TRADING и LIVE_TRADING_ARMED на сервере.'}}
function slots(){{return [...Array(5)].map((_,i)=>({{pair:document.getElementById('pair'+i).value.trim().toUpperCase(),alloc:+document.getElementById('alloc'+i).value}})).filter(x=>x.pair)}}
function clearSlot(i){{document.getElementById('pair'+i).value='';document.getElementById('alloc'+i).value='0';}}
async function loadRecommendations(){{const box=document.getElementById('recs');box.textContent='Анализирую рынок Binance…';try{{const d=await (await fetch('/api/recommendations?limit=20')).json();box.innerHTML=(d.recommendations||[]).map((x,i)=>`<div class="rec"><span><b>${i+1}. ${x.symbol}</b><br>${Number(x.price).toPrecision(8)} USDT • 24ч ${Number(x.change_24h_pct).toFixed(2)}% • score ${x.score}</span><button onclick="choosePair('${x.symbol}')">Выбрать</button></div>`).join('')||'Нет данных';}}catch(e){{box.textContent='Ошибка анализа: '+e}}}}
function choosePair(s){{for(let i=0;i<5;i++){{if(!document.getElementById('pair'+i).value.trim()){{document.getElementById('pair'+i).value=s;document.getElementById('alloc'+i).value=20;return}}}}document.getElementById('pair0').value=s;}}
function validateAlloc(){{const a=slots().reduce((n,x)=>n+x.alloc,0);document.getElementById('allocMsg').textContent='Сумма долей: '+a.toFixed(2)+'%';return Math.abs(a-100)<.01}}
async function saveCfg(){{if(!validateAlloc()){{document.getElementById('msg').textContent='Сначала доведи доли до 100%.';return}}localStorage.setItem('lazybot_cfg',JSON.stringify({{capital:+capital.value,pairs:slots(),minp:+minp.value,target:+target.value,sl:sl.checked}}));document.getElementById('msg').textContent='Конфигурация сохранена.'}}
function recommendProfit(){{const c=+capital.value;const min=Math.max(.20,c*.002),tar=Math.max(.30,c*.003);minp.value=min.toFixed(2);target.value=tar.toFixed(2);recProfit.textContent='Рекомендация NET: '+min.toFixed(2)+'–'+tar.toFixed(2)+' USDT на сделку.'}}
async function startBot(){{if(!validateAlloc()){{msg.textContent='Доли должны дать ровно 100%.';return}}const cfg=JSON.parse(localStorage.getItem('lazybot_cfg')||'null')||{{capital:+capital.value,pairs:slots(),minp:+minp.value,target:+target.value,sl:sl.checked}};cfg.pairs=slots();cfg.capital=+capital.value;cfg.min_usdt=+minp.value;cfg.target_usdt=+target.value;cfg.sl_pct=sl.checked?.5:0;cfg.max_hold=180;cfg.fee_pct=.1;msg.textContent='Запускаю…';const url=mode==='paper'?'/api/paper/start':'/api/live/start';try{{const r=await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(cfg)}});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Ошибка запуска');msg.textContent='Бот запущен.';document.getElementById('status').textContent='🟢 '+mode.toUpperCase()+' работает';document.getElementById('results').style.display='block';poll=setInterval(refresh,3000);refresh();}}catch(e){{msg.textContent='Не запущено: '+e.message}}}}
async function stopBot(){{try{{await fetch('/api/paper/stop',{{method:'POST'}});}}catch(e){{}}if(poll)clearInterval(poll);document.getElementById('status').textContent='⚪ Бот остановлен';refresh();}}
async function refresh(){{try{{const d=await (await fetch('/api/paper/status')).json();startBal.textContent=Number(d.initial_balance||0).toFixed(4);bal.textContent=Number(d.balance||0).toFixed(4);pnl.textContent=Number(d.pnl||0).toFixed(4);pnl.className=Number(d.pnl||0)>=0?'green':'red';count.textContent=(d.trades||[]).length;open.innerHTML=Object.values(d.open_positions||{}).map(p=>`<div>${p.symbol}: вход <b>${Number(p.entry_price).toPrecision(8)}</b> • объём ${Number(p.allocated_usdt).toFixed(2)} USDT</div>`).join('')||'Нет';trades.innerHTML=(d.trades||[]).slice().reverse().map(t=>`<div>${t.symbol}: вход ${Number(t.entry_price).toPrecision(8)} → выход ${Number(t.exit_price).toPrecision(8)} • NET <b>${Number(t.net_pnl).toFixed(4)} USDT</b> • ${t.reason}</div>`).join('<hr>')||'Нет сделок';}}catch(e){{}}}}
loadRecommendations();
</script></html>'''

@app.get('/settings/risk',response_class=HTMLResponse)
def risk_settings_page():
    enabled=load_settings()['stop_loss_enabled'];checked='checked' if enabled else '';mode='STOP_LOSS' if enabled else 'WAIT_FOR_RECOVERY';p=profit_time_config()
    return f'''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:system-ui;max-width:560px;margin:40px auto;padding:0 20px"><h2>Lazy Scalper</h2><label><input id="sl" type="checkbox" {checked}> Ограничение убытка (SL)</label><p id="mode">Режим: {mode}</p><h3>Профит + скорость</h3><p>Минимум: {p['minimum_profit_per_unit']}</p><p>Целевой интервал: {p['target_trade_interval_sec']} сек</p><p>Максимум удержания: {p['max_trade_hold_sec']} сек</p><script>sl.onchange=async()=>{{const r=await fetch('/api/settings/risk/stop-loss',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{enabled:sl.checked}})}});const d=await r.json();mode.textContent='Режим: '+d.exit_mode}}</script></body></html>'''
@app.get('/api/settings/risk')
def risk_settings():
    risk=load_settings();return {'stop_loss_enabled':risk['stop_loss_enabled'],'label':'Ограничение убытка (SL)','exit_mode':'STOP_LOSS' if risk['stop_loss_enabled'] else 'WAIT_FOR_RECOVERY'}
@app.post('/api/settings/risk/stop-loss')
def set_risk_stop_loss(payload:dict):
    if 'enabled' not in payload or not isinstance(payload['enabled'],bool):raise HTTPException(status_code=400,detail='Field "enabled" must be boolean')
    risk=set_stop_loss_enabled(payload['enabled']);return {'ok':True,'stop_loss_enabled':risk['stop_loss_enabled'],'label':'Ограничение убытка (SL)','exit_mode':'STOP_LOSS' if risk['stop_loss_enabled'] else 'WAIT_FOR_RECOVERY'}
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
        g=gateway(exchange_id);markets=g.load_markets();m=markets.get(symbol)
        if not m:raise ValueError('symbol_not_available')
        limits=m.get('limits',{}) or {}; amount_lim=limits.get('amount',{}) or {}; cost_lim=limits.get('cost',{}) or {}; price=0.0
        try:price=float(g.exchange.fetch_ticker(symbol).get('last') or 0)
        except Exception:price=0.0
        minimum_cost=cost_lim.get('min'); minimum_amount=amount_lim.get('min')
        if minimum_cost is None and minimum_amount is not None and price>0:minimum_cost=float(minimum_amount)*price
        budget=capital_usdt*allocation_pct/100.0
        req={'exchange':exchange_id,'symbol':symbol,'base':m.get('base'),'quote':m.get('quote'),'price':price,'minimum_amount':minimum_amount,'minimum_cost':minimum_cost,'capital_usdt':capital_usdt,'allocation_pct':allocation_pct,'allocated_usdt':round(budget,8),'entry_possible_with_allocation':minimum_cost is None or budget>=minimum_cost}
        req['allocation_warning']=None if req['entry_possible_with_allocation'] else f'Выделено {budget:.8g} USDT, но минимальный вход {float(minimum_cost):.8g} {m.get("quote")}. Нужно увеличить слот или выбрать другую пару.'
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
        if live:
            bal=gateway(exchange_id).fetch_balance();free=(bal.get('free',{}) or {});market=gateway(exchange_id).load_markets().get(symbol,{});quote=market.get('quote','USDT');free_quote=float(free.get(quote,0) or 0);estimated_cost=(amount*price if price is not None else amount)
            if estimated_cost>free_quote:raise HTTPException(status_code=400,detail=f'Order exceeds free {quote} balance: requested≈{estimated_cost}, free={free_quote}')
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

@app.post('/api/live/start')
def live_start(payload:dict):
    if os.getenv('LIVE_TRADING','false').lower()!='true' or os.getenv('LIVE_TRADING_ARMED','false').lower()!='true':
        raise HTTPException(status_code=403,detail='LIVE пока заблокирован сервером. Сначала включи LIVE_TRADING и LIVE_TRADING_ARMED после проверки PAPER.')
    raise HTTPException(status_code=501,detail='LIVE execution requires final deployment arming; PAPER is the active test runner.')
