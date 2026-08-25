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
from .final_ui_patch import install as _install_final_ui

_install_paper_mode(app)
_install_allocation_fix(app)
_install_report_v6()
_install_account_balance()
_install_report_v7()
_install_ui_controls(app)
_install_profit_gate()
_install_paper_api_v3(app)
_install_ui_pair_fix(app)
_install_final_ui(app)
