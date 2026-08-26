from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .config import SETTINGS
from .matrix import Candidate, RankingMatrix, PortfolioAllocation
from .paper_ledger import PaperLedger

app = FastAPI(title="FAST SCALPER CLEAN")
ledger: PaperLedger | None = None

@app.get("/health")
def health():
    return {"status": "ok", "version": "clean-skeleton", "live": False}

@app.get("/api/config")
def config():
    return {
        "capital_default": SETTINGS.default_capital,
        "target_pnl_per_min_per_100": SETTINGS.target_pnl_per_min_per_100,
        "max_pairs": SETTINGS.max_pairs,
        "ranking_layout": "2x5",
        "allocation_modes": ["AUTO", "MANUAL"],
        "timeframes": list(SETTINGS.allowed_timeframes),
    }

@app.get("/api/paper/status")
def paper_status():
    return ledger.snapshot() if ledger else {"running": False, "initial_capital": 0, "realized_pnl": 0, "trades": []}

@app.post("/api/paper/start")
def paper_start(payload: dict):
    global ledger
    capital = float(payload.get("capital", SETTINGS.default_capital))
    if capital <= 0:
        raise HTTPException(400, "Капитал должен быть больше нуля")
    pairs = [str(x).upper().replace("-", "/") for x in payload.get("pairs", [])][:SETTINGS.max_pairs]
    if not pairs:
        raise HTTPException(400, "Выберите хотя бы одну пару")
    mode = str(payload.get("allocation_mode", "AUTO")).upper()
    if mode not in {"AUTO", "MANUAL"}:
        raise HTTPException(400, "allocation_mode: AUTO или MANUAL")
    ledger = PaperLedger(capital)
    return {"ok": True, "mode": "PAPER", "pairs": pairs, "allocation_mode": mode, **ledger.snapshot()}

@app.post("/api/paper/stop")
def paper_stop():
    return {"ok": True, "message": "PAPER остановлен", "status": ledger.snapshot() if ledger else {"running": False}}

@app.post("/api/paper/reset")
def paper_reset():
    global ledger
    ledger = None
    return {"ok": True}

@app.get("/api/ranking")
def ranking():
    # Skeleton endpoint: market adapter will feed real candidates later.
    demo = [Candidate(s, 0.0) for s in ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "SUI/USDT", "TRX/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT"]]
    return {"blocks": [[c.__dict__ for c in b] for b in RankingMatrix().blocks(demo)]}

@app.post("/api/allocation/preview")
def allocation_preview(payload: dict):
    capital = float(payload.get("capital", SETTINGS.default_capital))
    mode = str(payload.get("mode", "AUTO")).upper()
    candidates = [Candidate(str(x["symbol"]), float(x.get("score", 0))) for x in payload.get("candidates", [])][:10]
    if mode == "AUTO":
        allocation = PortfolioAllocation().auto(candidates, capital)
    elif mode == "MANUAL":
        allocation = PortfolioAllocation().manual(payload.get("allocations", {}), capital)
    else:
        raise HTTPException(400, "mode должен быть AUTO или MANUAL")
    return {"mode": mode, "capital": capital, "allocation": allocation}

@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse('''<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FAST SCALPER CLEAN</title><style>body{margin:0;background:#070707;color:#eee;font:16px Arial}.wrap{max-width:900px;margin:auto;padding:18px}.card{border:1px solid #441016;border-radius:14px;padding:16px;margin:10px 0;background:#0b0c0e}.title{color:#ff2630;font-weight:900;font-size:22px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.metric{padding:12px;border:1px solid #333;border-radius:10px}.value{font-size:28px;font-weight:900;margin-top:5px}.green{color:#39e879}@media(max-width:600px){.grid{grid-template-columns:1fr}}</style><main class="wrap"><div class="card"><div class="title">⚡ FAST SCALPER — CLEAN SKELETON</div><p>Новая база. Старые торговые патчи не используются.</p></div><div class="grid"><div class="metric">Капитал<div class="value">100 USDT</div></div><div class="metric">Цель throughput<div class="value green">1.73 USDT/мин / $100</div></div><div class="metric">Рейтинг<div class="value">2 × 5 пар</div></div><div class="metric">Пары<div class="value">до 10</div></div></div><div class="card"><div class="title">📐 МАТРИЦА</div><p>1m / 3m / 5m · AUTO / MANUAL · PAPER-first · PnL по закрытым сделкам за скользящую минуту.</p></div><div class="card"><div class="title">📊 PAPER LEDGER</div><pre id="s">Загрузка…</pre></div><script>async function r(){let x=await fetch('/api/paper/status');document.getElementById('s').textContent=JSON.stringify(await x.json(),null,2)}r();setInterval(r,1000)</script></main></html>''')
