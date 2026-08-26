from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    default_capital: float = 100.0
    target_pnl_per_min_per_100: float = 1.73
    max_pairs: int = 10
    ranking_blocks: int = 2
    pairs_per_block: int = 5
    window_seconds: int = 60
    allowed_timeframes: tuple[str, ...] = ("1m", "3m", "5m")

SETTINGS = Settings()
