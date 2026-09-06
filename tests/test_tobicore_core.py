from app.tobicore_core import HORIZONS, CROSS_MODES, MarketSnapshot, evaluate, run_matrix


def test_all_horizons_and_modes_are_deterministic():
    s = MarketSnapshot('BTCUSDT', 100000.0, 0.8, 0.6, 1.4, 2.0)
    for h in HORIZONS:
        for mode in CROSS_MODES:
            a = evaluate(s, h, mode)
            b = evaluate(s, h, mode)
            assert a == b
            assert a['horizon_min'] == h
            assert a['mode'] == mode
            assert 0 <= a['score'] <= 100
            assert 0 <= a['confidence'] <= 100


def test_reverse_is_complement_of_direct_score():
    s = MarketSnapshot('ETHUSDT', 4000.0, -0.7, 0.3, 1.2, 1.5)
    for h in HORIZONS:
        d = evaluate(s, h, 'direct')
        r = evaluate(s, h, 'reverse')
        assert abs(d['score'] + r['score'] - 100.0) < 1e-9


def test_matrix_contract():
    result = run_matrix(cases_per_horizon=250, repeats=5)
    assert result['ok'] is True
    assert result['evaluations'] == 22500
    assert result['failures'] == []
