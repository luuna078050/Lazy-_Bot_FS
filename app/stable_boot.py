from __future__ import annotations

import json
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from .stable_app import app, CONTROL_HTML, snapshot
from . import fixed_app as core

for route in list(app.router.routes):
    if getattr(route, "path", None) in {"/", "/api/session/report/{mode}"}:
        app.router.routes.remove(route)


def _paper_report_authoritative():
    s = snapshot()
    return {
        "mode": "PAPER", "running": bool(s.get("running")),
        "started_at": s.get("started_at"), "stopped_at": s.get("stopped_at"),
        "initial_balance": float(s.get("initial_balance", 0) or 0),
        "account_balance_usdt": float(s.get("account_balance_usdt", 0) or 0),
        "bot_balance_usdt": float(s.get("initial_balance", 0) or 0),
        "free_usdt": float(s.get("free_usdt", 0) or 0),
        "equity_usdt": float(s.get("equity_usdt", 0) or 0),
        "realized_pnl": float(s.get("realized_pnl", 0) or 0),
        "unrealized_pnl": float(s.get("unrealized_pnl", 0) or 0),
        "net_pnl": float(s.get("net_pnl", 0) or 0),
        "positions": list((s.get("open_positions") or {}).values()),
        "orders": list((s.get("orders") or {}).values()),
        "order_history": list(s.get("order_history") or [])[-50:],
        "trades": list(s.get("trades") or [])[-50:],
        "config": s.get("config") or {}, "error": s.get("error"),
        "stop_type": s.get("stop_type"),
    }


def _live_report_authoritative():
    try:
        state = json.loads(core.LIVE_STATE.read_text()) if core.LIVE_STATE.exists() else {}
    except Exception:
        state = {}
    with core.LIVE_LOCK:
        state["running"] = bool(core.LIVE_PROC and core.LIVE_PROC.poll() is None)
    state["mode"] = "LIVE"
    state.setdefault("positions", [])
    state.setdefault("trades", [])
    state.setdefault("orders", {})
    return state


@app.get("/api/session/report/{mode}")
def session_report(mode: str):
    mode = mode.upper()
    if mode == "PAPER":
        return _paper_report_authoritative()
    if mode == "LIVE":
        return _live_report_authoritative()
    raise HTTPException(400, "Unknown mode")


@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(
        CONTROL_HTML,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
