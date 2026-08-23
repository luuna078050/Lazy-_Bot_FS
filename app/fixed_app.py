from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from .exchange_gateway import gateway
from .paper_engine import start_paper, stop_paper, emergency_stop_paper, snapshot

app=FastAPI(title='LazyBot FS',version='1.4.1')

@app.get('/api/health')
def health(): return {'ok':True,'project':'LazyBot FS','mode':'paper'}

@app.get('/api/recommendations')
def recommendations(limit:int=20):
    try:
        g=gateway('binance'); markets=g.load_markets()
        symbols=[s for s,m in markets.items() if m.get('spot') and m.get('active',True) and m.get('quote')=='USDT' and '/' in s and m.get('base') not in {'USDT','USDC','FDUSD','USDE','TUSD','DAI','USD1'}]
        rows=[]
        for s,t in g.exchange.fetch_tickers(symbols).items():
            p=float(t.get('last') or 0); pct=float(t.get('percentage') or 0); vol=float(t.get('quoteVolume') or 0)
            if p<=0 or vol<=10000: continue
            score=max(-5,min(5,pct))*1.6+min(5,__import__('math').log10(max(vol,1))/3)+max(0,1-__import__('math').log10(max(p,1e-9))/4)
            rows.append({'symbol':s,'price':p,'change_24h_pct':pct,'quote_volume_24h':vol,'score':round(score,3)})
        rows.sort(key=lambda x:x['score'],reverse=True)
        return {'ok':True,'recommendations':rows[:max(1,min(limit,20))]}
    except Exception as e: raise HTTPException(status_code=400,detail=str(e)[:300])

@app.post('/api/paper/start')
def paper_start(payload:dict): return start_paper(payload,gateway)
@app.post('/api/paper/stop')
def paper_stop(): return stop_paper(gateway)
@app.post('/api/paper/emergency-stop')
def emergency(): return emergency_stop_paper(gateway)
@app.get('/api/paper/status')
def paper_status(): return snapshot()

@app.get('/',response_class=HTMLResponse)
def home():
    slots=''.join('<div><input id="p%d" placeholder="Пара %d" style="width:42%%"><input id="a%d" type="number" value="20" style="width:18%%"> %%</div>'%(i,i+1,i) for i in range(5))
    return '''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LazyBot FS</title><style>body{font-family:system-ui;background:#111827;color:#fff;max-width:700px;margin:auto;padding:16px}.card{background:#202b3b;border-radius:18px;padding:16px;margin:12px 0}input{background:#374151;color:#fff;border:1px solid #526174;border-radius:10px;padding:10px;margin:5px}button{border:0;border-radius:11px;padding:12px;margin:4px;font-weight:800}.primary{background:#a78bfa;width:100%}.paper{background:#60a5fa}.stop{background:#ef4444;color:#fff}.em{background:#991b1b;color:#fff;width:100%}.rec{padding:8px;border-bottom:1px solid #394659;display:flex;justify-content:space-between}.muted{color:#aeb8c7}</style><h1>⚡ LazyBot FS</h1><p class="muted">Fast Scalper • Binance Spot • Android</p><div class="card"><button class="paper" onclick="start()">▶ PAPER — ЗАПУСТИТЬ</button><button class="stop" onclick="stop()">■ STOP</button><button class="em" onclick="emergency()">⛔ EMERGENCY STOP — ЗАКРЫТЬ ВСЁ</button><p id="s">⚪ Остановлен</p></div><div class="card"><h2>Бюджет</h2><input id="capital" type="number" value="30" step="0.01"> USDT</div><div class="card"><h2>5 пар</h2>''' + slots + '''<p>Сумма долей должна быть 100%.</p></div><div class="card"><h2>20 рекомендаций</h2><button class="primary" onclick="recs()">↻ Обновить анализ</button><div id="r">Загрузка…</div></div><div id="out" class="card"><h2>Session Result</h2><p>Старт: <b id="ib">0</b> USDT</p><p>Баланс: <b id="b">0</b> USDT</p><p>NET: <b id="pn">0</b> USDT</p><p>Сделок: <b id="n">0</b></p><h3>Открытые сделки</h3><div id="o">Нет</div><h3>Ордера и fills</h3><div id="ord">Нет</div><h3>Последние сделки</h3><div id="t">Нет</div></div><script>let poll=null;function slots(){return [...Array(5)].map((_,i)=>({p:document.getElementById('p'+i).value.trim().toUpperCase(),a:+document.getElementById('a'+i).value})).filter(x=>x.p)}async function recs(){let d=await (await fetch('/api/recommendations?limit=20')).json();document.getElementById('r').innerHTML=(d.recommendations||[]).map((x,i)=>'<div class="rec"><span><b>'+(i+1)+'. '+x.symbol+'</b><br>'+Number(x.price).toPrecision(8)+' • 24ч '+Number(x.change_24h_pct).toFixed(2)+'% • score '+x.score+'</span><button onclick="pick(\''+x.symbol+'\')">Выбрать</button></div>').join('')||'Нет данных'}function pick(s){for(let i=0;i<5;i++)if(!document.getElementById('p'+i).value){document.getElementById('p'+i).value=s;return}document.getElementById('p0').value=s}async function start(){let x=slots(),sum=x.reduce((z,q)=>z+q.a,0);if(!x.length||Math.abs(sum-100)>.01){document.getElementById('s').textContent='Ошибка: пары/доли должны дать 100%';return}let d=await (await fetch('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({capital:+capital.value,pairs:x.map(q=>q.p),allocations:x.map(q=>q.a),target_usdt:.30,min_usdt:.20,sl_pct:.5,max_hold:180,fee_pct:.1})})).json();document.getElementById('s').textContent=d.running?'🟢 PAPER работает':'Ошибка запуска';poll=setInterval(refresh,3000);refresh()}async function stop(){await fetch('/api/paper/stop',{method:'POST'});if(poll)clearInterval(poll);document.getElementById('s').textContent='⚪ STOP — бот заморожен';refresh()}async function emergency(){await fetch('/api/paper/emergency-stop',{method:'POST'});if(poll)clearInterval(poll);document.getElementById('s').textContent='⛔ EMERGENCY STOP — всё закрыто';refresh()}async function refresh(){let d=await (await fetch('/api/paper/status')).json();ib.textContent=Number(d.initial_balance||0).toFixed(4);b.textContent=Number(d.balance||0).toFixed(4);pn.textContent=Number(d.pnl||0).toFixed(4);n.textContent=(d.trades||[]).length;o.innerHTML=Object.values(d.open_positions||{}).map(p=>'<div><b>'+p.symbol+'</b> • вход '+Number(p.entry_price).toPrecision(8)+' • исполнено '+Number(p.amount).toFixed(6)+' • осталось '+Number(p.remaining_amount||0).toFixed(6)+' • '+(p.order_status||'FILLED')+'<br>fills: '+(p.fills||[]).map(f=>Number(f.amount).toFixed(6)+' @ '+Number(f.price).toPrecision(8)).join(' | ')+'</div>').join('<hr>')||'Нет';ord.innerHTML=Object.values(d.orders||{}).map(q=>'<div><b>'+q.symbol+'</b> • запрос '+Number(q.requested_amount).toFixed(6)+' • исполнено '+Number(q.filled_amount).toFixed(6)+' • остаток '+Number(q.remaining_amount).toFixed(6)+' • '+q.status+'</div>').join('<hr>')||'Нет';t.innerHTML=(d.trades||[]).slice().reverse().map(q=>'<div>'+q.symbol+': '+Number(q.entry_price).toPrecision(8)+' → '+Number(q.exit_price).toPrecision(8)+' • NET '+Number(q.net_pnl).toFixed(4)+' USDT • '+q.reason+'</div>').join('<hr>')||'Нет'}recs()</script></html>'''
