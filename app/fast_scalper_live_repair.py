from . import fast_scalper_beta_001_legacy as legacy
import asyncio, re, time

# Final surgical repair. Loaded after fast_scalper_patch.
# Do not add Radar logic here.
html = legacy.HTML

# Exact approved control layout:
# Amount is the single amount field used by both SET BOT BALANCE and WITHDRAW.
# Profit Target is a separate field with default 0.41. Reinvest remains user-controlled.
old_controls = '<div class="card"><div class="row"><input id="allocation" class="input amount" type="number" step="0.01" min="0" placeholder="Amount"><button type="button" class="btn test" id="allocBtn">SET BOT BALANCE</button><button type="button" class="btn stop" id="withdrawBtn">WITHDRAW</button><input id="profit" class="input" type="number" step="0.01" value="0.41"><label style="padding:10px"><input id="reinvest" type="checkbox" checked> Reinvest</label></div>'
new_controls = '<div class="card"><div class="row allocation-row"><input id="allocation" class="input amount" type="number" step="0.01" min="0" placeholder="Amount"><button type="button" class="btn test" id="allocBtn">SET BOT BALANCE</button><button type="button" class="btn stop" id="withdrawBtn">WITHDRAW</button></div><div class="row profit-row" style="margin-top:8px"><input id="profit" class="input" type="number" step="0.01" value="0.41"><label style="padding:10px"><input id="reinvest" type="checkbox" checked> Reinvest</label></div>'
if old_controls not in html:
    raise RuntimeError('Expected Fast Scalper control block not found')
html = html.replace(old_controls, new_controls, 1)

# Make the first control row stay on one line on the phone-sized layout.
html = html.replace('.amount{flex:0 0 150px;max-width:150px}', '.amount{flex:1 1 0;min-width:0;max-width:none}')
html = html.replace('.btn{border:0;border-radius:10px;padding:11px 15px;', '.btn{border:0;border-radius:10px;padding:10px 12px;')
html = html.replace('@media(max-width:650px){', '@media(max-width:650px){.allocation-row{flex-wrap:nowrap}.allocation-row .amount{min-width:0}.allocation-row .btn{font-size:12px;padding:10px 9px;white-space:nowrap}.profit-row{align-items:center}')

# The single Amount field is also the withdrawal amount.
html = html.replace("async function withdrawClick(){try{const a=Number($('withdrawAmount').value);if(!Number.isFinite(a)||a<=0)throw Error('Enter withdrawal amount');state=await request('/api/withdraw','POST',{amount:a});$('msg').textContent='Withdrawn to Reserve: '+num(a)+' USDT';$('withdrawAmount').value='';render()}catch(e){$('msg').textContent=e.message}}", "async function withdrawClick(){try{const a=Number($('allocation').value);if(!Number.isFinite(a)||a<=0)throw Error('Enter withdrawal amount');state=await request('/api/withdraw','POST',{amount:a});$('msg').textContent='Withdrawn to Reserve: '+num(a)+' USDT';$('allocation').value='';render()}catch(e){$('msg').textContent=e.message}}")

# Open Positions: compact font and timer only; do not display the word AGE.
html = html.replace('.pos-line{display:grid;', '.pos-line{font-size:12px;display:grid;')
html = html.replace('.pos-main{white-space:nowrap;', '.pos-main{font-size:12px;white-space:nowrap;')
html = html.replace('.pos-timer{font-weight:800;', '.pos-timer{font-size:12px;font-weight:800;')

legacy.HTML = html

_open_lock = asyncio.Lock()

async def open_pos_fast(i, s):
    if not s:
        return
    symbol = str(s).upper().replace('/', '')
    if any(str(p.get('symbol','')).upper().replace('/','') == symbol for p in legacy.S.get('positions', [])):
        return
    async with _open_lock:
        n = sum(1 for x in legacy.S.get('slots', []) if x)
        if not n or legacy.S.get('free', 0) <= 0:
            return
        stake = min(float(legacy.S['free']), float(legacy.S['bot']) / n)
        if stake <= 0:
            return
        legacy.S['free'] -= stake
    try:
        if legacy.S.get('mode') == 'BINANCE_TEST':
            r = await legacy.B.market_buy(symbol, stake)
            status = r.get('status', '')
            if status != 'FILLED':
                raise RuntimeError(f'Binance BUY not filled: {status or r}')
            qty = float(r.get('executedQty') or 0)
            spent = float(r.get('cummulativeQuoteQty') or 0)
            if qty <= 0 or spent <= 0:
                raise RuntimeError(f'Binance BUY returned empty fill: {r}')
            ep = spent / qty
            async with _open_lock:
                legacy.S['free'] += max(0.0, stake - spent)
            p = {'id': f"B{r.get('orderId', int(time.time()*1000))}", 'slot': i, 'symbol': symbol, 'tf': legacy.TF, 'entry': ep, 'current': ep, 'stake': spent, 'qty': qty, 'opened': time.time(), 'opened_at': legacy.now(), 'order_id': r.get('orderId')}
            legacy.S['positions'].append(p)
            legacy.S['orders'].insert(0, {'time': legacy.now(), 'symbol': symbol, 'side':'BUY', 'status':status, 'price':ep, 'qty':qty, 'stake':spent, 'order_id':r.get('orderId'), 'slot':i})
            print(f'[TRADE] OPEN {symbol} slot={i} stake={spent:.6f} entry={ep} opened_at={p["opened_at"]} mode=BINANCE_TEST', flush=True)
        else:
            ep = legacy.price(symbol)
            if ep <= 0:
                raise RuntimeError('price unavailable')
            p = {'id': f'P{int(time.time()*1000)}', 'slot': i, 'symbol': symbol, 'tf': legacy.TF, 'entry': ep, 'current': ep, 'stake': stake, 'opened': time.time(), 'opened_at': legacy.now()}
            legacy.S['positions'].append(p)
            legacy.S['orders'].insert(0, {'time': legacy.now(), 'symbol':symbol, 'side':'BUY', 'status':'PAPER_FILLED', 'price':ep, 'slot':i})
            print(f'[TRADE] OPEN {symbol} slot={i} stake={stake:.6f} entry={ep} opened_at={p["opened_at"]} mode=PAPER', flush=True)
    except Exception as e:
        async with _open_lock:
            legacy.S['free'] += stake
        legacy.S['error'] = f'Binance BUY {symbol}: {type(e).__name__}: {e}' if legacy.S.get('mode') == 'BINANCE_TEST' else f'Open {symbol}: {type(e).__name__}: {e}'
        print(f'[TRADE] BUY_ERROR {symbol} slot={i} {type(e).__name__}: {e}', flush=True)

async def engine_repair():
    from . import fast_scalper_antloss as anti
    asyncio.create_task(anti._radar_loop())
    while True:
        try:
            if legacy.S.get('running') or legacy.S.get('stop_requested'):
                await legacy.manage()
            if legacy.S.get('running'):
                positions = legacy.S.get('positions', [])
                occupied_slots = {p.get('slot') for p in positions}
                occupied_symbols = {str(p.get('symbol','')).upper().replace('/','') for p in positions}
                tasks = []
                for i, s in enumerate(list(legacy.S.get('slots', []))):
                    if s and i not in occupied_slots and str(s).upper().replace('/','') not in occupied_symbols:
                        tasks.append(open_pos_fast(i, s))
                if tasks:
                    await asyncio.gather(*tasks)
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            legacy.S['error'] = f'Engine: {type(e).__name__}: {e}'
            print(f'[ENGINE] {type(e).__name__}: {e}', flush=True)
            await asyncio.sleep(1)

legacy.open_pos = open_pos_fast
legacy.engine = engine_repair
