from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI(title="Fast Scalper Test Skeleton", version="0.1-test")
_lock = Lock()


@dataclass
class Position:
    id: str
    pair: str
    allocation_pct: float
    allocated_usdt: float
    entry_price: float
    last_price: float
    amount: float
    opened_at: float
    fee_pct: float = 0.10
    target_pct: float = 0.35
    stop_pct: float = 0.50
    max_hold_sec: int = 180
    signal: str = "NORMAL"

    def unrealized(self) -> float:
        gross = (self.last_price - self.entry_price) * self.amount
        fee = (self.entry_price * self.amount + self.last_price * self.amount) * self.fee_pct / 100
        return gross - fee


STATE: dict[str, Any] = {
    "running": False,
    "mode": "PAPER_TEST",
    "capital": 100.0,
    "available": 100.0,
    "realized_pnl": 0.0,
    "closed_trades": [],
    "positions": {},
    "orders": [],
    "events": [],
    "selected_pairs": [],
    "allocations": [],
    "started_at": None,
}


def _event(kind: str, **data: Any) -> None:
    STATE["events"].append({"ts": time.time(), "kind": kind, **data})
    STATE["events"] = STATE["events"][-200:]


def _clean_pair(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "/")


def reset() -> dict[str, Any]:
    with _lock:
        STATE.update({
            "running": False,
            "mode": "PAPER_TEST",
            "capital": 100.0,
            "available": 100.0,
            "realized_pnl": 0.0,
            "closed_trades": [],
            "positions": {},
            "orders": [],
            "events": [],
            "selected_pairs": [],
            "allocations": [],
            "started_at": None,
        })
        _event("RESET")
        return report()


def configure(payload: dict[str, Any]) -> dict[str, Any]:
    capital = float(payload.get("capital", 0))
    pairs = [_clean_pair(x) for x in payload.get("pairs", []) if _clean_pair(x)]
    alloc = [float(x) for x in payload.get("allocations", [])]
    if not 1 <= len(pairs) <= 5:
        raise HTTPException(400, "Выберите от 1 до 5 пар")
    if len(set(pairs)) != len(pairs):
        raise HTTPException(400, "Пары не должны повторяться")
    if len(alloc) != len(pairs) or any(x <= 0 for x in alloc) or abs(sum(alloc) - 100) > 0.001:
        raise HTTPException(400, "Распределение должно дать ровно 100%")
    if capital <= 0:
        raise HTTPException(400, "Капитал должен быть больше 0")
    with _lock:
        STATE["capital"] = capital
        STATE["available"] = capital
        STATE["selected_pairs"] = pairs
        STATE["allocations"] = alloc
        STATE["running"] = False
        STATE["positions"] = {}
        STATE["closed_trades"] = []
        STATE["realized_pnl"] = 0.0
        STATE["orders"] = []
        STATE["started_at"] = None
        _event("CONFIGURED", pairs=pairs, allocations=alloc, capital=capital)
        return report()


def start() -> dict[str, Any]:
    with _lock:
        if not STATE["selected_pairs"]:
            raise HTTPException(400, "Сначала выберите пары и распределение")
        STATE["running"] = True
        STATE["started_at"] = time.time()
        _event("START", pairs=STATE["selected_pairs"])
        return report()


def close_position(pair: str, reason: str) -> None:
    pos = STATE["positions"].pop(pair, None)
    if not pos:
        return
    net = pos.unrealized()
    STATE["available"] += pos.allocated_usdt + net
    STATE["realized_pnl"] += net
    trade = asdict(pos)
    trade.update({"exit_price": pos.last_price, "net_pnl": net, "reason": reason, "closed_at": time.time()})
    STATE["closed_trades"].append(trade)
    _event("TRADE_CLOSED", pair=pair, reason=reason, net_pnl=net)


def tick(payload: dict[str, Any]) -> dict[str, Any]:
    prices = { _clean_pair(k): float(v) for k, v in (payload.get("prices") or {}).items() }
    with _lock:
        if not STATE["running"]:
            raise HTTPException(400, "PAPER_TEST не запущен")
        now = time.time()
        for i, pair in enumerate(STATE["selected_pairs"]):
            price = prices.get(pair)
            if not price or price <= 0:
                continue
            pos = STATE["positions"].get(pair)
            if pos:
                pos.last_price = price
                age = now - pos.opened_at
                if pos.unrealized() >= pos.allocated_usdt * pos.target_pct / 100:
                    close_position(pair, "TARGET")
                elif pos.unrealized() <= -pos.allocated_usdt * pos.stop_pct / 100:
                    close_position(pair, "STOP_LOSS")
                elif age >= pos.max_hold_sec:
                    close_position(pair, "TIMEOUT")
                continue
            allocation_pct = STATE["allocations"][i]
            allocated = STATE["capital"] * allocation_pct / 100
            if STATE["available"] + 1e-9 < allocated:
                _event("SKIP_NO_CAPITAL", pair=pair, required=allocated)
                continue
            amount = allocated / price
            STATE["available"] -= allocated
            STATE["positions"][pair] = Position(
                id=str(uuid.uuid4()), pair=pair, allocation_pct=allocation_pct,
                allocated_usdt=allocated, entry_price=price, last_price=price,
                amount=amount, opened_at=now,
            )
            STATE["orders"].append({"id": str(uuid.uuid4()), "pair": pair, "side": "BUY", "price": price, "cost": allocated, "ts": now})
            _event("POSITION_OPENED", pair=pair, price=price, allocation_pct=allocation_pct)
        return report()


def stop() -> dict[str, Any]:
    with _lock:
        STATE["running"] = False
        _event("STOP")
        return report()


def emergency() -> dict[str, Any]:
    with _lock:
        for pair in list(STATE["positions"]):
            close_position(pair, "EMERGENCY_STOP")
        STATE["running"] = False
        _event("EMERGENCY_STOP")
        return report()


def report() -> dict[str, Any]:
    positions = []
    unrealized = 0.0
    for p in STATE["positions"].values():
        u = p.unrealized()
        unrealized += u
        item = asdict(p)
        item["unrealized_pnl"] = u
        item["age_sec"] = max(0, time.time() - p.opened_at)
        positions.append(item)
    return {
        "running": STATE["running"],
        "mode": STATE["mode"],
        "capital": STATE["capital"],
        "available": STATE["available"],
        "realized_pnl": STATE["realized_pnl"],
        "unrealized_pnl": unrealized,
        "net_pnl": STATE["realized_pnl"] + unrealized,
        "selected_pairs": STATE["selected_pairs"],
        "allocations": STATE["allocations"],
        "positions": positions,
        "closed_trades": STATE["closed_trades"][-100:],
        "orders": STATE["orders"][-100:],
        "events": STATE["events"][-100:],
    }


@app.get("/api/test/report")
def api_report():
    with _lock:
        return report()


@app.post("/api/test/reset")
def api_reset():
    return reset()


@app.post("/api/test/configure")
def api_configure(payload: dict[str, Any]):
    return configure(payload)


@app.post("/api/test/start")
def api_start():
    return start()


@app.post("/api/test/tick")
def api_tick(payload: dict[str, Any]):
    return tick(payload)


@app.post("/api/test/stop")
def api_stop():
    return stop()


@app.post("/api/test/emergency")
def api_emergency():
    return emergency()


@app.get("/api/health")
def health():
    return {"ok": True, "project": "Fast Scalper", "mode": "PAPER_TEST", "deterministic": True}


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("""<!doctype html><html lang='ru'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Fast Scalper — TEST</title><style>body{font-family:system-ui;background:#111;color:#eee;max-width:760px;margin:auto;padding:16px}.card{background:#1d1d22;border:1px solid #444;border-radius:14px;padding:14px;margin:10px 0}input,button{font-size:16px;padding:10px;margin:4px 0;border-radius:8px;border:1px solid #555}input{background:#111;color:#fff;width:100%;box-sizing:border-box}button{width:100%;font-weight:700}.ok{background:#176b3a;color:white}.warn{background:#7b1e1e;color:white}.grid{display:grid;grid-template-columns:2fr 1fr;gap:8px}.mono{font-family:monospace;white-space:pre-wrap;font-size:12px}</style><h1>⚡ Fast Scalper — TEST SKELETON</h1><div class='card'><b>Только PAPER_TEST.</b><br>Никаких реальных ордеров. Здесь проверяем связи: пары → капитал → позиция → цена → PnL → закрытие → отчёт.</div><div class='card'><h3>Конфигурация</h3><input id='cap' type='number' value='100'><div id='pairs'></div><button onclick='configure()'>СОХРАНИТЬ КОНФИГ</button></div><div class='card'><button class='ok' onclick='start()'>▶ START TEST</button><button onclick='tick()'>⏱ TICK — ИЗМЕНИТЬ ЦЕНЫ</button><button onclick='stop()'>■ STOP</button><button class='warn' onclick='emergency()'>⛔ EMERGENCY</button><button onclick='reset()'>RESET</button></div><div class='card'><h3>REPORT</h3><div id='out' class='mono'>—</div></div><script>const ps=['BTC/USDT','ETH/USDT','SOL/USDT','XRP/USDT','DOGE/USDT'];document.getElementById('pairs').innerHTML=ps.map((p,i)=>`<div class='grid'><input id='p${i}' value='${i<3?p:''}'><input id='a${i}' type='number' value='${i<3?[40,35,25][i]:0}'></div>`).join('');async function call(u,m='POST',b){let r=await fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});let d=await r.json();if(!r.ok)alert(d.detail||'ERROR');show(d);return d}function cfg(){let a=[];for(let i=0;i<5;i++){let p=document.getElementById('p'+i).value.trim(),x=+document.getElementById('a'+i).value;if(p&&x>0)a.push([p,x])}return{capital:+document.getElementById('cap').value,pairs:a.map(x=>x[0]),allocations:a.map(x=>x[1])}}function configure(){return call('/api/test/configure','POST',cfg())}function start(){return call('/api/test/start')}function tick(){let d={prices:{'BTC/USDT':101,'ETH/USDT':201,'SOL/USDT':101,'XRP/USDT':1.01,'DOGE/USDT':0.101}};return call('/api/test/tick','POST',d)}function stop(){return call('/api/test/stop')}function emergency(){return call('/api/test/emergency')}function reset(){return call('/api/test/reset')}async function load(){show(await call('/api/test/report','GET'))}function show(d){document.getElementById('out').textContent=JSON.stringify(d,null,2)}load()</script></html>""")
