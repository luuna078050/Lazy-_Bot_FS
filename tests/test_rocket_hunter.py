from app.rocket_hunter import RocketSnapshot, scan


def snap(**kw):
    base = dict(symbol='TESTUSDC', price=.000004, volume_24h=500000, volume_1h=100000,
                volume_5m=10000, volume_3m=7000, volume_1m=2500, price_change_1m=.015,
                price_change_3m=.035, price_change_5m=.06, trades_5m=1000, spread_bps=8,
                depth_usd=20000, buy_imbalance=.35, ma7_slope=.01, ma25_slope=.005,
                rsi=61, stoch_k=65, stoch_d=58, higher_tf_score=.25)
    base.update(kw)
    return RocketSnapshot(**base)


def test_early_acceleration_is_rocket_candidate():
    out = scan(snap())
    assert out.phase in {'EARLY_ROCKET', 'IGNITION', 'WATCH'}
    assert 'volume_acceleration' in out.reasons


def test_exhausted_vertical_pump_is_penalized():
    early = scan(snap())
    late = scan(snap(price_change_5m=.35, rsi=92, stoch_k=96, stoch_d=97))
    assert late.score < early.score
    assert 'late_entry_risk' in late.reasons


def test_low_nominal_price_is_not_the_main_signal():
    low = scan(snap(price=.000004))
    high = scan(snap(price=4.0))
    assert abs(low.score - high.score) < .10
