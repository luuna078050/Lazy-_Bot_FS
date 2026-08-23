from __future__ import annotations

# Keep Render cold-start fast. The market radar starts lazily on the first
# recommendation/PAPER request and then stays on one Binance WebSocket.
import threading
_original_thread_start = threading.Thread.start

def _defer_radar_start(self, *args, **kwargs):
    name = getattr(self, 'name', '')
    if name in {'fast-scalper-market-radar', 'radar-boot-check'}:
        return
    return _original_thread_start(self, *args, **kwargs)

threading.Thread.start = _defer_radar_start
try:
    from .ui_v5 import app
    from .paper_mode_patch import install as _install_paper_mode
    from .allocation_fix_patch import install as _install_allocation_fix
    _install_paper_mode(app)
    _install_allocation_fix(app)
finally:
    threading.Thread.start = _original_thread_start
