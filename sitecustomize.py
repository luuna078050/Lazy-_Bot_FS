"""Fast Scalper runtime safety shim.

Python imports sitecustomize automatically when the project root is on sys.path.
Alias the legacy REST-polling PAPER engine to the WebSocket-only implementation
before FastAPI imports app.fixed_app/app.ui_v2.
"""
import sys
try:
    from app import paper_engine_ws
    sys.modules['app.paper_engine'] = paper_engine_ws
except Exception:
    # Keep normal startup behavior if the optional WebSocket dependency is unavailable.
    pass
