import os
from fastapi import FastAPI
from dotenv import load_dotenv
from .core.risk import RiskConfig, RiskEngine
from .core.scalper import FastScalper
from .integrations.pchelka import PchelkaClient

load_dotenv()
app = FastAPI(title="LazyBot FS", version="0.1.0")
risk = RiskEngine(RiskConfig(
    max_position_usdt=float(os.getenv("MAX_POSITION_USDT", 5)),
    risk_per_trade_usdt=float(os.getenv("RISK_PER_TRADE_USDT", 1)),
    daily_loss_limit_usdt=float(os.getenv("DAILY_LOSS_LIMIT_USDT", 3)),
    leverage=int(os.getenv("LEVERAGE", 5)),
    take_profit_pct=float(os.getenv("TAKE_PROFIT_PCT", .006)),
    stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", .003)),
    trailing_stop_pct=float(os.getenv("TRAILING_STOP_PCT", .002)),
    breakeven_trigger_pct=float(os.getenv("BREAKEVEN_TRIGGER_PCT", .003)),
))
pchelka = PchelkaClient()
scalper = FastScalper(risk, pchelka)

@app.get("/api/health")
def health():
    return {"ok": True, "project": "LazyBot FS", "mode": os.getenv("TRADING_MODE", "paper"), "pchelka": bool(pchelka.base_url), "trading_halted": risk.state.halted}

@app.get("/api/status")
def status():
    return {"project":"LazyBot FS", "fs":"Fast Scalper", "mode":os.getenv("TRADING_MODE","paper"), "symbol":os.getenv("SYMBOL","BTC/USDT:USDT"), "leverage":risk.config.leverage, "max_position_usdt":risk.config.max_position_usdt, "daily_loss_limit_usdt":risk.config.daily_loss_limit_usdt, "pchelka_connected":bool(pchelka.base_url)}
