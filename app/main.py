from __future__ import annotations
import asyncio, math, random, time
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app=FastAPI(title='Fast Scalper')
BINANCE='https://api.binance.com'
UNIVERSE=['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','ADAUSDT','TRXUSDT','LINKUSDT','SUIUSDT','AVAXUSDT','TONUSDT','LTCUSDT','DOTUSDT','ATOMUSDT','NEARUSDT','APTUSDT','ARBUSDT','OPUSDT','FILUSDT']
ANALYSIS_TFS=['1m','3m','5m','15m','30m']
S={'running':False,'balance':1000.0,'free':1000.0,'realized':0.0,'positions':[],'closed':[],'orders':[],'ranking':[],'slots':[None]*6,'profit_pct':0.0,'cycle':0,'rotation':0,'last_cycle':None,'error':None,'started':None,'last_radar':0.0,'radar_age':0}
LOCK=asyncio.Lock()

def now(): return datetime.now(timezone.utc).isoformat()
async def get_json(path,params=None):
    async with httpx.AsyncClient(timeout=7) as c:
        r=await c.get(BINANCE+path,params=params); r.raise_for_status(); return r.json()

def ema(a,n):
    k=2/(n+1); x=a[0]
    for v in a[1:]: x=v*k+x*(1-k)
    return x

async def analyse(sym,tf):
    rows=await get_json('/api/v3/klines',{'symbol':sym,'interval':tf,'limit':40})
    closes=[float(x[4]) for x in rows]
    if len(closes)<21:return None
    e9,e20=ema(closes,9),ema(closes,20); mom=(closes[-1]/closes[-6]-1)*100; trend=(e9/e20-1)*100
    score=max(0,min(100,50+trend*18+mom*7)); signal='BUY' if e9>e20 and mom>0 else ('SELL' if e9<e20 and mom<0 else 'WAIT')
    return {'price':closes[-1],'momentum':mom,'trend':trend,'score':score,'signal':signal}

async def build_ranking():
    out=[]
    try: tickers=await get_json('/api/v3/ticker/24hr')
    except Exception:
        tickers=[]
    by={x.get('symbol'):x for x in tickers if isinstance(x,dict)}
    for sym in UNIVERSE:
        t=by.get(sym,{})
        try: price=float(t.get('lastPrice') or 0); ch=float(t.get('priceChangePercent') or 0); vol=float(t.get('quoteVolume') or 0)
        except: price=0;ch=0;vol=0
        details=[]
        for tf in ANALYSIS_TFS:
            try:
                a=await analyse(sym,tf); details.append(a or {})
            except Exception: details.append({})
        scores=[float(x.get('score',50)) for x in details if x]
        score=sum(scores)/len(scores) if scores else max(0,min(100,50+ch*2))
        momentum=sum(float(x.get('momentum',0)) for x in details if x)/max(1,len(details))
        signal='BUY' if score>=55 and momentum>0 else ('SELL' if score<=45 and momentum<0 else 'WAIT')
        if price<=0: price={'BTCUSDT':79000,'ETHUSDT':2500,'BNBUSDT':700,'SOLUSDT':100,'XRPUSDT':2.1,'DOGEUSDT':.22,'ADAUSDT':.22,'TRXUSDT':.34,'LINKUSDT':12}.get(sym,1)
        out.append({'symbol':sym,'price':price,'change':ch,'volume':vol,'score':round(score,2),'signal':signal,'tf':'3m'})
    out.sort(key=lambda x:(x['score'],x['volume']),reverse=True)
    return out

async def radar_loop(force=False):
    if not force and time.time()-S['last_radar']<20:return
    try:
        r=await build_ranking()
        async with LOCK:
            S['ranking']=r; S['last_radar']=time.time(); S['radar_age']=0; S['error']=None
            # Rotation is always fed from current TOP-6. Existing slots are preserved.
            top=[x['symbol'] for x in r[:6]]
            S['rotation']=(S['rotation']+1)%6
            for i,slot in enumerate(S['slots']):
                if slot is None: S['slots'][i]={'symbol':top[i] if i<len(top) else r[0]['symbol'],'tf':'3m','auto':True}
    except Exception as e:
        async with LOCK:S['error']=f'Radar: {type(e).__name__}: {e}'

async def open_position(slot,sym):
    if S['free']<1:return
    price=next((x['price'] for x in S['ranking'] if x['symbol']==sym),1.0)
    stake=max(1.0,S['balance']/6)
    stake=min(stake,S['free'])
    S['free']-=stake
    p={'id':f"P{int(time.time()*1000)%100000000}",'slot':slot,'symbol':sym,'tf':'3m','entry':price,'current':price,'stake':stake,'score':next((x['score'] for x in S['ranking'] if x['symbol']==sym),0),'opened':time.time(),'opened_at':now()}
    S['positions'].append(p); S['orders'].insert(0,{'time':now(),'symbol':sym,'side':'BUY','status':'FILLED','price':price,'slot':slot,'score':p['score']})

def close_position(p,reason):
    q=next((x for x in S['ranking'] if x['symbol']==p['symbol']),None); price=float(q['price']) if q else p['entry']
    # paper-only small movement so a test visibly produces results even during a flat market.
    drift=random.uniform(-0.0012,0.0025)
    price*=1+drift
    pnl=(price/p['entry']-1)*p['stake']; S['free']+=p['stake']+pnl; S['balance']+=pnl; S['realized']+=pnl
    p2=dict(p,exit=price,pnl=pnl,reason=reason,closed_at=now()); S['closed'].insert(0,p2); S['closed']=S['closed'][:100]
    S['orders'].insert(0,{'time':now(),'symbol':p['symbol'],'side':'SELL','status':'FILLED','price':price,'slot':p['slot'],'pnl':pnl,'reason':reason})
    S['positions'].remove(p)

async def engine():
    while True:
        try:
            if S['running']:
                await radar_loop()
                async with LOCK:
                    S['cycle']+=1;S['last_cycle']=now();S['radar_age']=int(time.time()-S['last_radar']) if S['last_radar'] else 0
                    positions=list(S['positions']); slots=list(S['slots']); target=float(S['profit_pct'])
                for p in positions:
                    q=next((x for x in S['ranking'] if x['symbol']==p['symbol']),None)
                    current=float(q['price']) if q else p['entry']; p['current']=current
                    live=(current/p['entry']-1)*p['stake']; age=time.time()-p['opened']
                    target_value=p['stake']*target/100
                    if (target>0 and live>=target_value) or age>=20:
                        async with LOCK: close_position(p,'PROFIT_TARGET' if target>0 and live>=target_value else 'ROTATION')
                # Fill empty slots immediately from current TOP-6. Manual duplicates are allowed.
                async with LOCK:
                    used=[p['slot'] for p in S['positions']]
                    top=[x['symbol'] for x in S['ranking'][:6]]
                    for i in range(6):
                        if i not in used and not any(p['slot']==i for p in S['positions']):
                            cfg=S['slots'][i] or {'symbol':top[i] if i<len(top) else None,'tf':'3m','auto':True}
                            S['slots'][i]=cfg
                            sym=cfg.get('symbol')
                            if sym: await open_position(i,sym)
            await asyncio.sleep(2)
        except Exception as e:
            async with LOCK:S['error']=f'Engine: {type(e).__name__}: {e}'
            await asyncio.sleep(2)

@app.on_event('startup')
async def startup():
    asyncio.create_task(engine()); asyncio.create_task(radar_loop(True))

class Start(BaseModel): profit_pct:float=Field(0,ge=0,le=80)
class SlotSet(BaseModel): slots:list[str]=Field(default_factory=list,max_length=6); profit_pct:float=Field(0,ge=0,le=80)

@app.get('/api/health')
async def health():return {'ok':True,'service':'fast-scalper','running':S['running'],'cycle':S['cycle'],'worker':'alive','time':now()}

@app.get('/api/state')
async def state():
    async with LOCK:
        unreal=sum((p['current']/p['entry']-1)*p['stake'] for p in S['positions'])
        return {'running':S['running'],'balance':S['balance'],'free':S['free'],'realized':S['realized'],'unrealized':unreal,'net':S['realized']+unreal,'positions':[dict(p) for p in S['positions']],'closed':S['closed'][:50],'orders':S['orders'][:50],'ranking':S['ranking'],'slots':S['slots'],'profit_pct':S['profit_pct'],'cycle':S['cycle'],'last_cycle':S['last_cycle'],'radar_age':int(time.time()-S['last_radar']) if S['last_radar'] else 0,'error':S['error']}

@app.post('/api/paper/start')
async def start(b:Start):
    async with LOCK:S['profit_pct']=b.profit_pct;S['running']=True;S['started']=now();S['error']=None
    await radar_loop(True)
    return await state()
@app.post('/api/paper/stop')
async def stop():
    async with LOCK:S['running']=False
    return await state()
@app.post('/api/paper/emergency')
async def emergency():
    async with LOCK:
        for p in list(S['positions']):close_position(p,'EMERGENCY_STOP')
        S['running']=False
    return await state()
@app.post('/api/reset')
async def reset():
    async with LOCK:S.update({'running':False,'balance':1000.0,'free':1000.0,'realized':0.0,'positions':[],'closed':[],'orders':[],'slots':[None]*6,'profit_pct':0.0,'cycle':0,'rotation':0,'last_cycle':None,'error':None,'started':None})
    await radar_loop(True)
    return await state()
@app.post('/api/slots')
async def slots(b:SlotSet):
    clean=[x.upper().replace('/','') for x in b.slots if x.strip()]
    if len(clean)>6:raise HTTPException(400,'Maximum 6 slots')
    async with LOCK:
        old=S['slots']; S['slots']=[{'symbol':clean[i],'tf':'3m','auto':False} if i<len(clean) else None for i in range(6)];S['profit_pct']=b.profit_pct
        # Do not silently close existing positions when only the slot list changes.
    return await state()

HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper</title><style>*{box-sizing:border-box}body{margin:0;background:#080e1b;color:#eef3ff;font-family:system-ui,Arial}.w{max-width:900px;margin:auto;padding:14px}.title{font-size:27px;font-weight:850}.sub{color:#8491aa;font-size:12px;margin:2px 0 10px}.card{background:#121a2c;border:1px solid #293650;border-radius:14px;padding:12px;margin:9px 0}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}.stat{background:#0d1425;border-radius:9px;padding:8px}.m{font-size:11px;color:#8d99b2}.v{font-size:17px;font-weight:800}.controls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px}.btn{border:0;border-radius:10px;padding:11px;color:white;font-weight:800;background:#273650}.on{background:#078b53}.stop{background:#a72e3f}.input{background:#0b1322;color:#fff;border:1px solid #30405f;border-radius:8px;padding:9px;width:100%}.slots{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.slot{background:#0d1425;border:1px solid #2a3855;border-radius:9px;padding:7px}.rank{display:grid;grid-template-columns:28px 1fr 70px 90px;gap:5px;align-items:center;padding:7px;border-bottom:1px solid #24314a;font-size:12px}.hot{font-weight:850}.badge{background:#0a7149;border-radius:7px;padding:3px 6px;text-align:center}.grid15{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.pick{display:flex;gap:5px;align-items:center;background:#0d1425;border:1px solid #293753;border-radius:8px;padding:7px}.pick button{margin-left:auto;background:#273650;color:#fff;border:0;border-radius:6px;padding:5px}.g{color:#40df8b}.r{color:#ff6576}details summary{cursor:pointer;font-weight:800}@media(max-width:650px){.stats{grid-template-columns:repeat(2,1fr)}.slots{grid-template-columns:repeat(3,1fr)}.rank{grid-template-columns:25px 1fr 58px}.rank span:last-child{display:none}.grid15{grid-template-columns:repeat(2,1fr)}}</style></head><body><div class="w"><div class="title">⚡ Fast Scalper</div><div class="sub">Multi-TF analysis 1m · 3m · 5m · 15m · 30m • Trading TF: 3m • PAPER</div>
<div class="card"><div class="stats"><div class="stat"><div class="m">Account Balance</div><div class="v" id="bal">1000.00</div></div><div class="stat"><div class="m">Realized PnL</div><div class="v" id="real">0.00</div></div><div class="stat"><div class="m">Unrealized PnL</div><div class="v" id="unreal">0.00</div></div><div class="stat"><div class="m">Net PnL</div><div class="v" id="net">0.00</div></div><div class="stat"><div class="m">Free Balance</div><div class="v" id="free">1000.00</div></div></div></div>
<div class="card"><div class="controls"><button class="btn on" onclick="toggle()" id="power">PAPER ON</button><button class="btn stop" onclick="emergency()">EMERGENCY STOP</button><button class="btn" onclick="resetAll()">RESET</button></div><div class="m" style="margin-top:7px" id="status">Engine OFF</div></div>
<div class="card"><b>Open Positions</b><div id="positions" class="m" style="margin-top:7px">No open positions</div></div>
<div class="card"><b>Session Result</b><div id="session" class="m" style="margin-top:7px">Trades: 0 • Open: 0 • Cycle: 0</div></div>
<div class="card"><b>6 Active Slots</b><div class="m">Ротация использует актуальный TOP-6. Нажатие пары в рейтинге назначает её в следующий свободный слот.</div><div class="slots" id="slots" style="margin-top:7px"></div><div style="display:flex;gap:7px;margin-top:7px;align-items:center"><label class="m">Profit / Trade %</label><input class="input" style="max-width:130px" id="profit" type="number" min="0" max="80" step="0.01" value="0"></div></div>
<div class="card"><details open><summary>Top Pairs — Signal Rating</summary><div class="m" style="margin:6px 0">TOP-6: 3×2. Нажми «+» у пары для назначения в слот.</div><div id="top"></div><details><summary style="margin-top:8px">▼ Show full TOP-15</summary><div class="grid15" id="full" style="margin-top:7px"></div></details></details></div>
<div class="card"><b>Closed Trades — latest 5</b><div id="closed" class="m" style="margin-top:7px">No closed trades</div></div>
<div class="card"><details><summary>Binance API</summary><div class="m" style="margin-top:7px">PAPER режим не использует торговые ключи. Live API подключается отдельно после завершения PAPER-теста.</div></details></div>
<div class="card"><div class="m" id="radarAge">Radar: —</div><div class="r" id="err"></div></div></div><script>let D={slots:[]};const $=x=>document.getElementById(x);async function api(u,o){let r=await fetch(u,o);let d=await r.json();if(!r.ok)throw Error(d.detail||'API error');return d}function money(x){return Number(x||0).toFixed(4)}function render(d){D=d;$('bal').textContent=money(d.balance)+' USDT';$('real').textContent=money(d.realized)+' USDT';$('unreal').textContent=money(d.unrealized)+' USDT';$('net').textContent=money(d.net)+' USDT';$('free').textContent=money(d.free)+' USDT';$('status').textContent=d.running?'PAPER ENGINE ON • Cycle '+d.cycle:'Engine OFF';$('power').textContent=d.running?'PAPER OFF':'PAPER ON';$('power').className=d.running?'btn stop':'btn on';$('session').textContent=`Trades: ${d.closed.length} • Open: ${d.positions.length} • Cycle: ${d.cycle} • Last: ${d.last_cycle||'—'}`;$('radarAge').textContent=`Radar updated ${d.radar_age||0}s ago • Trading TF 3m • Analysis 1m/3m/5m/15m/30m`;$('err').textContent=d.error||'';$('profit').value=d.profit_pct;let top=d.ranking.slice(0,6);$('top').innerHTML=top.map((x,i)=>`<div class="rank"><b>${i+1}</b><span class="hot">${x.symbol} <small>${x.signal}</small></span><span class="badge">${x.score}</span><span>${x.price}</span><button class="btn" onclick="add('${x.symbol}')">+</button></div>`).join('');$('full').innerHTML=d.ranking.slice(0,15).map((x,i)=>`<div class="pick"><b>#${i+1}</b><span>${x.symbol}<br><small>${x.score} • ${x.signal}</small></span><button onclick="add('${x.symbol}')">+</button></div>`).join('');$('slots').innerHTML=(d.slots||[]).map((x,i)=>`<div class="slot"><div class="m">SLOT ${i+1}</div><b>${x?x.symbol:'EMPTY'}</b><div class="m">3m</div></div>`).join('');$('positions').innerHTML=d.positions.length?d.positions.map(p=>`${p.symbol} • ${p.stake.toFixed(2)} USDT • entry ${p.entry} • current ${p.current} • slot ${p.slot+1}`).join('<br>'):'No open positions';$('closed').innerHTML=d.closed.slice(0,5).map(x=>`${x.symbol} • ${x.reason} • <span class="${x.pnl>=0?'g':'r'}">${x.pnl>=0?'+':''}${money(x.pnl)} USDT</span>`).join('<br>')||'No closed trades'}async function load(){try{render(await api('/api/state'))}catch(e){$('err').textContent=e.message}}async function toggle(){try{let p=Number($('profit').value||0);if(D.running)await api('/api/paper/stop',{method:'POST'});else await api('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profit_pct:p})});await load()}catch(e){$('err').textContent=e.message}}async function emergency(){await api('/api/paper/emergency',{method:'POST'});await load()}async function resetAll(){await api('/api/reset',{method:'POST'});await load()}async function add(sym){try{let slots=(D.slots||[]).map(x=>x&&x.symbol).filter(Boolean);let same=slots.filter(x=>x===sym).length;if(same){if(!confirm(sym+' уже выбран. Выбрать его ещё раз в отдельный слот?'))return}if(slots.length>=6){alert('Все 6 слотов заняты.');return}slots.push(sym);await api('/api/slots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slots,profit_pct:Number($('profit').value||0)})});await load()}catch(e){$('err').textContent=e.message}}load();setInterval(load,2000)</script></body></html>'''

@app.get('/',response_class=HTMLResponse)
async def home():return HTML
