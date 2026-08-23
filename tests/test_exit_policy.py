from app.exit_policy import decide_exit


def test_stop_loss_enabled_exits_at_loss():
    assert decide_exit(100, 99.0, 0.006, 0.01, True, False) == "stop_loss"


def test_stop_loss_disabled_waits_at_loss():
    assert decide_exit(100, 99.0, 0.006, 0.01, False, True) is None


def test_take_profit_is_independent_of_stop_loss():
    assert decide_exit(100, 101.0, 0.006, 0.01, False, False) == "take_profit"


def test_profitable_confirmed_reversal_can_exit_without_sl():
    assert decide_exit(100, 101.0, 0.02, 0.01, False, True) == "confirmed_reversal"
