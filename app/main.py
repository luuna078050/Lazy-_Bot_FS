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
    from .ui_v8 import app
    from .paper_mode_patch import install as _install_paper_mode
    from .allocation_fix_patch import install as _install_allocation_fix
    from .report_v6_patch import install as _install_report_v6
    from .account_balance_patch import install as _install_account_balance
    from .report_v7_patch import install as _install_report_v7
    from .ui_controls_patch import install as _install_ui_controls
    from .paper_api_v3_patch import install as _install_paper_api_v3
    from .ui_pair_fix_patch import install as _install_ui_pair_fix
    _install_paper_mode(app)
    _install_allocation_fix(app)
    _install_report_v6()
    _install_account_balance()
    _install_report_v7()
    _install_ui_controls(app)
    _install_paper_api_v3(app)
    _install_ui_pair_fix(app)
finally:
    threading.Thread.start = _original_thread_start
