from __future__ import annotations

import json
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from .stable_app import app, CONTROL_HTML, _paper_report
from . import fixed_app as core

for route in list(app.router.routes):
    if getattr(route, "path", None) in {"/", "/api/session/report/{mode}"}:
        app.router.routes.remove(route)


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
        return _paper_report()
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
