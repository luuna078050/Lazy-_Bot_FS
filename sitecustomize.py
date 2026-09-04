"""Compatibility bootstrap for the Render start command.

The actual integrations live in app.integration and app.balance_overlay.
This file only loads them because Render starts uvicorn directly from app.main.
"""

try:
    import app.main as _main
    from app import balance_overlay as _balance_overlay
    from app import integration as _integration

    _balance_overlay.install(_main)
    _integration.install(_main)
except Exception as exc:
    # Never prevent Fast Scalper from starting if an optional integration is down.
    print(f"[integration] bootstrap warning: {type(exc).__name__}: {exc}")
