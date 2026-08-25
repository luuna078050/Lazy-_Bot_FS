"""Fast Scalper runtime safety shim."""
import sys
try:
    from app import paper_engine_ws
    sys.modules['app.paper_engine'] = paper_engine_ws
    from app import session_recovery_hot_replace_patch
    session_recovery_hot_replace_patch.install(paper_engine_ws)
    from app import fixed_app
    from app import session_ui_patch
    session_ui_patch.install(fixed_app)
except Exception:
    pass
