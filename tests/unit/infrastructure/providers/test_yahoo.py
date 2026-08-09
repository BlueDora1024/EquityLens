from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.market_data.service import SharedMarketDataService
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.infrastructure.providers.yahoo import YahooFallbackProvider


class _Control:
    def cancellation_requested(self) -> bool:
        return False


class _Download:
    def __init__(self, frame: pd.DataFrame | Exception) -> None:
        self.frame = frame
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(kwargs)
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.frame


def _frame(
    symbol: str,
    index: pd.DatetimeIndex,
    closes: tuple[float, ...],
) -> pd.DataFrame:
    columns = pd.MultiIndex.from_product([[symbol], ["Open", "High", "Low", "Close", "Volume"]])
    rows = [
        [
            max(0.1, close - 0.5),
            close + 1,
            max(0.1, close - 1),
            close,
            100 + offset,
        ]
        for offset, close in enumerate(closes)
    ]
    return pd.DataFrame(rows, index=index, columns=columns)


def test_daily_download_uses_exclusive_end_and_adjusted_prices() -> None:
    download = _Download(
        _frame(
            "AAPL",
            pd.DatetimeIndex(["2026-07-09", "2026-07-10"]),
            (100.0, 101.0),
        )
    )
    provider = YahooFallbackProvider(download=download)

    dataset = provider.get_daily_series(
        ("AAPL.US",),
        date(2026, 7, 9),
        date(2026, 7, 10),
        operation_control=_Control(),
    )

    assert download.calls == [
        {
            "tickers": ("AAPL",),
            "start": "2026-07-09",
            "end": "2026-07-11",
            "interval": "1d",
            "auto_adjust": True,
            "actions": False,
            "group_by": "ticker",
            "threads": 1,
            "progress": False,
            "timeout": 10.0,
        }
    ]
    assert dataset.series_by_symbol["AAPL.US"].points[-1].close == Decimal("101.0")
    assert dataset.source_by_symbol == {"AAPL.US": "yahoo"}


def test_one_two_and_four_hour_candles_reuse_one_hourly_download() -> None:
    index = pd.date_range(
        "2026-07-29 09:30",
        periods=8,
        freq="h",
        tz="America/New_York",
    )
    download = _Download(_frame("AAPL", index, tuple(float(value) for value in range(1, 9))))
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)
    provider = YahooFallbackProvider(download=download, now=lambda: now)
    end_at = datetime(2026, 7, 29, 23, 59, tzinfo=UTC)

    one_hour = provider.get_candle_series(
        ("AAPL.US",),
        CandleInterval.MIN_60,
        4,
        end_at,
        operation_control=_Control(),
    )
    two_hour = provider.get_candle_series(
        ("AAPL.US",),
        CandleInterval.MIN_120,
        3,
        end_at,
        operation_control=_Control(),
    )
    four_hour = provider.get_candle_series(
        ("AAPL.US",),
        CandleInterval.MIN_240,
        2,
        end_at,
        operation_control=_Control(),
    )

    assert len(download.calls) == 1
    assert download.calls[0]["interval"] == "1h"
    assert download.calls[0]["period"] == "2y"
    assert "start" not in download.calls[0]
    assert "end" not in download.calls[0]
    assert len(one_hour.series_by_symbol["AAPL.US"].candles) == 4
    assert [item.close for item in two_hour.series_by_symbol["AAPL.US"].candles] == [
        Decimal("4.0"),
        Decimal("6.0"),
        Decimal("8.0"),
    ]
    assert [item.close for item in four_hour.series_by_symbol["AAPL.US"].candles] == [
        Decimal("4.0"),
        Decimal("8.0"),
    ]
    assert four_hour.series_by_symbol["AAPL.US"].candles[-1].volume == sum(
        100 + offset for offset in range(4, 8)
    )


def test_intraday_history_older_than_sixty_days_is_rejected_without_io() -> None:
    download = _Download(pd.DataFrame())
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)
    provider = YahooFallbackProvider(download=download, now=lambda: now)

    dataset = provider.get_candle_series(
        ("AAPL.US",),
        CandleInterval.MIN_30,
        100,
        now - timedelta(days=61),
        operation_control=_Control(),
    )

    assert download.calls == []
    assert dataset.errors == {"AAPL.US": "yahoo_intraday_history_limited"}


def test_current_thirty_minute_download_uses_full_sixty_day_range() -> None:
    index = pd.date_range(
        "2026-07-29 09:30",
        periods=4,
        freq="30min",
        tz="America/New_York",
    )
    download = _Download(_frame("NVDA", index, (100.0, 101.0, 102.0, 103.0)))
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)
    provider = YahooFallbackProvider(download=download, now=lambda: now)

    dataset = provider.get_candle_series(
        ("NVDA.US",),
        CandleInterval.MIN_30,
        650,
        datetime(2026, 7, 29, 23, 59, tzinfo=UTC),
        operation_control=_Control(),
    )

    assert tuple(dataset.series_by_symbol) == ("NVDA.US",)
    assert download.calls[0]["period"] == "60d"
    assert "start" not in download.calls[0]
    assert "end" not in download.calls[0]


def test_yahoo_candles_are_available_through_shared_screening_boundary() -> None:
    index = pd.date_range(
        "2026-07-29 09:30",
        periods=4,
        freq="30min",
        tz="America/New_York",
    )
    download = _Download(_frame("IREN", index, (35.0, 36.0, 37.0, 38.0)))
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)
    provider = YahooFallbackProvider(download=download, now=lambda: now)

    dataset = SharedMarketDataService(provider).get_candle_series(
        ("IREN.US",),
        CandleInterval.MIN_30,
        4,
        datetime(2026, 7, 29, 23, 59, tzinfo=UTC),
        operation_control=_Control(),
    )

    assert tuple(dataset.series_by_symbol) == ("IREN.US",)
    assert dataset.source_by_symbol == {"IREN.US": "yahoo"}


def test_one_hour_history_between_sixty_days_and_two_years_is_allowed() -> None:
    index = pd.date_range(
        "2026-03-31 09:30",
        periods=4,
        freq="h",
        tz="America/New_York",
    )
    download = _Download(_frame("NVDA", index, (100.0, 101.0, 102.0, 103.0)))
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)
    provider = YahooFallbackProvider(download=download, now=lambda: now)

    dataset = provider.get_candle_series(
        ("NVDA.US",),
        CandleInterval.MIN_60,
        4,
        now - timedelta(days=120),
        operation_control=_Control(),
    )

    assert tuple(dataset.series_by_symbol) == ("NVDA.US",)
    assert len(download.calls) == 1
    assert download.calls[0]["period"] == "2y"


def test_weekly_download_requests_enough_calendar_history_for_bar_count() -> None:
    download = _Download(
        _frame(
            "NVDA",
            pd.DatetimeIndex(["2013-12-30", "2026-07-27"]),
            (10.0, 100.0),
        )
    )
    provider = YahooFallbackProvider(download=download)

    provider.get_candle_series(
        ("NVDA.US",),
        CandleInterval.WEEK,
        650,
        datetime(2026, 7, 31, 23, 59, tzinfo=UTC),
        operation_control=_Control(),
    )

    start = date.fromisoformat(download.calls[0]["start"])
    end = date.fromisoformat(download.calls[0]["end"])
    assert (end - start).days >= 650 * 7


def test_rate_limit_is_mapped_for_every_requested_symbol() -> None:
    provider = YahooFallbackProvider(
        download=_Download(RuntimeError("Too Many Requests. Rate limited."))
    )

    dataset = provider.get_daily_series(
        ("AAPL.US", "NVDA.US"),
        date(2026, 7, 1),
        date(2026, 7, 10),
        operation_control=_Control(),
    )

    assert dataset.errors == {
        "AAPL.US": FailureCode.RATE_LIMITED.value,
        "NVDA.US": FailureCode.RATE_LIMITED.value,
    }


def test_class_share_symbol_round_trips_through_yahoo_dash() -> None:
    download = _Download(
        _frame(
            "BRK-B",
            pd.DatetimeIndex(["2026-07-10"]),
            (500.0,),
        )
    )
    provider = YahooFallbackProvider(download=download)

    dataset = provider.get_daily_series(
        ("BRK.B.US",),
        date(2026, 7, 10),
        date(2026, 7, 10),
        operation_control=_Control(),
    )

    assert download.calls[0]["tickers"] == ("BRK-B",)
    assert tuple(dataset.series_by_symbol) == ("BRK.B.US",)
