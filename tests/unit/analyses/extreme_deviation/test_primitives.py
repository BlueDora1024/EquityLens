from __future__ import annotations

import pytest

from stock_toolbox.analyses.extreme_deviation.domain.primitives import (
    cn_sma,
    directional_pressure,
    ema,
    rolling_max,
    rolling_min,
)


def test_cn_sma_is_recursive_not_a_simple_average() -> None:
    assert cn_sma((3.0, 6.0, 12.0), 3, 1) == pytest.approx((3.0, 4.0, 20.0 / 3.0))


def test_ema_matches_adjust_false_recursion() -> None:
    assert ema((10.0, 14.0, 14.0), 3) == pytest.approx((10.0, 12.0, 13.0))


def test_rolling_extrema_use_available_history_until_window_is_full() -> None:
    assert rolling_max((1.0, 3.0, 2.0), 3) == (1.0, 3.0, 3.0)
    assert rolling_min((1.0, 3.0, 2.0), 3) == (1.0, 1.0, 1.0)


def test_sell_pressure_uses_original_positive_high_change_denominator() -> None:
    falling_lows = tuple(200.0 - index for index in range(8))
    rising_highs = tuple(100.0 + index for index in range(8))

    buy = directional_pressure(falling_lows, "buy")
    sell = directional_pressure(rising_highs, "sell")

    assert sell[-1] == pytest.approx(100.0)
    assert buy[-1] == pytest.approx(1_000_000.0)


def test_directional_pressure_is_finite_when_denominator_decays_to_zero() -> None:
    pressure = directional_pressure(tuple(100.0 - index for index in range(100)), "buy")
    assert all(0.0 <= value <= 1_000_000.0 for value in pressure)
