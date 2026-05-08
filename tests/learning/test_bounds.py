import pytest
from bot.learning.bounds import (
    clamp,
    CONFIDENCE_MIN_BOUNDS,
    BUY_THRESHOLD_BOUNDS,
    SELL_THRESHOLD_BOUNDS,
    WEIGHT_BOUNDS,
    MAX_DAILY_CHANGE_PCT,
    is_within_daily_change_cap,
)


def test_clamp_within_bounds():
    assert clamp(0.6, 0.5, 0.75) == 0.6


def test_clamp_below_min():
    assert clamp(0.3, 0.5, 0.75) == 0.5


def test_clamp_above_max():
    assert clamp(0.9, 0.5, 0.75) == 0.75


def test_clamp_equals_bound():
    assert clamp(0.5, 0.5, 0.75) == 0.5
    assert clamp(0.75, 0.5, 0.75) == 0.75


def test_confidence_min_bounds():
    assert CONFIDENCE_MIN_BOUNDS == (0.50, 0.75)


def test_buy_threshold_bounds():
    assert BUY_THRESHOLD_BOUNDS == (0.005, 0.02)


def test_sell_threshold_bounds():
    assert SELL_THRESHOLD_BOUNDS == (-0.02, -0.005)


def test_weight_bounds():
    assert WEIGHT_BOUNDS == (0.05, 0.30)


def test_max_daily_change_pct():
    assert MAX_DAILY_CHANGE_PCT == 0.15


def test_is_within_daily_change_cap_under():
    # 0.60 → 0.55 = -8.3% relatif, sous le cap 15%
    assert is_within_daily_change_cap(0.60, 0.55) is True


def test_is_within_daily_change_cap_over():
    # 0.60 → 0.40 = -33% relatif, au-dessus du cap 15%
    assert is_within_daily_change_cap(0.60, 0.40) is False


def test_is_within_daily_change_cap_zero_from():
    # cas spécial : si from = 0, on accepte (pas de division)
    assert is_within_daily_change_cap(0.0, 0.5) is True
