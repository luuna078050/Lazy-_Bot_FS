import os
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from .forecast import HORIZONS_MIN, validate_horizon, forecast_targets
from .cross_validation import run_matrix
from .exchange_gateway import configured_exchange_ids, gateway, choose_best_spot
from .transfer_router import plan_cross_exchange

app = FastAPI(title="LazyBot FS", version="0.4.0")


def paper_config():
    return {
        "max_position_usdt": float(os.getenv("MAX_POSITION_USDT", 5)),
        "risk_per_trade_usdt": float(os.getenv("RISK_PER_TRADE_USDT", 1)),
        "daily_loss_limit_usdt": float(os.getenv("DAILY_LOSS_LIMIT_USDT", 3)),
        "leverage": int(os.getenv("LEVERAGE", 1)),
        "take_profit_pct": float(os.getenv("TAKE_PROFIT_PCT", 0.6)),
        "stop_loss_pct": float(os.getenv("STOP_LOSS_PCT", 0.3)),
    }

@app.get("/api/health")
def health():
    return {"ok": True, "project": "LazyBot FS", "mode": os.getenv("TRADING_MODE", "paper"), "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/status")
def status():
    return {
        "project": "LazyBot FS",
        "strategy": "Fast Scalper",
        "mode": os.getenv("TRADING_MODE", "paper"),
        "exchanges": configured_exchange_ids(),
        "symbol": os.getenv("SYMBOL", "BTC/USDT"),
        "forecast_horizons_min": list(HORIZONS_MIN),
        "risk": paper_config(),
        "live_trading": os.getenv("LIVE_TRADING", "false").lower() == "true" and os.getenv("LIVE_TRADING_ARMED", "false").lower() == "true",
        "live_transfers": os.getenv("LIVE_TRANSFER_ARMED", "false").lower() == "true",
    }

@app.get("/api/paper-test")
def paper_test(price: float = 100.0, predicted_return_pct: float = 0.1):
    targets = forecast_targets(price, predicted_return_pct)
    return {"ok": True, "mode": "paper", "horizons_min": list(HORIZONS_MIN), "targets": {str(h): targets[h] for h in HORIZONS_MIN}, "all_horizons_valid": all(validate_horizon(h) == h for h in HORIZONS_MIN), "live_trading": False}

@app.get("/api/paper-test/matrix")
def paper_test_matrix():
    return run_matrix()

@app.get("/api/exchanges/capabilities")
def exchange_capabilities():
    result = {}
    for eid in configured_exchange_ids():
        try:
            result[eid] = gateway(eid).public_capabilities()
        except Exception as exc:
            result[eid] = {"exchange": eid, "available": False, "error": str(exc)[:300]}
    return result

@app.get("/api/exchanges/preflight")
def exchange_preflight(symbol: str):
    result = {}
    for eid in configured_exchange_ids():
        try:
            result[eid] = gateway(eid).account_preflight(symbol)
        except Exception as exc:
            result[eid] = {"exchange": eid, "eligible": False, "errors": [str(exc)[:300]]}
    return result

@app.get("/api/exchanges/route")
def exchange_route(symbol: str):
    return {"symbol": symbol, "venues": choose_best_spot(configured_exchange_ids(), symbol)}

@app.get("/api/transfers/plan")
def transfer_plan(symbol_buy: str, symbol_sell: str, asset: str, source_exchange: str, destination_exchange: str, amount: float):
    try:
        return plan_cross_exchange(symbol_buy, symbol_sell, asset, source_exchange, destination_exchange, amount)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
