from app.profit_first_engine_v2 import TARGET_PNL_PER_MIN_PER_100, decision


def test_target_is_portfolio_rate_not_single_trade():
    assert TARGET_PNL_PER_MIN_PER_100 == 1.73


def test_entry_gate_allows_confirmed_practical_signal():
    m = {
        "score": 75, "change_1m_pct": 0.12, "change_3m_pct": 0.25,
        "volume_ratio": 1.8, "buy_ratio": 0.60, "volume_surge": 0.25,
        "stability": 0.8, "signal": "PUMP_NOW"
    }
    d = decision(m)
    assert d["entry_ok"] is True


def test_weak_flat_signal_is_rejected():
    m = {
        "score": 35, "change_1m_pct": 0.0, "change_3m_pct": 0.0,
        "volume_ratio": 0.7, "buy_ratio": 0.50, "volume_surge": 0.0,
        "stability": 0.9, "signal": "NORMAL"
    }
    assert decision(m)["entry_ok"] is False
