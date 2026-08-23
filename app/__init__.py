"""LazyBot FS package bootstrap.

Adds a small Android-friendly control surface to the existing FastAPI app
without changing the trading strategy modules.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

_original_init = FastAPI.__init__


def _patched_init(self: FastAPI, *args: Any, **kwargs: Any) -> None:
    _original_init(self, *args, **kwargs)

    if getattr(self, "_lazybot_control_routes", False):
        return
    self._lazybot_control_routes = True
    self.state.bot_process = None
    self.state.bot_live = False

    @self.get("/", response_class=HTMLResponse, include_in_schema=False)
    def _home() -> str:
        return _CONTROL_HTML

    @self.get("/api/bot/status", include_in_schema=False)
    def _bot_status() -> dict[str, Any]:
        p = self.state.bot_process
        running = bool(p and p.poll() is None)
        return {
            "running": running,
            "mode": "LIVE" if running and self.state.bot_live else "PAPER",
            "pid": p.pid if running else None,
            "exchange": "binance",
        }

    @self.post("/api/bot/start", include_in_schema=False)
    def _bot_start(payload: dict[str, Any]) -> dict[str, Any]:
        p = self.state.bot_process
        if p and p.poll() is None:
            raise HTTPException(status_code=409, detail="Бот уже запущен")

        live = bool(payload.get("live", False))
        capital = float(payload.get("capital", 100))
        pairs = [str(x).strip().upper().replace("-", "/") for x in payload.get("pairs", []) if str(x).strip()]
        alloc = [float(x) for x in payload.get("allocations", [])]
        min_profit = float(payload.get("min_profit", 0.20))
        target_profit = float(payload.get("target_profit", 0.30))
        sl = bool(payload.get("sl", True))

        if capital <= 0 or len(pairs) not in (2, 3) or len(alloc) != len(pairs):
            raise HTTPException(status_code=400, detail="Нужно 2–3 пары и соответствующие доли капитала")
        if abs(sum(alloc) - 100) > 0.01 or any(x <= 0 for x in alloc):
            raise HTTPException(status_code=400, detail="Распределение капитала должно быть ровно 100%")
        if min_profit <= 0 or target_profit < min_profit:
            raise HTTPException(status_code=400, detail="Проверьте минимальный и целевой профит")

        env = os.environ.copy()
        env.update({
            "FAST_SCALPER_CAPITAL_USDT": str(capital),
            "FAST_SCALPER_PAIRS": ",".join(pairs),
            "FAST_SCALPER_ALLOCATIONS": ",".join(str(x) for x in alloc),
            "FAST_SCALPER_MIN_PROFIT_USDT": str(min_profit),
            "FAST_SCALPER_TARGET_PROFIT_USDT": str(target_profit),
            "FAST_SCALPER_STOP_LOSS_ENABLED": "true" if sl else "false",
            "FAST_SCALPER_LIVE": "true" if live else "false",
            "LIVE_TRADING": "true" if live else "false",
            "LIVE_TRADING_ARMED": "true" if live else "false",
            "TRADING_MODE": "live" if live else "paper",
        })

        if live:
            key = str(payload.get("api_key", "")).strip()
            secret = str(payload.get("api_secret", "")).strip()
            if not key or not secret:
                raise HTTPException(status_code=400, detail="Для LIVE нужны Binance API Key и Secret")
            env["BINANCE_API_KEY"] = key
            env["BINANCE_API_SECRET"] = secret
            try:
                import ccxt
                ex = ccxt.binance({"apiKey": key, "secret": secret, "enableRateLimit": True})
                ex.load_markets()
                ex.fetch_balance()
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Binance API не прошёл проверку: {str(exc)[:240]}")

        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "scripts.fast_scalper_3m"],
                cwd=os.getcwd(),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Не удалось запустить скальпер: {exc}")

        self.state.bot_process = proc
        self.state.bot_live = live
        return {"ok": True, "running": True, "mode": "LIVE" if live else "PAPER", "pid": proc.pid}

    @self.post("/api/bot/stop", include_in_schema=False)
    def _bot_stop() -> dict[str, Any]:
        p = self.state.bot_process
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        self.state.bot_process = None
        self.state.bot_live = False
        return {"ok": True, "running": False}


FastAPI.__init__ = _patched_init


_CONTROL_HTML = r'''<!doctype html>
<html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LazyBot FS — Fast Scalper</title>
<style>
body{font-family:system-ui;background:#111827;color:#f5f7fa;max-width:620px;margin:auto;padding:16px}
.card{background:#1f2937;border-radius:16px;padding:16px;margin:12px 0}
input,select{box-sizing:border-box;background:#374151;color:white;border:1px solid #4b5563;border-radius:10px;padding:11px;width:100%;margin:6px 0}
button{border:0;border-radius:11px;padding:13px 16px;font-weight:700;margin:4px 0;width:100%}
.start{background:#22c55e;color:#07130a}.paper{background:#60a5fa;color:#07111f}.stop{background:#ef4444;color:white}
.row{display:grid;grid-template-columns:1fr 90px;gap:8px}.ok{color:#4ade80}.warn{color:#fbbf24}.muted{color:#aeb8c7;font-size:14px}
</style></head><body>
<h1>⚡ LazyBot FS</h1><p class="muted">Fast Scalper 3m • Binance Spot • Android</p>
<div class="card"><h3>Режим</h3>
<button class="paper" onclick="start(false)">▶ PAPER — тест без денег</button>
<button class="start" onclick="start(true)">▶ LIVE — реальные деньги</button>
<button class="stop" onclick="stopBot()">■ Остановить бота</button>
<p id="status">Проверка...</p></div>
<div class="card"><h3>Binance</h3>
<input id="key" placeholder="API Key" autocomplete="off">
<input id="secret" placeholder="Secret Key" type="password" autocomplete="off">
<p class="muted">Ключ используется только для текущего процесса. Не включай Withdrawals. Для LIVE используй Spot Trading + IP restriction.</p></div>
<div class="card"><h3>Капитал бота</h3><input id="capital" type="number" value="100" min="1" step="1"><span>USDT</span></div>
<div class="card"><h3>Пары и доли</h3>
<div class="row"><input id="p1" value="DGB/USDT"><input id="a1" value="30" type="number"></div>
<div class="row"><input id="p2" value="ZRO/USDT"><input id="a2" value="30" type="number"></div>
<div class="row"><input id="p3" value="TUT/USDT"><input id="a3" value="40" type="number"></div>
<p class="muted">2–3 пары. Доли автоматически должны дать 100%.</p></div>
<div class="card"><h3>Профит</h3>
<label>Минимальный net<input id="minp" value="0.20" type="number" step="0.01"></label>
<label>Целевой net<input id="target" value="0.30" type="number" step="0.01"></label>
<label><input id="sl" type="checkbox" checked style="width:auto"> Ограничение убытка (SL)</label></div>
<div class="card"><h3>Обмен валюты</h3>
<p class="muted">Архитектура quote-agnostic: бот работает с USDT/USDC/EUR и другими котировками, если Binance предоставляет соответствующий рынок. Если прямой пары нет, конвертация не будет выдумываться.</p></div>
<script>
async function status(){try{let r=await fetch('/api/bot/status');let d=await r.json();document.getElementById('status').innerHTML=d.running?'🟢 Бот работает: <b>'+d.mode+'</b>':'⚪ Бот остановлен'}catch(e){document.getElementById('status').textContent='Ошибка связи'}}
function cfg(){return {capital:+capital.value,pairs:[p1.value,p2.value,p3.value].filter(Boolean),allocations:[+a1.value,+a2.value,+a3.value].slice(0,[p1.value,p2.value,p3.value].filter(Boolean).length),min_profit:+minp.value,target_profit:+target.value,sl:sl.checked}}
async function start(live){let c=cfg();c.live=live;if(live){c.api_key=key.value;c.api_secret=secret.value;if(!c.api_key||!c.api_secret){alert('Для LIVE введи Binance API Key и Secret');return}}let r=await fetch('/api/bot/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c)});let d=await r.json();if(!r.ok){alert(d.detail||'Ошибка запуска');return}alert('Запущено: '+d.mode);status()}
async function stopBot(){await fetch('/api/bot/stop',{method:'POST'});status()}
status();setInterval(status,5000)
</script></body></html>'''
