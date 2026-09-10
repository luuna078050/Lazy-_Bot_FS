from __future__ import annotations

import asyncio
import time
import re
from fastapi import HTTPException

from . import fast_scalper_beta_001_legacy as legacy
from .market_radar import RADAR

# Keep the approved 10-slot runtime exactly as it is.
legacy.MAX_SLOTS = 10
legacy.S['slots'] = (list(legacy.S.get('slots', [])) + [None] * 10)[:10]

# ---------- runtime watchdog / anti-freeze ----------
legacy.S.setdefault('engine_heartbeat', 0.0)
legacy.S.setdefault('radar_watchdog_restarts', 0)

async def radar_watchdog():
    """Recover a dead/stale market WebSocket without changing radar logic."""
    while True:
        try:
            await asyncio.sleep(10)
            if not legacy.S.get('running'):
                continue
            last = float(getattr(RADAR, 'last_update', 0.0) or 0.0)
            if last and time.time() - last <= 30:
                continue
            # Re-open the same market stream. This does not alter ranking or pairs.
            try:
                ws = getattr(RADAR, '_ws', None)
                if ws:
                    ws.close()
            except Exception:
                pass
            try:
                stop_evt = getattr(RADAR, '_stop', None)
                if stop_evt:
                    stop_evt.clear()
                RADAR._thread = None
                RADAR.start()
                legacy.S['radar_watchdog_restarts'] = int(legacy.S.get('radar_watchdog_restarts', 0)) + 1
                print('[RADAR] WATCHDOG reconnect', flush=True)
            except Exception as e:
                legacy.S['error'] = f'Radar watchdog: {type(e).__name__}: {e}'
        except asyncio.CancelledError:
            raise
        except Exception as e:
            legacy.S['error'] = f'Radar watchdog: {type(e).__name__}: {e}'


async def stable_engine():
    """Same trade/slot logic, with bounded awaits so one stuck call cannot kill the loop."""
    while True:
        try:
            legacy.S['engine_heartbeat'] = time.time()
            if legacy.S.get('running') or legacy.S.get('stop_requested'):
                try:
                    await asyncio.wait_for(legacy.manage(), timeout=15)
                except asyncio.TimeoutError:
                    legacy.S['error'] = 'Engine: position management timeout'
                    print('[ENGINE] manage timeout', flush=True)

            if legacy.S.get('running'):
                positions = legacy.S.get('positions', [])
                occupied_slots = {p.get('slot') for p in positions}
                occupied_symbols = {str(p.get('symbol', '')).upper().replace('/', '') for p in positions}
                tasks = []
                for i, symbol in enumerate(list(legacy.S.get('slots', []))):
                    if not symbol or i in occupied_slots:
                        continue
                    normalized = str(symbol).upper().replace('/', '')
                    if normalized in occupied_symbols:
                        continue
                    async def bounded_open(slot=i, sym=symbol):
                        try:
                            await asyncio.wait_for(legacy.open_pos(slot, sym), timeout=15)
                        except asyncio.TimeoutError:
                            legacy.S['error'] = f'Engine: open timeout {sym}'
                            print(f'[ENGINE] open timeout {sym}', flush=True)
                    tasks.append(bounded_open())
                if tasks:
                    await asyncio.gather(*tasks)
            legacy.S['engine_heartbeat'] = time.time()
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            legacy.S['error'] = f'Engine: {type(e).__name__}: {e}'
            print(f'[ENGINE] {type(e).__name__}: {e}', flush=True)
            await asyncio.sleep(1)

legacy.engine = stable_engine

# Start the watchdog once per process.
_watchdog_started = False
async def start_watchdog():
    global _watchdog_started
    if not _watchdog_started:
        _watchdog_started = True
        asyncio.create_task(radar_watchdog())

# ---------- per-position Emergency ----------

def _find_position(position_id: str):
    return next((p for p in legacy.S.get('positions', []) if str(p.get('id')) == str(position_id)), None)

# Remove any previous endpoint with the same path pattern is unnecessary; this is a new route.
@legacy.app.post('/api/position/{position_id}/emergency')
async def position_emergency(position_id: str):
    p = _find_position(position_id)
    if p is None:
        raise HTTPException(404, 'Position not found')
    try:
        # Close only this position. The bot itself remains running.
        await asyncio.wait_for(legacy.close(p, 'EMERGENCY_STOP'), timeout=15)
        return await legacy.state()
    except asyncio.TimeoutError:
        legacy.S['error'] = f'Close {p.get("symbol")}: timeout'
        raise HTTPException(504, 'Emergency close timeout')
    except Exception as e:
        legacy.S['error'] = f'Close {p.get("symbol")}: {type(e).__name__}: {e}'
        raise HTTPException(500, legacy.S['error'])

# ---------- Open Positions / Closed Trades UI only ----------
html = legacy.HTML

# Open Positions gets only the requested fields: Delta in USDT, age timer, and a real button.
open_card = '''<div class="card fs-open-card"><h2 class="section-title">Open Positions</h2><div id="pos" class="muted">No open positions</div></div>'''
html = re.sub(r'<div class="card"><h2 class="section-title">Open Positions</h2><div id="pos"[^<]*?>(?:.*?)</div></div>', open_card, html, count=1, flags=re.S)
if 'id="pos"' not in html:
    html = re.sub(r'<div class="card">\s*<h2[^>]*>Open Positions</h2>.*?</div>', open_card, html, count=1, flags=re.S)

style = '''<style>
.fs-open-card .fs-pos-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;align-items:center;padding:7px 0;border-bottom:1px solid #24314a}
.fs-open-card .fs-pos-main{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px}
.fs-open-card .fs-pos-timer{font-size:12px;font-weight:800;color:#8b97ae;white-space:nowrap}
.fs-open-card .fs-emergency{border:0;border-radius:8px;padding:7px 9px;background:#a72e3f;color:#fff;font-weight:850;cursor:pointer;white-space:nowrap;font-size:11px}
.fs-open-card .fs-emergency:disabled{opacity:.55}
.fs-closed-pos{color:#19d58a!important}
.fs-closed-neg{color:#ff6576!important}
@media(max-width:420px){.fs-open-card .fs-pos-row{grid-template-columns:minmax(0,1fr) auto}.fs-open-card .fs-emergency{grid-column:2;grid-row:1}.fs-open-card .fs-pos-timer{grid-column:1;grid-row:2;font-size:11px}.fs-open-card .fs-pos-main{grid-column:1;grid-row:1;font-size:11px}}
</style>'''
html = html.replace('</head>', style + '</head>', 1)

# Replace only the position/closed rendering statements in the existing JS.
old_marker = "$('pos').innerHTML=p.length?p.map(x=>"
start = html.find(old_marker)
if start >= 0:
    end = html.find(";const reasonMap", start)
    if end < 0:
        end = html.find(";$('closed').innerHTML", start)
    if end >= 0:
        new_js = r'''$('pos').innerHTML=p.length?p.map(x=>{const delta=(Number(x.current||0)-Number(x.entry||x.current||0))/Number(x.entry||1)*Number(x.stake||0);const age=Math.max(0,Math.floor(Date.now()/1000-Number(x.opened||Date.now()/1000)));return `<div class="fs-pos-row"><span class="fs-pos-main">${x.symbol} · Δ ${delta>=0?'+':''}${delta.toFixed(4)} USDT</span><span class="fs-pos-timer">${clock(age)}</span><button class="fs-emergency" data-pos="${x.id}">EMERGENCY</button></div>`}).join(''):'No open positions';document.querySelectorAll('.fs-emergency').forEach(b=>b.onclick=async()=>{b.disabled=true;try{state=await request('/api/position/'+encodeURIComponent(b.dataset.pos)+'/emergency','POST');render()}catch(e){$('msg').textContent=e.message;b.disabled=false}})'''
        html = html[:start] + new_js + html[end:]

# If the current UI uses the older compact render, patch its Closed Trades expression too.
closed_old = "$('closed').innerHTML=(state.closed||[]).slice(0,5).map(x=>{const pnl=Number(x.pnl||0);"
if closed_old in html:
    cstart = html.find(closed_old)
    cend = html.find("}).join('')||'No closed trades'", cstart)
    if cend >= 0:
        cend += len("}).join('')||'No closed trades'")
        closed_new = r'''$('closed').innerHTML=(state.closed||[]).slice(0,5).map(x=>{const pnl=Number(x.pnl||0);const cls=pnl>=0?'fs-closed-pos':'fs-closed-neg';const r=x.reason||'—';return `<div class="line ${cls}">${x.symbol} · ${r} · ${pnl>=0?'+':''}${pnl.toFixed(4)} USDT · ${num(x.exit)}</div>`}).join('')||'No closed trades' '''
        html = html[:cstart] + closed_new + html[cend:]

# Current UI has a 1-second interval with overlapping fetches. Replace it with a single-flight poll + timeout.
html = re.sub(r"setInterval\(\(\)=>\{?[^;]*load\(\)[^;]*;?\},1000\);?", "", html)
html = re.sub(r"setInterval\(load,1000\)", "", html)
html += '''<script>(function(){let fsBusy=false;async function fsPoll(){if(fsBusy)return;fsBusy=true;const ctl=new AbortController();const t=setTimeout(()=>ctl.abort(),5000);try{const r=await fetch('/api/state',{cache:'no-store',signal:ctl.signal});if(!r.ok)throw Error('HTTP '+r.status);state=await r.json();render();if(typeof syncSlots==='function')syncSlots()}catch(e){if(typeof $('msg')!=='undefined' && $('msg'))$('msg').textContent=e.name==='AbortError'?'State request timeout':e.message}finally{clearTimeout(t);fsBusy=false}}setInterval(fsPoll,1000);fsPoll()})();</script>'''

legacy.HTML = html

# Health telemetry is additive only.
_original_health = None
for route in legacy.app.router.routes:
    if getattr(route, 'path', None) == '/api/health' and getattr(route, 'endpoint', None):
        _original_health = route.endpoint
        break
if _original_health:
    async def health_repaired():
        data = await _original_health()
        data['engine_heartbeat_age'] = int(max(0, time.time() - float(legacy.S.get('engine_heartbeat', time.time()))))
        data['radar_last_update_age'] = int(max(0, time.time() - float(getattr(RADAR, 'last_update', time.time()))))
        data['radar_watchdog_restarts'] = int(legacy.S.get('radar_watchdog_restarts', 0))
        return data
    for route in list(legacy.app.router.routes):
        if getattr(route, 'path', None) == '/api/health' and getattr(route, 'endpoint', None) is _original_health:
            legacy.app.router.routes.remove(route)
            break
    legacy.app.get('/api/health')(health_repaired)

# Run watchdog as part of startup without changing the existing trading startup semantics.
legacy.app.router.on_startup.append(start_watchdog)
