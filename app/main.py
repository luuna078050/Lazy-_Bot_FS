from __future__ import annotations

# Canonical Fast Scalper surface: stable_app + native FastAPI root route.
from .stable_app import app, CONTROL_HTML
from fastapi.responses import HTMLResponse

# New UI state namespace intentionally resets stale browser-local pair selections
# from previous builds. Existing selections must never survive a fresh deployment.
CONTROL_HTML = CONTROL_HTML.replace('fsStableSlotsV1', 'fsStableSlotsV2').replace('fsStableRankingV1', 'fsStableRankingV2')

# stable_app historically appended a lightweight route-like object. Starlette
# requires real BaseRoute/APIRoute objects, so replace that compatibility shim
# with a native FastAPI route before requests arrive.
for _r in list(app.router.routes):
    if type(_r).__name__ == 'StableRoute':
        app.router.routes.remove(_r)

@app.get('/', response_class=HTMLResponse)
def fast_scalper_root():
    return HTMLResponse(CONTROL_HTML, headers={
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        'Pragma': 'no-cache',
        'Expires': '0',
    })
