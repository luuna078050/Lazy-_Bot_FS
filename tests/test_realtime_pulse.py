from app.realtime_execution import pulse_entry_allowed


def test_short_pump_can_trigger_realtime_entry():
    assert pulse_entry_allowed({
        "state": "IGNITION",
        "score": 0.80,
        "price_change_2s": 0.0022,
        "volume_ratio": 3.1,
        "buy_ratio": 0.64,
    })


def test_normal_move_does_not_trigger():
    assert not pulse_entry_allowed({
        "state": "EARLY_ROCKET",
        "score": 0.60,
        "price_change_2s": 0.0010,
        "volume_ratio": 1.4,
        "buy_ratio": 0.55,
    })
