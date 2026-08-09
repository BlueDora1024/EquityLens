from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.infrastructure.providers.yahoo import YahooFallbackProvider


class _Control:
    def cancellation_requested(self) -> bool:
        return False


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_YAHOO") != "1",
        reason="set RUN_LIVE_YAHOO=1 for the explicit Yahoo network smoke",
    ),
]


def test_yahoo_live_daily_and_supported_periods() -> None:
    now = datetime.now(UTC)
    end_date = now.date() - timedelta(days=1)
    provider = YahooFallbackProvider(now=lambda: now)

    daily = provider.get_daily_series(
        ("AAPL.US",),
        end_date - timedelta(days=14),
        end_date,
        operation_control=_Control(),
    )
    assert daily.errors == {}
    assert len(daily.series_by_symbol["AAPL.US"].points) >= 5

    end_at = datetime.combine(end_date, datetime.max.time(), UTC)
    for interval in (
        CandleInterval.MIN_30,
        CandleInterval.MIN_60,
        CandleInterval.MIN_120,
        CandleInterval.MIN_240,
        CandleInterval.DAY,
        CandleInterval.WEEK,
    ):
        candles = provider.get_candle_series(
            ("AAPL.US",),
            interval,
            2,
            end_at,
            operation_control=_Control(),
        )
        assert candles.errors == {}, (interval, candles.errors)
        assert len(candles.series_by_symbol["AAPL.US"].candles) == 2


def test_yahoo_live_covers_current_extreme_deviation_warmup() -> None:
    now = datetime.now(UTC)
    end_date = now.date() - timedelta(days=1)
    end_at = datetime.combine(end_date, datetime.max.time(), UTC)
    provider = YahooFallbackProvider(now=lambda: now)

    for interval in (
        CandleInterval.MIN_30,
        CandleInterval.MIN_60,
        CandleInterval.DAY,
        CandleInterval.WEEK,
    ):
        candles = provider.get_candle_series(
            ("NVDA.US",),
            interval,
            650,
            end_at,
            operation_control=_Control(),
        )
        assert candles.errors == {}, (interval, candles.errors)
        assert len(candles.series_by_symbol["NVDA.US"].candles) >= 650, interval
