from __future__ import annotations

from fastapi.responses import HTMLResponse

from .stable_app import app, CONTROL_HTML

# stable_app intentionally owns the entire control surface. Remove any root
# route inherited from fixed_app and install exactly one normal FastAPI route.
for route in list(app.router.routes):
    if getattr(route, "path", None) == "/":
        app.router.routes.remove(route)


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
