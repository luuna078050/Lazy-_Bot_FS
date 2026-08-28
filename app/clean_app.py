from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Fast Scalper")
BINANCE = "https://api.binance.com"
UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT", "SUIUSDT", "AVAXUSDT", "TONUSDT"]
TF_SEC = {"1m": 60, "3m": 180, "5m": 300}

STATE: dict[str, Any] = {
    "running": False,
    "capital": 100.0,
    "account_balance": 100.0,
    "free_balance": 100.0,
    "realized": 0.0,
    "unrealized": 0.0,
    "net": 0.0,
    "pairs": [],
    "positions": [],
    "closed": [],
    "orders": [],
    "ranking": [],
    "error": None,
    "started_at": None,
    "last_update": None,
    "cycle": 0,
    "target_per_100_min": 1.73,
    "cooldown": {},
}
LOCK = asyncio.Lock()
WORKER: asyncio.Task | None = None


class StartReq(BaseModel):
    capital: float = Field(gt=0)
    pairs: list[dict[str, str]] = Field(default_factory=list)


class PairReq(BaseModel):
    pairs: list[dict[str, str]] = Field(default_factory=list)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def binance(path: str, params: dict[str, Any] | None = None):
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(BINANCE + path, params=params)
        response.raise_for_status()
        return response.json()


async def market_snapshot() -> list[dict[str, Any]]:
    tickers = await binance("/api/v3/ticker/24hr")
    by_symbol = {x["symbol"]: x for x in tickers if x.get("symbol") in UNIVERSE}
    rows: list[dict[str, Any]] = []

    for symbol in UNIVERSE:
        ticker = by_symbol.get(symbol, {})
        try:
            k1 = await binance("/api/v3/klines", {"symbol": symbol, "interval": "1m", "limit": 6})
            k3 = await binance("/api/v3/klines", {"symbol": symbol, "interval": "3m", "limit": 2})
        except Exception:
            k1, k3 = [], []

        price = float(ticker.get("lastPrice") or 0)
        change24 = float(ticker.get("priceChangePercent") or 0)
        trades24 = int(float(ticker.get("count") or 0))
        volume24 = float(ticker.get("quoteVolume") or 0)
        m1 = 0.0
        trades1m = 0
        volume1m = 0.0
        if k1:
            base = float(k1[-1][1] or price)
            m1 = (price / base - 1.0) * 100 if base else 0.0
            trades1m = int(float(k1[-1][8] or 0))
            volume1m = float(k1[-1][7] or 0)
        m3 = 0.0
        if len(k3) >= 2:
            a = float(k3[-2][1] or 0)
            b = float(k3[-1][4] or 0)
            m3 = (b / a - 1.0) * 100 if a else 0.0

        hot = max(0.0, min(100.0, 50.0 + abs(m1) * 120.0 + abs(m3) * 80.0))
        activity = max(0.0, min(100.0, math.log10(max(trades1m, 1)) / 3.0 * 100.0))
        liquidity = max(0.0, min(100.0, (math.log10(max(volume24, 1.0)) - 5.0) / 5.0 * 100.0))
        momentum = max(0.0, min(100.0, 50.0 + m1 * 120.0 + m3 * 60.0))
        stability = max(0.0, min(100.0, 100.0 - abs(m1) * 300.0))
        score = 0.30 * hot + 0.25 * momentum + 0.20 * activity + 0.15 * liquidity + 0.10 * stability
        signal = "BUY" if m1 > 0 or m3 > 0 else "SELL" if m1 < 0 or m3 < 0 else "WAIT"

        rows.append({
            "symbol": symbol,
            "score": round(max(0.0, min(100.0, score)), 1),
            "price": price,
            "change24": round(change24, 3),
            "m1": round(m1, 4),
            "m3": round(m3, 4),
            "trades24": trades24,
            "trades1m": trades1m,
            "vol24": volume24,
            "vol1m": volume1m,
            "hot": round(hot, 1),
            "activity": round(activity, 1),
            "liquidity": round(liquidity, 1),
            "signal": signal,
        })

    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows


def expected_pnl(row: dict[str, Any], tf: str, capital: float) -> float:
    seconds = TF_SEC[tf]
    recent_move = abs(float(row.get("m1", 0))) + abs(float(row.get("m3", 0))) * 0.5
    rate = max(0.0002, min(0.02, recent_move / 100.0))
    return round(capital * rate * (seconds / 60.0), 4)


async def refresh_rank() -> list[dict[str, Any]]:
    try:
        rows = await market_snapshot()
        async with LOCK:
            STATE["ranking"] = rows
            STATE["last_update"] = now()
            STATE["error"] = None
        return rows
    except Exception as exc:
        async with LOCK:
            STATE["error"] = f"Market: {str(exc)[:240]}"
        return []


async def open_paper(row: dict[str, Any], tf: str, allocation: float) -> bool:
    symbol = row["symbol"]
    price = float(row["price"])
    async with LOCK:
        if not STATE["running"] or allocation <= 0 or STATE["free_balance"] < allocation:
            return False
        if any(x["symbol"] == symbol for x in STATE["positions"]):
            return False
        side = "SHORT" if row["signal"] == "SELL" else "LONG"
        position = {
            "id": f"{symbol}-{time.time_ns()}",
            "symbol": symbol,
            "tf": tf,
            "entry": price,
            "current": price,
            "allocation": allocation,
            "opened_ts": time.time(),
            "opened_at": now(),
            "score": row["score"],
            "side": side,
            "target": expected_pnl(row, tf, allocation),
        }
        STATE["free_balance"] -= allocation
        STATE["positions"].append(position)
        STATE["orders"].append({"time": now(), "symbol": symbol, "side": side, "status": "PAPER_FILLED", "price": price, "allocation": allocation})
        return True


async def close_paper(position: dict[str, Any], reason: str) -> None:
    symbol = position["symbol"]
    async with LOCK:
        row = next((x for x in STATE["ranking"] if x["symbol"] == symbol), None)
    if not row:
        return
    price = float(row["price"])
    entry = float(position["entry"])
    allocation = float(position["allocation"])
    raw = ((price / entry) - 1.0) * allocation if position["side"] == "LONG" else ((entry / price) - 1.0) * allocation
    fee = (allocation + price * (allocation / entry)) * 0.0005
    pnl = raw - fee
    async with LOCK:
        if position not in STATE["positions"]:
            return
        STATE["free_balance"] += allocation + pnl
        STATE["account_balance"] += pnl
        STATE["realized"] += pnl
        STATE["closed"].insert(0, {
            **position,
            "exit": price,
            "pnl": round(pnl, 6),
            "reason": reason,
            "closed_at": now(),
            "duration_sec": round(time.time() - position["opened_ts"], 1),
        })
        STATE["orders"].append({"time": now(), "symbol": symbol, "side": "CLOSE", "status": "PAPER_FILLED", "price": price, "pnl": round(pnl, 6), "reason": reason})
        STATE["positions"].remove(position)
        STATE["closed"] = STATE["closed"][:100]
        STATE["cooldown"][symbol] = time.time() + 180


async def worker() -> None:
    while True:
        try:
            rows = await refresh_rank()
            async with LOCK:
                STATE["cycle"] += 1
                running = bool(STATE["running"])
                pairs = list(STATE["pairs"])
                positions = list(STATE["positions"])
                capital = float(STATE["capital"])

            if running and rows and pairs:
                by_symbol = {x["symbol"]: x for x in rows}
                allocation = capital / max(1, len(pairs))
                for selected in pairs:
                    symbol = selected["symbol"]
                    tf = selected["tf"]
                    row = by_symbol.get(symbol)
                    if not row or row["price"] <= 0:
                        continue
                    if time.time() < STATE["cooldown"].get(symbol, 0):
                        continue
                    if row["score"] >= 35 and row["signal"] != "WAIT":
                        await open_paper(row, tf, allocation)

                async with LOCK:
                    positions = list(STATE["positions"])
                for position in positions:
                    row = by_symbol.get(position["symbol"])
                    if not row:
                        continue
                    position["current"] = float(row["price"])
                    age = time.time() - float(position["opened_ts"])
                    raw = ((position["current"] / position["entry"]) - 1.0) * position["allocation"] if position["side"] == "LONG" else ((position["entry"] / position["current"]) - 1.0) * position["allocation"]
                    target = max(0.01, float(position["target"]))
                    if raw >= target:
                        await close_paper(position, "TARGET")
                    elif age >= TF_SEC[position["tf"]]:
                        await close_paper(position, "TIMEFRAME")

            async with LOCK:
                unrealized = 0.0
                for position in STATE["positions"]:
                    current = float(position["current"])
                    entry = float(position["entry"])
                    allocation = float(position["allocation"])
                    unrealized += ((current / entry) - 1.0) * allocation if position["side"] == "LONG" else ((entry / current) - 1.0) * allocation
                STATE["unrealized"] = unrealized
                STATE["net"] = STATE["account_balance"] + unrealized - STATE["capital"]
        except Exception as exc:
            async with LOCK:
                STATE["error"] = f"Engine: {str(exc)[:240]}"
        await asyncio.sleep(2)


def snapshot() -> dict[str, Any]:
    result = dict(STATE)
    result["positions"] = [dict(x) for x in STATE["positions"]]
    result["ranking"] = [dict(x) for x in STATE["ranking"]]
    result["closed"] = [dict(x) for x in STATE["closed"][:20]]
    result["session_result"] = {
        "trades": len(STATE["closed"]),
        "open": len(STATE["positions"]),
        "realized": round(STATE["realized"], 6),
        "unrealized": round(STATE["unrealized"], 6),
        "net": round(STATE["net"], 6),
        "target_per_100_min": STATE["target_per_100_min"],
    }
    return result


@app.on_event("startup")
async def startup() -> None:
    global WORKER
    WORKER = asyncio.create_task(worker())


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML


@app.get("/api/health")
async def health():
    return {"ok": True, "running": STATE["running"], "cycle": STATE["cycle"], "engine": "paper-market"}


@app.get("/api/state")
async def state():
    async with LOCK:
        return snapshot()


@app.get("/api/ranking")
async def ranking():
    return {"pairs": await refresh_rank()}


@app.post("/api/radar")
async def radar():
    await refresh_rank()
    async with LOCK:
        return snapshot()


@app.post("/api/pairs")
async def set_pairs(req: PairReq):
    clean = []
    seen = set()
    for item in req.pairs[:10]:
        symbol = item.get("symbol", "").upper().replace("/", "")
        tf = item.get("tf", item.get("timeframe", "3m")).lower()
        if symbol in UNIVERSE and tf in TF_SEC and symbol not in seen:
            clean.append({"symbol": symbol, "tf": tf})
            seen.add(symbol)
    async with LOCK:
        STATE["pairs"] = clean
    return snapshot()


@app.post("/api/paper/start")
async def paper_start(req: StartReq):
    clean = []
    seen = set()
    for item in req.pairs[:10]:
        symbol = item.get("symbol", "").upper().replace("/", "")
        tf = item.get("tf", item.get("timeframe", "3m")).lower()
        if symbol in UNIVERSE and tf in TF_SEC and symbol not in seen:
            clean.append({"symbol": symbol, "tf": tf})
            seen.add(symbol)
    if not clean:
        raise HTTPException(400, "Выбери хотя бы одну пару")
    async with LOCK:
        STATE["capital"] = req.capital
        STATE["account_balance"] = req.capital
        STATE["free_balance"] = req.capital
        STATE["realized"] = 0.0
        STATE["unrealized"] = 0.0
        STATE["net"] = 0.0
        STATE["positions"] = []
        STATE["closed"] = []
        STATE["orders"] = []
        STATE["cooldown"] = {}
        STATE["pairs"] = clean
        STATE["running"] = True
        STATE["started_at"] = now()
        STATE["error"] = None
    return snapshot()


@app.post("/api/paper/stop")
async def paper_stop():
    async with LOCK:
        STATE["running"] = False
    return snapshot()


@app.post("/api/paper/emergency")
async def emergency():
    async with LOCK:
        positions = list(STATE["positions"])
        STATE["running"] = False
    for position in positions:
        await close_paper(position, "EMERGENCY")
    return snapshot()


@app.post("/api/reset")
async def reset_api():
    async with LOCK:
        STATE.update({
            "running": False, "capital": 100.0, "account_balance": 100.0, "free_balance": 100.0,
            "realized": 0.0, "unrealized": 0.0, "net": 0.0, "pairs": [], "positions": [],
            "closed": [], "orders": [], "ranking": [], "error": None, "started_at": None,
            "last_update": None, "cycle": STATE["cycle"], "cooldown": {},
        })
    return snapshot()


HTML = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fast Scalper</title><style>
*{box-sizing:border-box}body{margin:0;background:#090a0c;color:#eee;font-family:Arial,sans-serif}.wrap{max-width:900px;margin:auto;padding:12px}.card{border:1px solid #501019;border-radius:14px;padding:12px;margin:10px 0;background:#0d0e11}h1,h2{margin:4px 0 8px;color:#ff3345}.muted{color:#9a9ca3;font-size:12px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.metric{padding:10px;border-radius:10px;background:#15161a}.v{font-size:20px;font-weight:800}.g{color:#32e875}.r{color:#ff6470}.buttons{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}.btn{border:0;border-radius:10px;padding:12px;font-weight:800;color:#fff;background:#34353b}.on{background:#07994d}.stop{background:#a82737}.slots{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.slot{border:1px solid #272a31;border-radius:10px;padding:8px}.slot input,.slot select{width:100%;background:#15161a;color:#fff;border:1px solid #363940;border-radius:7px;padding:8px;margin-bottom:6px}.radar{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.cand{border:1px solid #33363d;border-radius:10px;padding:9px}.score{float:right;color:#32e875;font-weight:900}.forecast{color:#32e875;font-weight:800}.pick{width:100%;padding:8px;border-radius:8px;border:1px solid #e5a900;background:#15130b;color:#ffc11a;font-weight:800}.selected{border-color:#32e875}.table{width:100%;border-collapse:collapse;font-size:12px}.table td,.table th{padding:6px;border-bottom:1px solid #25272c;text-align:left}.err{color:#ff6470}.target{color:#ffc11a;font-weight:800}@media(max-width:600px){.radar{grid-template-columns:1fr 1fr}.slots{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr 1fr}}
</style></head><body><div class="wrap"><h1>⚡ FAST SCALPER</h1><div class="muted">PAPER • Binance market data • 10 radar candidates • up to 10 active pairs</div>
<div class="card"><div class="grid"><div class="metric">Account Balance<div id="bal" class="v">—</div></div><div class="metric">Free Balance<div id="free" class="v">—</div></div><div class="metric">Realized PnL<div id="real" class="v">—</div></div><div class="metric">Unrealized PnL<div id="unreal" class="v">—</div></div><div class="metric">Net PnL<div id="net" class="v">—</div></div><div class="metric">Цель<div class="v target">1.73 USDT / 100 / мин</div></div></div></div>
<div class="card"><h2>УПРАВЛЕНИЕ</h2><div class="buttons"><button id="run" class="btn on" onclick="toggle()">PAPER ON</button><button class="btn stop" onclick="emergency()">EMERGENCY STOP</button><button class="btn" onclick="resetAll()">RESET</button></div><div id="status" class="muted" style="margin-top:8px">OFF</div></div>
<div class="card"><h2>СЕССИЯ</h2><div id="session" class="muted">—</div></div>
<div class="card"><h2>10 ПОЗИЦИЙ В РОТАЦИИ</h2><div class="muted">Для каждой пары отдельный таймфрейм. Пары можно выбирать из рейтинга.</div><div id="slots" class="slots"></div><button class="btn" style="width:100%;margin-top:8px" onclick="save()">СОХРАНИТЬ 10 ПАР</button></div>
<div class="card"><h2>ТОП-10 • ГОРЯЧАЯ МАТРИЦА</h2><div id="radar" class="radar"></div></div>
<div class="card"><h2>ОТКРЫТЫЕ ПОЗИЦИИ</h2><table class="table"><thead><tr><th>Пара</th><th>TF</th><th>Вход</th><th>Текущая</th><th>PnL</th></tr></thead><tbody id="open"></tbody></table></div>
<div class="card"><h2>ПОСЛЕДНИЕ ЗАКРЫТЫЕ СДЕЛКИ</h2><table class="table"><thead><tr><th>Пара</th><th>TF</th><th>PnL</th><th>Причина</th></tr></thead><tbody id="closed"></tbody></table></div>
<div class="card"><div id="err" class="err"></div></div></div>
<script>
const $=id=>document.getElementById(id),tfs=['1m','3m','5m'];let D={};
function money(x){return Number(x||0).toFixed(4)+' USDT'}
function slots(){let a=D.pairs||[],h='';for(let i=0;i<10;i++){let p=a[i]||{};h+=`<div class="slot"><input id="s${i}" placeholder="PAIR ${i+1}" value="${p.symbol||''}"><select id="t${i}">${tfs.map(x=>`<option ${x===(p.tf||'3m')?'selected':''}>${x}</option>`).join('')}</select></div>`}$('slots').innerHTML=h}
async function api(u,o){let r=await fetch(u,o),d=await r.json();if(!r.ok)throw Error(d.detail||'request failed');return d}
function selected(sym){return(D.pairs||[]).some(x=>x.symbol===sym)}
function renderRadar(){let a=D.ranking||[];$('radar').innerHTML=a.slice(0,10).map((x,i)=>`<div class="cand ${selected(x.symbol)?'selected':''}"><b>🔥 #${i+1} ${x.symbol}</b><span class="score">${x.score}</span><div class="muted">Hot ${x.hot} • 1m trades ${x.trades1m} • 24h trades ${x.trades24}</div><div class="muted">1m ${x.m1}% • 3m ${x.m3}% • 24h ${x.change24}%</div><div class="muted">Activity ${x.activity} • Liquidity ${x.liquidity}</div><div class="forecast">Прогноз $100: ${expected(x)} $/мин</div><button class="pick" onclick="pick('${x.symbol}')">${selected(x.symbol)?'✓ ВЫБРАНО':'ВЫБРАТЬ'}</button></div>`).join('')||'<div class="muted">Радар загружается…</div>'}
function expected(x){let recent=Math.abs(Number(x.m1||0))+Math.abs(Number(x.m3||0))*.5;let rate=Math.max(.0002,Math.min(.02,recent/100));return(100*rate).toFixed(4)}
function render(){
 $('bal').textContent=money(D.account_balance);$('free').textContent=money(D.free_balance);$('real').textContent=money(D.realized);$('unreal').textContent=money(D.unrealized);$('net').textContent=money(D.net);$('status').textContent=D.running?'PAPER РАБОТАЕТ • cycle '+D.cycle:'PAPER ОСТАНОВЛЕН';$('run').textContent=D.running?'PAPER OFF':'PAPER ON';$('run').className='btn '+(D.running?'':'on');$('session').textContent=`Сделок: ${(D.closed||[]).length} • Открыто: ${(D.positions||[]).length} • PnL: ${money(D.realized)} • Цель: 1.73 USDT/100/мин`;
 $('open').innerHTML=(D.positions||[]).map(x=>{let p=Number(x.current),e=Number(x.entry),a=Number(x.allocation),pnl=x.side==='LONG'?(p/e-1)*a:(e/p-1)*a;return`<tr><td>${x.symbol}</td><td>${x.tf}</td><td>${e}</td><td>${p}</td><td class="${pnl>=0?'g':'r'}">${money(pnl)}</td></tr>`}).join('')||'<tr><td colspan="5">Нет открытых позиций</td></tr>';
 $('closed').innerHTML=(D.closed||[]).slice(0,10).map(x=>`<tr><td>${x.symbol}</td><td>${x.tf}</td><td class="${Number(x.pnl)>=0?'g':'r'}">${money(x.pnl)}</td><td>${x.reason}</td></tr>`).join('')||'<tr><td colspan="4">Нет закрытых сделок</td></tr>';$('err').textContent=D.error||'';slots();renderRadar()}
async function refresh(){try{D=await api('/api/state');render()}catch(e){$('err').textContent=e.message}}
async function toggle(){try{if(D.running)D=await api('/api/paper/stop',{method:'POST'});else{let p=collect();let c=Number(prompt('Капитал PAPER, USDT',D.capital||100)||100);D=await api('/api/paper/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({capital:c,pairs:p})})}render()}catch(e){alert(e.message)}}
function collect(){let p=[];for(let i=0;i<10;i++){let s=$('s'+i).value.trim().toUpperCase();if(s)p.push({symbol:s,tf:$('t'+i).value})}return p}
async function save(){try{D=await api('/api/pairs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pairs:collect()})});render()}catch(e){alert(e.message)}}
async function pick(sym){let p=collect().filter(x=>x.symbol!==sym);if(p.length>=10){alert('Максимум 10 пар');return}p.push({symbol:sym,tf:'3m'});D=await api('/api/pairs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pairs:p})});render()}
async function emergency(){try{D=await api('/api/paper/emergency',{method:'POST'});render()}catch(e){alert(e.message)}}
async function resetAll(){try{D=await api('/api/reset',{method:'POST'});render()}catch(e){alert(e.message)}}
refresh();setInterval(refresh,2000);
</script></body></html>'''
