from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from stock_toolbox.analyses.extreme_deviation.domain.indicator import (
    ExtremeDeviationIndicator,
)
from stock_toolbox.core.market_data.models import MarketCandle

pytestmark = pytest.mark.fast


def _trend_candles(*, rising: bool, count: int = 650) -> tuple[MarketCandle, ...]:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    candles = []
    for index in range(count):
        change = Decimal(index) / Decimal(20)
        close = Decimal(100) + change if rising else Decimal(200) - change
        candles.append(
            MarketCandle(
                start + timedelta(days=index),
                close,
                close + Decimal(1),
                close - Decimal(1),
                close,
                1000 + index,
            )
        )
    return tuple(candles)


def test_indicator_uses_available_history_before_the_500_bar_window_is_full() -> None:
    points = ExtremeDeviationIndicator().calculate(
        _trend_candles(rising=False, count=62)
    )

    assert len(points) >= 30
    assert points[-1].buy_raw > points[-1].sell_raw


def test_indicator_requires_only_the_30_bar_trigger_window() -> None:
    assert ExtremeDeviationIndicator().calculate(
        _trend_candles(rising=False, count=29)
    ) == ()


def test_corrected_indicator_detects_falling_buy_and_rising_sell_pressure() -> None:
    falling = ExtremeDeviationIndicator().calculate(_trend_candles(rising=False))
    rising = ExtremeDeviationIndicator().calculate(_trend_candles(rising=True))

    assert len(falling) >= 100
    assert len(rising) >= 100
    assert falling[-1].buy_raw > falling[-1].sell_raw
    assert rising[-1].sell_raw > rising[-1].buy_raw
    assert falling[-1].buy_trigger_age == 0
    assert rising[-1].sell_trigger_age == 0


def test_all_indicator_outputs_are_finite() -> None:
    points = ExtremeDeviationIndicator().calculate(_trend_candles(rising=True))

    for point in points:
        assert point.is_finite()
