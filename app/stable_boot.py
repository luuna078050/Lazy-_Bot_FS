from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from .stable_app import app, CONTROL_HTML, _paper_report, _live_report

# stable_app owns the control surface. Remove inherited root/report routes and
# install exactly one authoritative implementation for each.
for route in list(app.router.routes):
    if getattr(route, "path", None) in {"/", "/api/session/report/{mode}"}:
        app.router.routes.remove(route)


@app.get("/api/session/report/{mode}")
def session_report(mode: str):
    mode = mode.upper()
    if mode == "PAPER":
        return _paper_report()
    if mode == "LIVE":
        return _live_report()
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
