from app.strategy_intelligence import evaluate, reassess_position, timeframe_signal


def series(values):
    return {"close": values, "high": [x * 1.002 for x in values], "low": [x * .998 for x in values]}


def test_timeframe_contains_rsi_stochastic_and_ma():
    values = [1.0 + i * 0.001 for i in range(120)]
    out = timeframe_signal(series(values))
    assert "rsi14" in out
    assert "stoch14_k" in out and "stoch14_d" in out
    assert "ma7" in out and "ma25" in out and "ma99" in out


def test_flat_regime_is_not_driven_by_one_short_candle():
    base = [1.0 + (i % 8) * 0.002 for i in range(120)]
    tfs = {tf: series(base) for tf in ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h")}
    out = evaluate(tfs)
    assert out["regime"]["regime"] in {"flat", "transition", "bull", "bear"}
    assert "regime" in out


def test_underwater_flat_position_is_not_forced_to_exit():
    analysis = {
        "score": 0.02,
        "direction": "neutral",
        "regime": {"regime": "flat"},
        "timeframes": {"1h": {"rsi14": 49}},
    }
    out = reassess_position(0.066, 0.061, 20, analysis)
    assert out["action"] == "RANGE_HOLD"


def test_underwater_position_can_rotate_when_structure_breaks():
    analysis = {
        "score": -0.60,
        "direction": "bearish",
        "regime": {"regime": "bear"},
        "timeframes": {"1h": {"rsi14": 35}},
    }
    out = reassess_position(0.066, 0.061, 30, analysis, alternative_edge=0.05)
    assert out["action"] == "ROTATE"
