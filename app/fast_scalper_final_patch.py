from . import fast_scalper_beta_001_legacy as legacy
from fastapi import HTTPException
import asyncio
import time
import re

# Final lifecycle/UI patch. Keeps the current radar, 10-slot layout and
# allocation logic intact; only fixes position lifecycle and position display.
MAX_HOLD = 300.0
CLOSE_TIMEOUT = 10.0

async def close_safe(p, reason):
    symbol = str(p.get('symbol','')).upper().replace('/','')
    try:
        await asyncio.wait_for(legacy.close(p, reason), timeout=CLOSE_TIMEOUT)
        print(f'[TRADE] CLOSE_OK {symbol} reason={reason}', flush=True)
        return True
    except asyncio.TimeoutError:
        legacy.S['error'] = f'Close {symbol}: timeout after {CLOSE_TIMEOUT:.0f}s'
        print(f'[TRADE] CLOSE_ERROR {symbol} reason={reason} timeout={CLOSE_TIMEOUT:.0f}s', flush=True)
        return False
    except Exception as e:
        legacy.S['error'] = f'Close {symbol}: {type(e).__name__}: {e}'
        print(f'[TRADE] CLOSE_ERROR {symbol} reason={reason} {type(e).__name__}: {e}', flush=True)
        return False

async def manage_final():
    now = time.time()
    # Work on a snapshot so removing positions during iteration is safe.
    for p in list(legacy.S.get('positions', [])):
        try:
            p['current'] = legacy.price(p['symbol']) or p.get('current', p.get('entry', 0))
            entry = float(p.get('entry') or 0)
            stake = float(p.get('stake') or 0)
            current = float(p.get('current') or entry)
            live_pct = ((current / entry) - 1.0) * 100.0 if entry else 0.0
            p['delta_usdt'] = ((current / entry) - 1.0) * stake if entry else 0.0
            age = max(0.0, now - float(p.get('opened') or now))
            p['age'] = age
            p['age_seconds'] = int(age)

            # Profit target has priority.
            if float(legacy.S.get('profit', 0) or 0) > 0 and live_pct >= float(legacy.S['profit']):
                await close_safe(p, 'PROFIT_TARGET')
                continue

            # Normal timeout: close if flat/profitable.
            if age >= float(getattr(legacy, 'MAX_AGE', 60) or 60) and live_pct >= 0:
                await close_safe(p, 'TIMEOUT')
                continue

            # Anti-loss hold is bounded. A position must never hang forever.
            if age >= MAX_HOLD:
                await close_safe(p, 'MAX_HOLD')
                continue

            # BOT OFF means no new entries and all remaining positions are closed
            # promptly; never let the OFF button wait on an unbounded request.
            if legacy.S.get('stop_requested'):
                await close_safe(p, 'BOT_OFF')
        except Exception as e:
            legacy.S['error'] = f'Manage {p.get("symbol")}: {type(e).__name__}: {e}'
            print(f'[ENGINE] MANAGE_ERROR {p.get("symbol")} {type(e).__name__}: {e}', flush=True)

legacy.manage = manage_final

# Replace BOT OFF with a non-blocking, deterministic shutdown: stop entries,
# request closure of every current position, and return immediately. The
# background engine performs the bounded close calls.
for r in list(legacy.app.router.routes):
    if getattr(r, 'path', None) == '/api/paper/stop' and 'POST' in (getattr(r, 'methods', set()) or set()):
        legacy.app.router.routes.remove(r)

@legacy.app.post('/api/paper/stop')
async def stop_final_position_patch():
    legacy.S['running'] = False
    legacy.S['stop_requested'] = time.time() if legacy.S.get('positions') else None
    print(f'[BOT] OFF requested positions={len(legacy.S.get("positions", []))}', flush=True)
    return await legacy.state()

# Per-position Emergency. Only the selected position is closed.
@legacy.app.post('/api/position/emergency')
async def position_emergency(body: dict):
    ident = str(body.get('id') or '').strip()
    symbol = str(body.get('symbol') or '').upper().replace('/','').strip()
    target = None
    for p in legacy.S.get('positions', []):
        if ident and str(p.get('id')) == ident:
            target = p; break
        if symbol and str(p.get('symbol','')).upper().replace('/','') == symbol:
            target = p; break
    if target is None:
        raise HTTPException(404, 'Open position not found')
    ok = await close_safe(target, 'EMERGENCY_POSITION')
    if not ok:
        raise HTTPException(502, legacy.S.get('error') or 'Position close failed')
    if not legacy.S.get('positions'):
        legacy.S['stop_requested'] = None
    return await legacy.state()

# Enrich closed records once, without changing their existing meaning.
# opened_at is already stored by the engine. duration_seconds and close_time
# are derived here for the UI and remain available in /api/state.
def enrich_closed():
    for x in legacy.S.get('closed', []):
        if 'duration_seconds' not in x:
            try:
                opened = float(x.get('opened') or 0)
                closed = x.get('closed_at')
                if isinstance(closed, str):
                    from datetime import datetime
                    closed_ts = datetime.fromisoformat(closed).timestamp()
                else:
                    closed_ts = float(closed or time.time())
                x['duration_seconds'] = max(0, int(closed_ts - opened)) if opened else 0
            except Exception:
                x['duration_seconds'] = 0
        if 'close_time' not in x:
            x['close_time'] = x.get('closed_at') or ''

# Add display helpers/styles to the existing production HTML. Do not rebuild
# the page, so the approved controls and TOP-10 layout remain untouched.
html = legacy.HTML
css = '''<style>
.pos-line,.closed-line{display:flex;align-items:center;gap:7px;min-height:31px;padding:5px 0;border-bottom:1px solid #24314a;white-space:nowrap;overflow:hidden}
.pos-main,.closed-main{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis}
.pos-delta{font-weight:850;min-width:72px;text-align:right}
.pos-delta.pos-plus,.closed-pnl.pos-plus{color:#18c878}
.pos-delta.pos-minus,.closed-pnl.pos-minus{color:#ef5264}
.pos-age,.closed-age{color:#8b97ae;min-width:48px;text-align:right;font-variant-numeric:tabular-nums}
.pos-emergency{background:#a72e3f!important;padding:6px 8px!important;font-size:10px!important;min-width:66px}
.closed-pnl{font-weight:850;min-width:76px;text-align:right}
.closed-time{color:#8b97ae;min-width:54px;text-align:right;font-size:10px}
</style>'''
if '</head>' in html and 'pos-line{' not in html:
    html = html.replace('</head>', css + '</head>', 1)

# Replace the old render() function with a version that shows live delta and age
# and adds a per-position Emergency button. Existing API/state semantics stay the same.
pattern = r'function render\(\)\{.*?\n\}\nasync function load\(\)'
new_render = r'''function render(){
 const m=state.mode||'PAPER';
 $('paperBtn').className='btn mode'+(m==='PAPER'?' active':'');
 $('testModeBtn').className='btn mode'+(m==='BINANCE_TEST'?' test-active':'');
 $('account').textContent=num(state.account);$('bot').textContent=num(state.bot_balance);$('reserve').textContent=num(state.reserve);$('sp').textContent=num(state.session_realized);
 $('tim').textContent='SESSION '+clock(state.session_age)+' · 24H '+clock(state.day_age);
 const p=state.positions||[];
 $('pos').innerHTML=p.length?p.map(x=>{
   const d=Number(x.delta_usdt!==undefined?x.delta_usdt:((Number(x.current||0)/Number(x.entry||1)-1)*Number(x.stake||0)));
   const age=Number(x.age_seconds!==undefined?x.age_seconds:Math.max(0,Date.now()/1000-Number(x.opened||Date.now()/1000)));
   const cls=d>=0?'pos-plus':'pos-minus';
   return `<div class="pos-line"><span class="pos-main">${x.symbol} · ${num(x.stake)} USDT</span><span class="pos-delta ${cls}">${d>=0?'+':''}${num(d)} USDT</span><span class="pos-age">${clock(age)}</span><button type="button" class="btn pos-emergency" data-pos-emergency="${x.id||''}" data-symbol="${x.symbol}">EMERGENCY</button></div>`
 }).join(''):'No open positions';
 const c=(state.closed||[]).slice(0,5);
 $('closed').innerHTML=c.map(x=>{
   const pnl=Number(x.pnl||0); const cls=pnl>=0?'pos-plus':'pos-minus';
   let dur=Number(x.duration_seconds||0); if(!dur && x.opened&&x.closed_at){try{dur=Math.max(0,Math.floor((new Date(x.closed_at).getTime()-Number(x.opened)*1000)/1000))}catch(_){}}
   let ct=''; if(x.closed_at){try{ct=new Date(x.closed_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}catch(_){}}
   return `<div class="closed-line"><span class="closed-main">${x.symbol} · ${x.reason}</span><span class="closed-pnl ${cls}">${pnl>=0?'+':''}${num(pnl)} USDT</span><span class="closed-age">${clock(dur)}</span><span class="closed-time">${ct}</span></div>`
 }).join('')||'No closed trades';
 $('radar').innerHTML=(state.ranking||[]).slice(0,15).map((x,i)=>`<div class="rank"><b>${i+1}</b><b>${x.symbol}</b><span>${num(x.price)}</span><span>${num(x.score)}</span><button type="button" class="btn add-radar" data-symbol="${x.symbol}">${(state.slots||[]).includes(x.symbol)?'IN SLOTS':'ADD PAIR'}</button></div>`).join('')||'Radar waiting for data'
}
async function load()'''
html2, n = re.subn(pattern, new_render, html, count=1, flags=re.S)
if n:
    html = html2
# Add delegated Emergency handler before the existing button bindings.
handler = '''\ndocument.addEventListener('click',e=>{const b=e.target.closest('[data-pos-emergency]');if(!b)return;(async()=>{try{b.disabled=true;state=await request('/api/position/emergency','POST',{id:b.dataset.posEmergency,symbol:b.dataset.symbol});render()}catch(err){$('msg').textContent=err.message}finally{b.disabled=false}})()});\n'''
if 'data-pos-emergency' in html and 'position/emergency' not in html.split('</script>')[0]:
    html = html.replace("$('paperBtn').addEventListener", handler+"$('paperBtn').addEventListener", 1)
legacy.HTML = html

# Make the additional fields visible immediately in API state even between cycles.
_old_state = legacy.state
async def state_enriched():
    enrich_closed()
    out = await _old_state()
    now = time.time()
    for p in out.get('positions', []):
        entry=float(p.get('entry') or 0); stake=float(p.get('stake') or 0); cur=float(p.get('current') or entry)
        p['delta_usdt']=((cur/entry)-1)*stake if entry else 0.0
        p['age_seconds']=max(0,int(now-float(p.get('opened') or now)))
        p['age']=p['age_seconds']
    return out
legacy.state = state_enriched
