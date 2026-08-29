from __future__ import annotations

from fastapi.responses import HTMLResponse

# The stable Fast Scalper implementation contains the intended control surface,
# radar, timers, PnL telemetry, 10 slots and PAPER/LIVE wiring.  Its only
# deployment defect was a hand-made Starlette route object that newer Starlette
# versions cannot match.  Import it, remove that object, and register a normal
# FastAPI route instead of changing the stable UI/engine.
from . import stable_app as _stable

app = _stable.app

for _route in list(app.router.routes):
    if _route.__class__.__name__ == "StableRoute":
        app.router.routes.remove(_route)

@app.get("/", response_class=HTMLResponse)
def home():
    html = _stable.CONTROL_HTML.replace('value="100"', 'value="50"', 1)
    return HTMLResponse(html, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })
