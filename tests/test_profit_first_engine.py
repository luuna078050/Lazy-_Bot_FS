from app.profit_first_engine import decision, pnl


def test_target_is_positive_after_fees():
    net, gross, fee = pnl(30, 100, 100.0014, 0.10)
    assert net < 0
    net2, _, _ = pnl(30, 100, 100.004, 0.10)
    assert net2 > 0


def test_entry_requires_multiple_confirmations():
    weak = {"change_3m_pct": 0.20, "volume_ratio": 1.0, "buy_ratio": 0.50, "pump_score": 0.10, "signal": "NORMAL", "change_24h_pct": 1.0}
    assert decision(weak)["entry_ok"] is False


def test_strong_pulse_passes_quality_gate():
    strong = {"change_3m_pct": 0.50, "volume_ratio": 3.0, "buy_ratio": 0.65, "pump_score": 0.90, "signal": "PUMP_NOW", "change_24h_pct": 2.0}
    d = decision(strong)
    assert d["entry_ok"] is True
    assert d["quality"] >= 58
    assert d["confirmations"] >= 4
