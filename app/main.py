import os
from datetime import datetime, timezone
from fastapi import FastAPI
from .forecast import HORIZONS_MIN, validate_horizon, forecast_targets
from .matrix_test import run_matrix

app = FastAPI(title="LazyBot FS", version="0.3.0")


def paper_config():
    return {
        "max_position_usdt": float(os.getenv("MAX_POSITION_USDT", 5)),
        "risk_per_trade_usdt": float(os.getenv("RISK_PER_TRADE_USDT", 1)),
        "daily_loss_limit_usdt": float(os.getenv("DAILY_LOSS_LIMIT_USDT", 3)),
        "leverage": int(os.getenv("LEVERAGE", 5)),
        "take_profit_pct": float(os.getenv("TAKE_PROFIT_PCT", 0.6)),
        "stop_loss_pct": float(os.getenv("STOP_LOSS_PCT", 0.3)),
    }


@app.get("/api/health")
def health():
    return {"ok": True, "project": "LazyBot FS", "mode": os.getenv("TRADING_MODE", "paper"), "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/status")
def status():
    return {"project": "LazyBot FS", "strategy": "Fast Scalper", "mode": os.getenv("TRADING_MODE", "paper"), "symbol": os.getenv("SYMBOL", "BTC/USDT:USDT"), "forecast_horizons_min": list(HORIZONS_MIN), "risk": paper_config(), "live_trading": False}


@app.get("/api/paper-test")
def paper_test(price: float = 100.0, predicted_return_pct: float = 0.1):
    targets = forecast_targets(price, predicted_return_pct)
    return {"ok": True, "mode": "paper", "horizons_min": list(HORIZONS_MIN), "targets": {str(h): targets[h] for h in HORIZONS_MIN}, "all_horizons_valid": all(validate_horizon(h) == h for h in HORIZONS_MIN), "live_trading": False}


@app.get("/api/paper-test/matrix")
def paper_test_matrix():
    return run_matrix()
