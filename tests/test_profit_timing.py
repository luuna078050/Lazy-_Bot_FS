from app.profit_timing import ProfitTimeProfile, should_rotate, should_take_profit


def test_target_profit_is_money_based():
    profile = ProfitTimeProfile(target_profit_per_unit=0.25, minimum_profit_per_unit=0.20, target_interval_sec=90, max_hold_sec=180)
    assert profile.target_net_profit(4.0) == 1.0
    assert profile.minimum_net_profit(4.0) == 0.8


def test_lower_profit_floor_is_allowed_at_target_interval():
    profile = ProfitTimeProfile(0.25, 0.20, 90, 180)
    assert should_take_profit(net_profit=0.8, allocated_capital=4.0, age_sec=90, profile=profile)


def test_floor_is_not_taken_too_early():
    profile = ProfitTimeProfile(0.25, 0.20, 90, 180)
    assert not should_take_profit(net_profit=0.8, allocated_capital=4.0, age_sec=60, profile=profile)


def test_full_target_closes_before_interval():
    profile = ProfitTimeProfile(0.25, 0.20, 90, 180)
    assert should_take_profit(net_profit=1.0, allocated_capital=4.0, age_sec=20, profile=profile)


def test_time_recycle_only_after_max_hold_and_non_losing():
    profile = ProfitTimeProfile(0.25, 0.20, 90, 180)
    assert should_rotate(net_profit=0.01, allocated_capital=4.0, age_sec=180, profile=profile, entry_still_valid=True)
    assert not should_rotate(net_profit=-0.01, allocated_capital=4.0, age_sec=180, profile=profile, entry_still_valid=True)
