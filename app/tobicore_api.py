from fastapi import FastAPI
from pydantic import BaseModel, Field
from .tobicore_core import MarketSnapshot, HORIZONS, CROSS_MODES, evaluate, run_matrix

app = FastAPI(title="TobiCore", version="1.0")

class SnapshotRequest(BaseModel):
    symbol: str = "BTCUSDT"
    price: float = Field(..., gt=0)
    momentum: float
    trend: float
    volume_ratio: float = 1.0
    spread_bps: float = 0.0

@app.get("/api/health")
def health():
    return {"ok": True, "service": "tobicore", "horizons": list(HORIZONS), "modes": list(CROSS_MODES)}

@app.post("/api/signal")
def signal(req: SnapshotRequest):
    s = MarketSnapshot(req.symbol.upper(), req.price, req.momentum, req.trend, req.volume_ratio, req.spread_bps)
    return {"signals": [evaluate(s, h, m) for h in HORIZONS for m in CROSS_MODES]}

@app.get("/api/matrix")
def matrix(cases_per_horizon: int = 250, repeats: int = 5):
    return run_matrix(cases_per_horizon, repeats)
