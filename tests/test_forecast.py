from app.forecast import HORIZONS_MIN, validate_horizon, forecast_targets


def test_canonical_horizons():
    assert HORIZONS_MIN == (1, 3, 5, 15, 30, 60)


def test_horizon_validation():
    for horizon in HORIZONS_MIN:
        assert validate_horizon(horizon) == horizon


def test_target_generation():
    targets = forecast_targets(100.0, 1.0)
    assert tuple(targets) == HORIZONS_MIN
    assert all(value == 101.0 for value in targets.values())
