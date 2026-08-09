from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stock_toolbox.core.market_data.models import (
    CandleInterval,
    CandleSeries,
    MarketCandle,
)


def test_extreme_deviation_intervals_have_stable_wire_values() -> None:
    assert tuple(item.value for item in CandleInterval) == (
        "30m",
        "60m",
        "120m",
        "240m",
        "1d",
        "1w",
    )


def test_candle_series_is_ordered_and_immutable() -> None:
    candle = MarketCandle(
        datetime(2026, 7, 24, tzinfo=UTC),
        Decimal(10),
        Decimal(11),
        Decimal(9),
        Decimal("10.5"),
        42,
    )
    series = CandleSeries("NVDA.US", CandleInterval.MIN_30, (candle,))
    assert series.candles == (candle,)
    with pytest.raises(AttributeError):
        series.symbol = "AMD.US"  # type: ignore[misc]


def test_market_candle_rejects_invalid_ohlc() -> None:
    with pytest.raises(ValueError, match="OHLC"):
        MarketCandle(
            datetime(2026, 7, 24, tzinfo=UTC),
            Decimal(10),
            Decimal(9),
            Decimal(8),
            Decimal(10),
            42,
        )
