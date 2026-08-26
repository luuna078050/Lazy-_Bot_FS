from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from threading import RLock

from .config import SETTINGS
from .matrix import MinuteThroughput

@dataclass
class Trade:
    id: int
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    allocated_usdt: float
    gross_pnl: float
    fee_usdt: float
    net_pnl: float
    opened_at: str
    closed_at: str
    reason: str

class PaperLedger:
    """Single source of truth for PAPER accounting."""
    def __init__(self, capital: float):
        self.lock = RLock()
        self.initial_capital = float(capital)
        self.free_capital = float(capital)
        self.realized_pnl = 0.0
        self.trades: list[Trade] = []
        self.positions: dict[str, dict] = {}
        self.throughput = MinuteThroughput()
        self._next_id = 1

    def open(self, symbol: str, price: float, allocation: float) -> None:
        with self.lock:
            if allocation <= 0 or allocation > self.free_capital:
                raise ValueError("Недостаточно свободного капитала")
            if symbol in self.positions:
                return
            self.free_capital -= allocation
            self.positions[symbol] = {
                "symbol": symbol,
                "entry_price": float(price),
                "allocated_usdt": float(allocation),
                "opened_at": datetime.now(timezone.utc).isoformat(),
            }

    def close(self, symbol: str, price: float, fee_rate: float = 0.001, reason: str = "SIGNAL") -> Trade:
        with self.lock:
            pos = self.positions.pop(symbol)
            allocation = pos["allocated_usdt"]
            entry = pos["entry_price"]
            gross = allocation * (float(price) / entry - 1.0)
            fee = (allocation + allocation * float(price) / entry) * fee_rate
            net = gross - fee
            self.free_capital += allocation + net
            self.realized_pnl += net
            now = datetime.now(timezone.utc).isoformat()
            trade = Trade(self._next_id, symbol, "LONG", entry, float(price), allocation, gross, fee, net, pos["opened_at"], now, reason)
            self._next_id += 1
            self.trades.append(trade)
            self.throughput.record(net)
            return trade

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "initial_capital": self.initial_capital,
                "free_capital": self.free_capital,
                "realized_pnl": self.realized_pnl,
                "unrealized_pnl": 0.0,
                "net_pnl": self.realized_pnl,
                "target_pnl_per_min": self.throughput.target_for(self.initial_capital),
                "realized_pnl_last_minute": self.throughput.pnl_last_minute(),
                "positions": list(self.positions.values()),
                "trades": [asdict(t) for t in self.trades[-100:]],
                "running": True,
            }
