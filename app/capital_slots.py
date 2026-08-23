"""Capital-slot controller shared by manual and automatic trading modes.

The percentage belongs to a slot, not to a specific coin. When a candidate
loses its edge, the slot may be reassigned to a better candidate while keeping
the approved allocation unchanged.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class CapitalSlot:
    slot_id: int
    allocation_pct: float
    symbol: str | None = None
    status: str = "EMPTY"
    locked: bool = False


class CapitalAllocator:
    def __init__(self, capital: float, allocations: list[float], mode: str = "manual"):
        if capital <= 0: raise ValueError("capital must be positive")
        if any(x < 0 or x > 100 for x in allocations): raise ValueError("allocation must be 0..100")
        if sum(allocations) > 100.000001: raise ValueError("allocations exceed 100%")
        self.capital = capital
        self.mode = mode if mode in {"manual", "auto"} else "manual"
        self.slots = [CapitalSlot(i + 1, float(p)) for i, p in enumerate(allocations)]

    def snapshot(self) -> list[dict]:
        return [{"slot_id": s.slot_id, "allocation_pct": s.allocation_pct,
                 "amount": self.capital * s.allocation_pct / 100.0,
                 "symbol": s.symbol, "status": s.status, "locked": s.locked}
                for s in self.slots]

    def assign(self, slot_id: int, symbol: str, score: float, force: bool = False) -> dict:
        s = self._slot(slot_id)
        if s.locked and not force: return {"action": "REJECT", "reason": "slot_locked", "slot_id": slot_id}
        s.symbol = symbol; s.status = "ACTIVE" if score > 0 else "WATCH"
        return {"action": "ASSIGN", "slot_id": slot_id, "symbol": symbol, "allocation_pct": s.allocation_pct,
                "amount": self.capital * s.allocation_pct / 100.0}

    def rebalance(self, candidates: list[dict], min_score: float = .55) -> list[dict]:
        """Replace weak symbols while preserving each slot's allocation percentage."""
        ranked = sorted((c for c in candidates if float(c.get("score", 0)) >= min_score),
                        key=lambda c: float(c.get("score", 0)), reverse=True)
        used = set(); actions = []
        for s in self.slots:
            current = next((c for c in candidates if c.get("symbol") == s.symbol), None)
            current_score = float(current.get("score", 0)) if current else -1
            replacement = next((c for c in ranked if c.get("symbol") not in used and
                                c.get("symbol") != s.symbol and float(c.get("score", 0)) > current_score), None)
            if replacement and not s.locked:
                old = s.symbol; s.symbol = replacement["symbol"]; s.status = "ACTIVE"; used.add(s.symbol)
                actions.append({"action": "REPLACE", "slot_id": s.slot_id, "old_symbol": old,
                                "new_symbol": s.symbol, "allocation_pct": s.allocation_pct,
                                "amount": self.capital * s.allocation_pct / 100.0})
            elif s.symbol:
                used.add(s.symbol); s.status = "ACTIVE" if current_score >= min_score else "REASSESS"
        return actions

    def _slot(self, slot_id: int) -> CapitalSlot:
        for s in self.slots:
            if s.slot_id == slot_id: return s
        raise KeyError(slot_id)
