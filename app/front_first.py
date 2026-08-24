from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Fast Scalper Front First")

HTML = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Fast Scalper</title>
<style>
:root{--bg:#0b0b0d;--card:#141418;--line:#3a1118;--red:#ff2635;--gold:#ffbd16;--muted:#a6a6ad;--green:#19d66b;--blue:#3e8cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f5f5f7;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:720px;margin:auto;padding:14px}.brand{border:1px solid #64111a;border-radius:22px;padding:24px 20px;background:radial-gradient(circle at 80% 15%,#571017,transparent 55%),#08090b;box-shadow:0 0 30px #2b090d inset}.bolt{font-size:46px}.brand h1{margin:0;font-size:42px;letter-spacing:-2px;color:#fff}.brand h1 b{color:var(--red)}.brand p{margin:5px 0 18px;font-size:18px;color:#d0b58e}.mode{display:flex;align-items:center;gap:10px;color:var(--gold);font-weight:800}.switch{width:68px;height:34px;border-radius:20px;background:#292a2f;border:1px solid #666;display:inline-flex;align-items:center;padding:4px}.dot{width:25px;height:25px;border-radius:50%;background:#777}.card{margin-top:14px;border:1px solid var(--line);border-radius:20px;background:var(--card);padding:16px}.title{font-size:21px;font-weight:900;color:var(--red);margin-bottom:12px}.pnl{font-size:43px;font-weight:900}.muted{color:var(--muted)}.balance{border:1px solid #72580d;border-radius:14px;padding:13px;margin-top:12px;background:#12110d}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.panel{border:1px solid #41101a;border-radius:15px;padding:12px;background:#0d0e11}.panel h3{margin:0 0 8px}.btn{width:100%;border:0;border-radius:12px;padding:13px;font-size:16px;font-weight:900;margin-top:8px;background:#292a2f;color:white}.btn.green{background:#12a952}.btn.red{background:#c81e2b}.btn.gold{background:#5d4800;color:#ffd44a}.input{width:100%;background:#101114;color:#fff;border:1px solid #3a3b42;border-radius:10px;padding:13px;font-size:17px}.row{display:grid;grid-template-columns:1fr 90px;gap:8px;margin:8px 0}.pair{display:flex;align-items:center;justify-content:space-between;padding:12px;border:1px solid #40101a;border-radius:12px;margin:8px 0}.tag{padding:6px 9px;border-radius:9px;background:#173f29;color:#48ef91;font-weight:800}.empty{color:#777;padding:10px 0}.footer{color:#666;text-align:center;padding:18px 0;font-size:12px}
@media(max-width:480px){.brand h1{font-size:34px}.pnl{font-size:36px}.grid{grid-template-columns:1fr}.row{grid-template-columns:1fr 80px}}
</style></head>
<body><main class="wrap">
<section class="brand"><div class="bolt">⚡</div><h1>FAST <b>SCALPER</b></h1><p>ЛОВИМ РАКЕТЫ НА ВЗЛЁТЕ</p><div class="mode">PAPER MODE <span class="switch"><span class="dot"></span></span><span class="muted">без реальных активов</span></div></section>
<section class="card"><div class="title">PnL СЕГОДНЯ</div><div class="pnl">0.0000 USDT</div><div class="muted">(0.00%)</div><div class="balance">💼 БАЛАНС АККАУНТА<br><b style="font-size:24px">100.0000 USDT</b></div><div class="grid" style="margin-top:10px"><div>Realized PnL<br><b>0.0000</b></div><div>Unrealized PnL<br><b>0.0000</b></div></div></section>
<section class="card"><div class="title">🚀 ТОП ПАРЫ · РЕЙТИНГ СИГНАЛОВ</div><div class="pair"><span>#1 BTC/USDT <span class="muted">NORMAL · 180s</span></span><span class="tag">ВЫБРАТЬ</span></div><div class="pair"><span>#2 ETH/USDT <span class="muted">NORMAL · 180s</span></span><span class="tag">ВЫБРАТЬ</span></div><div class="pair"><span>#3 SOL/USDT <span class="muted">NORMAL · 180s</span></span><span class="tag">ВЫБРАТЬ</span></div><div class="empty">Радар подключается — интерфейс не зависит от его обновлений.</div></section>
<section class="card"><div class="title">⚙️ РЕЖИМ РАБОТЫ</div><div class="grid"><button class="btn gold">1m</button><button class="btn">3m</button><button class="btn">5m</button><button class="btn">NORMAL</button></div></section>
<section class="card"><div class="title">⚡ УПРАВЛЕНИЕ</div><div class="grid"><div class="panel"><h3>PAPER</h3><button class="btn green">▶ ЗАПУСТИТЬ PAPER</button><button class="btn red">■ STOP PAPER</button></div><div class="panel"><h3>LIVE</h3><button class="btn">▶ ЗАПУСТИТЬ LIVE</button><button class="btn red">■ STOP LIVE</button><button class="btn red">⛔ EMERGENCY</button></div></div></section>
<section class="card"><div class="title">⚙️ НАСТРОЙКИ СЕССИИ</div><label class="muted">Выделенный баланс бота</label><input class="input" value="100" inputmode="decimal"><div class="row"><input class="input" value="BTC/USDT"><input class="input" value="40"></div><div class="row"><input class="input" value="ETH/USDT"><input class="input" value="35"></div><div class="row"><input class="input" value="SOL/USDT"><input class="input" value="25"></div><button class="btn">ОЧИСТИТЬ</button></section>
<section class="card"><div class="title">📊 ПОЗИЦИИ И СДЕЛКИ</div><div class="empty">Открытые позиции: 0</div><div class="empty">Закрытые сделки: 0</div><div class="empty">Отчёт: ожидает подключения торгового ядра</div></section>
<div class="footer">FAST SCALPER · FRONT-FIRST BASE · PAPER FIRST</div>
</main></body></html>'''

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(HTML, headers={"Cache-Control":"no-store, max-age=0"})

@app.get("/api/health")
def health():
    return {"ok": True, "project": "Fast Scalper", "stage": "front-first"}
'''
