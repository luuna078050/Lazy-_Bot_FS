from __future__ import annotations

from fastapi import HTTPException
from . import fixed_app as core
from .profit_first_engine_v2 import start_paper, stop_paper, emergency_stop_paper, snapshot


def _remove(path: str) -> None:
    for route in list(core.app.router.routes):
        if getattr(route, 'path', None) == path and getattr(route, 'methods', None):
            core.app.router.routes.remove(route)


def install(app):
    _remove('/api/paper/start')
    _remove('/api/paper/stop')
    _remove('/api/paper/emergency-stop')
    _remove('/api/paper/status')

    @app.post('/api/paper/start')
    def paper_start_v5(payload: dict):
        try:
            return start_paper(payload)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'PAPER engine error: {str(exc)[:240]}')

    @app.post('/api/paper/stop')
    def paper_stop_v5():
        return stop_paper()

    @app.post('/api/paper/emergency-stop')
    def paper_emergency_v5():
        return emergency_stop_paper()

    @app.get('/api/paper/status')
    def paper_status_v5():
        return snapshot()
