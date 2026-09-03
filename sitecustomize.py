try:
    import app.main as _fast_scalper_main
    from app import balance_overlay as _balance_overlay
    _balance_overlay.install(_fast_scalper_main)
except Exception:
    pass
