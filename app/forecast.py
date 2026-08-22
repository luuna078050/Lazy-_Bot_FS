"""Canonical forecast horizons shared by Lazy Income and Lazy Bot Scalper."""

HORIZONS_MIN = (1, 3, 5, 15, 30, 60)


def validate_horizon(minutes: int) -> int:
    minutes = int(minutes)
    if minutes not in HORIZONS_MIN:
        raise ValueError(f"Unsupported forecast horizon: {minutes}. Allowed: {HORIZONS_MIN}")
    return minutes


def forecast_targets(price: float, predicted_return_pct: float) -> dict[int, float]:
    """Return target prices for every canonical horizon using the supplied signal."""
    target = price * (1.0 + float(predicted_return_pct) / 100.0)
    return {h: target for h in HORIZONS_MIN}
