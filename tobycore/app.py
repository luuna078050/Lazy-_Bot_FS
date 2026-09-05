from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from .db import init_db, record_feedback, register_bot, get_stats
from .engine import decide

app = FastAPI(title="Toby Core", version="0.1.0", description="Standalone central decision, memory and feedback API.")

class DecisionRequest(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    features: dict = Field(default_factory=dict)
    source: str = "unknown"

class FeedbackRequest(BaseModel):
    event_id: str
    outcome: str
    reward: float = 0.0
    details: dict = Field(default_factory=dict)

class BotRequest(BaseModel):
    bot_id: str
    bot_type: str
    capabilities: list[str] = Field(default_factory=list)

@app.on_event("startup")
def startup():
    init_db()

@app.get("/health")
def health():
    return {"status": "ok", "service": "toby-core", "version": "0.1.0"}

@app.post("/v1/decide")
def decision(req: DecisionRequest):
    result = decide(req.model_dump())
    return result

@app.post("/v1/feedback")
def feedback(req: FeedbackRequest):
    return record_feedback(req.model_dump())

@app.post("/v1/bots/register")
def bot_register(req: BotRequest, x_api_key: str | None = Header(default=None)):
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="API key required")
    return register_bot(req.model_dump())

@app.get("/v1/memory/stats")
def memory_stats():
    return get_stats()
