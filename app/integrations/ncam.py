from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MarketCandidate:
    symbol: str
    safety_score: float
    profit_score: float
    volatility_score: float = 0.0
    liquidity_score: float = 0.0
    correlation_score: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)


class NcamClient:
    """Research/search adapter for the NCAM/Bee-derived search layer.

    Research only: it never places, changes, or closes an order.
    The adapter accepts normalized evidence from existing Bee/Pchelka search
    segments and exposes a stable interface to Lazy strategies.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url

    async def rank_candidates(self, candidates: List[MarketCandidate], limit: int = 10) -> List[MarketCandidate]:
        ranked = sorted(
            candidates,
            key=lambda x: (0.45 * x.safety_score + 0.35 * x.profit_score
                           + 0.10 * x.liquidity_score + 0.10 * x.volatility_score),
            reverse=True,
        )
        return ranked[:limit]

    async def evidence(self, symbol: str) -> Dict[str, Any]:
        # Transport to the real Bee/Pchelka service is deliberately injected
        # later; keeping this method deterministic makes paper testing safe.
        return {"symbol": symbol, "source": "ncam", "research_only": True}
