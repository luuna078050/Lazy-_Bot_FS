from __future__ import annotations

# Fast Scalper stays live continuously. MarketRadar owns the persistent
# Binance public WebSocket feed and reconnects automatically.
from .ui_v10 import app
from .paper_mode_patch import install as _install_paper_mode
from .allocation_fix_patch import install as _install_allocation_fix
from .report_v6_patch import install as _install_report_v6
from .account_balance_patch import install as _install_account_balance
from .report_v7_patch import install as _install_report_v7
from .ui_controls_patch import install as _install_ui_controls
from .profit_gate_patch import install as _install_profit_gate
from .paper_api_v3_patch import install as _install_paper_api_v3
from .ui_pair_fix_patch import install as _install_ui_pair_fix
from .multi_slot_backend_patch import install as _install_multi_slot
from .final_ui_patch import install as _install_final_ui
from .final_ui_v13_patch import install as _install_final_ui_v13
from .reinvest_ui_patch import install as _install_reinvest_ui
from .reinvest_engine_patch import install as _install_reinvest_engine
from .recent_ui_patch import install as _install_recent_ui
from .paper_persistence_patch import install as _install_paper_persistence
from .final_fix_v14_patch import install as _install_final_fix_v14

_install_paper_mode(app)
_install_allocation_fix(app)
_install_report_v6()
_install_account_balance()
_install_report_v7()
_install_ui_controls(app)
_install_profit_gate()
_install_paper_api_v3(app)
_install_ui_pair_fix(app)
_install_multi_slot(app)
_install_reinvest_engine()
_install_paper_persistence()
_install_final_ui(app)
_install_final_ui_v13(app)
_install_reinvest_ui(app)
_install_recent_ui(app)
_install_final_fix_v14(app)
