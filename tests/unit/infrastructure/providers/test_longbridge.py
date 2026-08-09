from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import stock_toolbox.infrastructure.providers.longbridge as longbridge_module
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.infrastructure.providers.longbridge import LongbridgeProvider


@dataclass
class Static:
    symbol: str
    name_en: str
    name_cn: str = ""
    name_hk: str = ""
    exchange: str = "NASDAQ"
    currency: str = "USD"
    board: str = "USMain"


@dataclass
class Candle:
    timestamp: datetime
    close: Decimal


@dataclass
class OhlcCandle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass
class Indexes:
    symbol: str
    last_done: Decimal
    total_market_value: Decimal


@dataclass
class TradingDays:
    trading_days: list[date]
    half_trading_days: list[date]


@dataclass
class Company:
    name: str = "IREN"
    company_name: str = "IREN Limited"
    market: str = "NASDAQ"
    region: str = "US"
    profile: str = "Operates data centers for AI cloud and Bitcoin mining."
    sector: int = 123
    category: str = "Technology"
    founded: str = "2018"
    employees: str = "1,000"
    website: str = "https://iren.com"


class Quote:
    def __init__(self) -> None:
        self.static_calls: list[tuple[str, ...]] = []
        self.candle_calls: list[tuple[object, ...]] = []
        self.trading_day_calls: list[tuple[object, date, date]] = []
        self.index_calls: list[tuple[tuple[str, ...], tuple[object, ...]]] = []

    def static_info(self, symbols: tuple[str, ...]) -> list[Static]:
        self.static_calls.append(tuple(symbols))
        return [Static(symbol, symbol.removesuffix(".US")) for symbol in symbols]

    def history_candlesticks_by_offset(self, *args: object) -> list[Candle]:
        self.candle_calls.append(args)
        cursor = args[5]
        assert isinstance(cursor, datetime)
        end = cursor.date()
        return [
            Candle(
                datetime.combine(end - timedelta(days=offset), datetime.min.time(), UTC),
                Decimal(100 + offset),
            )
            for offset in range(200)
            if (end - timedelta(days=offset)).weekday() < 5
        ][:200]

    def trading_days(
        self,
        market: object,
        begin: date,
        end: date,
    ) -> TradingDays:
        self.trading_day_calls.append((market, begin, end))
        days = [
            begin + timedelta(days=offset)
            for offset in range((end - begin).days + 1)
            if (begin + timedelta(days=offset)).weekday() < 5
        ]
        return TradingDays(days, [])

    def calc_indexes(
        self,
        symbols: tuple[str, ...],
        indexes: tuple[object, ...],
    ) -> list[Indexes]:
        self.index_calls.append((tuple(symbols), tuple(indexes)))
        return [Indexes(symbol, Decimal("123.45"), Decimal(25000000000)) for symbol in symbols]


class Fundamental:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.error = error

    def company(self, symbol: str) -> Company:
        self.calls.append(symbol)
        if self.error is not None:
            raise self.error
        return Company()


class FlakyProfileQuote(Quote):
    def __init__(self, failures: tuple[Exception, ...]) -> None:
        super().__init__()
        self.failures = list(failures)

    def static_info(self, symbols: tuple[str, ...]) -> list[Static]:
        self.static_calls.append(tuple(symbols))
        if self.failures:
            raise self.failures.pop(0)
        return [Static(symbol, symbol.removesuffix(".US")) for symbol in symbols]


class DensePagingQuote(Quote):
    def history_candlesticks_by_offset(self, *args: object) -> list[Candle]:
        self.candle_calls.append(args)
        cursor = args[5]
        count = args[4]
        assert isinstance(cursor, datetime)
        assert isinstance(count, int)
        end = cursor.date()
        if cursor.hour < 20:
            end -= timedelta(days=1)
        return [
            Candle(
                datetime.combine(
                    end - timedelta(days=offset),
                    datetime.min.time().replace(hour=20),
                    UTC,
                ),
                Decimal(100 + offset),
            )
            for offset in range(count)
        ]


class AsyncDailyQuote:
    def __init__(
        self,
        *,
        failures: dict[str, Exception] | None = None,
    ) -> None:
        self.failures = failures or {}
        self.calls: list[tuple[object, ...]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def history_candlesticks_by_offset(self, *args: object) -> list[Candle]:
        self.calls.append(args)
        symbol = str(args[0])
        count = int(args[4])
        cursor = args[5]
        assert isinstance(cursor, datetime)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.002 if symbol.endswith("0.US") else 0.001)
            error = self.failures.get(symbol)
            if error is not None:
                raise error
            return [
                Candle(
                    datetime.combine(cursor.date(), datetime.min.time(), UTC),
                    Decimal(100),
                )
            ][:count]
        finally:
            self.in_flight -= 1


class AsyncFlakyDailyQuote(AsyncDailyQuote):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    async def history_candlesticks_by_offset(self, *args: object) -> list[Candle]:
        self.attempts += 1
        if self.attempts == 1:
            raise TimeoutError("temporary timeout")
        return await super().history_candlesticks_by_offset(*args)


class MutableControl:
    def __init__(self) -> None:
        self.canceled = False

    def cancellation_requested(self) -> bool:
        return self.canceled

    def try_enter_committing(self) -> bool:
        return not self.canceled


class ScreeningQuote(Quote):
    def history_candlesticks_by_offset(self, *args: object) -> list[OhlcCandle]:
        self.candle_calls.append(args)
        cursor = args[5]
        count = args[4]
        assert isinstance(cursor, datetime)
        assert isinstance(count, int)
        return [
            OhlcCandle(
                cursor - timedelta(minutes=30 * offset),
                Decimal(100),
                Decimal(101),
                Decimal(99),
                Decimal(100),
                1000,
            )
            for offset in range(count)
        ]


class InclusiveSecondPagingQuote(Quote):
    """Mirror the SDK's second-precision inclusive paging boundary."""

    def __init__(self) -> None:
        super().__init__()
        end = datetime(2026, 7, 24, 20, tzinfo=UTC)
        self.candles = tuple(
            OhlcCandle(
                end - timedelta(minutes=30 * offset),
                Decimal(100),
                Decimal(101),
                Decimal(99),
                Decimal(100),
                1000,
            )
            for offset in range(800)
        )

    def history_candlesticks_by_offset(
        self,
        *args: object,
    ) -> list[OhlcCandle]:
        self.candle_calls.append(args)
        count = args[4]
        cursor = args[5]
        assert isinstance(count, int)
        assert isinstance(cursor, datetime)
        boundary_offset = cursor.minute % 30
        on_boundary = boundary_offset == 0 and cursor.second == 0 and cursor.microsecond == 0
        second_precision = cursor.replace(second=0, microsecond=0)
        if not on_boundary:
            second_precision += timedelta(minutes=30 - boundary_offset)
        eligible = [item for item in self.candles if item.timestamp <= second_precision]
        return eligible[:count]


def control():
    registry = OperationRegistry(clock=lambda: datetime(2026, 7, 25, tzinfo=UTC))
    registry.reserve("op-1", "key", "provider")
    context = registry.begin_reserved("op-1")
    assert context is not None
    return context.operation_control


def test_static_info_is_batched_at_100_and_usmain_remains_ambiguous() -> None:
    quote = Quote()
    provider = LongbridgeProvider(quote)
    symbols = tuple(f"S{number}.US" for number in range(101))

    result = provider.get_security_profiles(
        symbols,
        operation_control=control(),
    )

    assert tuple(len(call) for call in quote.static_calls) == (100, 1)
    assert len(result.profiles) == 101
    assert result.profiles[0].asset_hints[0].normalized_type == "UNKNOWN"
    assert result.profiles[0].asset_hints[0].reliability == "ambiguous"


def test_static_info_prefers_chinese_security_name() -> None:
    quote = Quote()
    quote.static_info = lambda symbols: [
        Static(symbols[0], "NVIDIA Corporation", "英伟达")
    ]
    provider = LongbridgeProvider(quote)

    result = provider.get_security_profiles(
        ("NVDA.US",),
        operation_control=control(),
    )

    assert result.profiles[0].name == "英伟达"


def test_company_overview_enriches_profile_without_guessing_classifications() -> None:
    quote = Quote()
    fundamental = Fundamental()
    provider = LongbridgeProvider(quote, fundamental_context=fundamental)

    result = provider.get_security_profiles(
        ("IREN.US",),
        operation_control=control(),
    )

    assert fundamental.calls == ["IREN.US"]
    assert result.errors == ()
    profile = result.profiles[0]
    assert profile.name == "IREN Limited"
    assert profile.description == "Operates data centers for AI cloud and Bitcoin mining."
    assert profile.business_profile == {
        "board": "USMain",
        "company": {
            "market": "NASDAQ",
            "region": "US",
            "sector": "123",
            "category": "Technology",
            "founded": "2018",
            "employees": "1,000",
            "website": "https://iren.com",
        },
    }


def test_optional_company_overview_failure_does_not_hide_valid_symbol() -> None:
    quote = Quote()
    fundamental = Fundamental(error=PermissionError("permission denied"))
    provider = LongbridgeProvider(
        quote,
        fundamental_context=fundamental,
        max_retries=0,
    )

    result = provider.get_security_profiles(
        ("IREN.US",),
        operation_control=control(),
    )

    assert len(result.profiles) == 1
    assert result.errors == ()
    assert result.profiles[0].description is None
    assert result.profiles[0].business_profile == {"board": "USMain"}


def test_daily_bars_use_frozen_positional_order_and_unadjusted_day_period() -> None:
    quote = Quote()
    provider = LongbridgeProvider(quote)

    result = provider.get_daily_series(
        ("IREN.US",),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=control(),
    )

    assert "IREN.US" in result.series_by_symbol
    first_call = quote.candle_calls[0]
    assert first_call[0] == "IREN.US"
    assert str(first_call[1]).endswith("Day")
    assert str(first_call[2]).endswith("NoAdjust")
    assert first_call[3] is False
    assert first_call[4] == 1000
    points = result.series_by_symbol["IREN.US"].points
    assert points == tuple(sorted(points, key=lambda item: item.date))
    assert all(date(2026, 1, 1) <= item.date <= date(2026, 7, 24) for item in points)


def test_latest_completed_day_uses_us_calendar_and_market_close() -> None:
    quote = Quote()
    provider = LongbridgeProvider(
        quote,
        clock=lambda: datetime(2026, 7, 24, 19, tzinfo=UTC),
    )

    result = provider.latest_completed_trading_day(
        operation_control=control(),
    )

    assert result == date(2026, 7, 23)
    assert len(quote.trading_day_calls) == 1


def test_latest_completed_day_honors_requested_upper_boundary() -> None:
    quote = Quote()
    provider = LongbridgeProvider(
        quote,
        clock=lambda: datetime(2026, 7, 30, 22, tzinfo=UTC),
    )

    result = provider.latest_completed_trading_day(
        operation_control=control(),
        on_or_before=date(2026, 7, 19),
    )

    assert result == date(2026, 7, 17)
    assert quote.trading_day_calls[0][2] == date(2026, 7, 19)


def test_retryable_provider_errors_obey_configured_retry_count() -> None:
    quote = FlakyProfileQuote((TimeoutError("timeout"), ConnectionError("temporary network")))
    waits: list[float] = []
    provider = LongbridgeProvider(
        quote,
        max_retries=2,
        sleeper=waits.append,
    )

    result = provider.get_security_profiles(
        ("IREN.US",),
        operation_control=control(),
    )

    assert len(result.profiles) == 1
    assert len(quote.static_calls) == 3
    assert waits == [1.0, 2.0]


def test_authentication_error_is_not_retried() -> None:
    quote = FlakyProfileQuote((RuntimeError("authentication failed"),))
    waits: list[float] = []
    provider = LongbridgeProvider(
        quote,
        max_retries=5,
        sleeper=waits.append,
    )

    result = provider.get_security_profiles(
        ("IREN.US",),
        operation_control=control(),
    )

    assert result.errors[0].code == "authentication_failed"
    assert len(quote.static_calls) == 1
    assert waits == []


def test_permission_error_is_not_retried() -> None:
    quote = FlakyProfileQuote((RuntimeError("access denied"),))
    waits: list[float] = []
    provider = LongbridgeProvider(
        quote,
        max_retries=5,
        sleeper=waits.append,
    )

    result = provider.get_security_profiles(
        ("IREN.US",),
        operation_control=control(),
    )

    assert result.errors[0].code == "permission_denied"
    assert len(quote.static_calls) == 1
    assert waits == []


def test_dense_daily_bars_request_the_official_1000_bar_page_size() -> None:
    quote = DensePagingQuote()
    provider = LongbridgeProvider(quote)
    end = date(2026, 7, 24)

    result = provider.get_daily_series(
        ("IREN.US",),
        end - timedelta(days=1000),
        end,
        operation_control=control(),
    )

    assert len(quote.candle_calls) == 2
    assert len(result.series_by_symbol["IREN.US"].points) == 1001
    assert all(call[4] == 1000 for call in quote.candle_calls)


def test_daily_bars_use_bounded_async_concurrency_and_preserve_symbol_order() -> None:
    quote = Quote()
    async_quote = AsyncDailyQuote()
    symbols = tuple(f"S{index}.US" for index in range(8))
    provider = LongbridgeProvider(
        quote,
        async_quote_factory=lambda: async_quote,
    )

    result = provider.get_daily_series(
        symbols,
        date(2026, 7, 1),
        date(2026, 7, 24),
        operation_control=control(),
    )

    assert 1 < async_quote.max_in_flight <= 4
    assert tuple(result.series_by_symbol) == symbols
    assert all(call[4] == 1000 for call in async_quote.calls)


def test_daily_bars_async_progress_reports_partial_failures() -> None:
    quote = Quote()
    async_quote = AsyncDailyQuote(
        failures={"BAD.US": RuntimeError("unsupported")}
    )
    provider = LongbridgeProvider(
        quote,
        async_quote_factory=lambda: async_quote,
        max_retries=0,
    )
    events = []

    result = provider.get_daily_series(
        ("GOOD.US", "BAD.US"),
        date(2026, 7, 1),
        date(2026, 7, 24),
        operation_control=control(),
        progress=events.append,
    )

    assert tuple(result.series_by_symbol) == ("GOOD.US",)
    assert result.errors == {"BAD.US": "unsupported"}
    assert events[-1].completed == 2
    assert events[-1].total == 2
    assert events[-1].succeeded == 1
    assert events[-1].failed == 1


def test_daily_bars_async_retry_does_not_block_through_sync_sleep() -> None:
    quote = Quote()
    async_quote = AsyncFlakyDailyQuote()
    waits: list[float] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    provider = LongbridgeProvider(
        quote,
        async_quote_factory=lambda: async_quote,
        max_retries=1,
        async_sleeper=record_wait,
    )

    result = provider.get_daily_series(
        ("IREN.US",),
        date(2026, 7, 1),
        date(2026, 7, 24),
        operation_control=control(),
    )

    assert "IREN.US" in result.series_by_symbol
    assert async_quote.attempts == 2
    assert waits == [1.0]


def test_daily_bars_async_cancel_stops_queued_symbols() -> None:
    quote = Quote()
    async_quote = AsyncDailyQuote()
    mutable_control = MutableControl()
    symbols = tuple(f"S{index}.US" for index in range(12))

    def cancel_after_first_completion(progress) -> None:
        if progress.completed == 1:
            mutable_control.canceled = True

    provider = LongbridgeProvider(
        quote,
        async_quote_factory=lambda: async_quote,
    )
    provider.get_daily_series(
        symbols,
        date(2026, 7, 1),
        date(2026, 7, 24),
        operation_control=mutable_control,
        progress=cancel_after_first_completion,
    )

    assert len(async_quote.calls) <= 4


def test_screening_snapshots_are_batched_at_100() -> None:
    quote = Quote()
    provider = LongbridgeProvider(quote)
    symbols = tuple(f"S{index}.US" for index in range(101))

    result = provider.get_security_snapshots(
        symbols,
        operation_control=control(),
    )

    assert tuple(len(call[0]) for call in quote.index_calls) == (100, 1)
    assert result.snapshots_by_symbol["S0.US"].last_price == Decimal("123.45")
    assert result.snapshots_by_symbol["S0.US"].total_market_value == Decimal(25000000000)


def test_screening_candles_use_forward_adjust_and_200_bar_pages() -> None:
    quote = ScreeningQuote()
    provider = LongbridgeProvider(quote)

    result = provider.get_candle_series(
        ("IREN.US",),
        CandleInterval.MIN_30,
        220,
        datetime(2026, 7, 24, 20, tzinfo=UTC),
        operation_control=control(),
    )

    assert tuple(call[4] for call in quote.candle_calls) == (200, 20)
    assert str(quote.candle_calls[0][1]).endswith("Min_30")
    assert str(quote.candle_calls[0][2]).endswith("ForwardAdjust")
    assert len(result.series_by_symbol["IREN.US"].candles) == 220


def test_screening_candles_tolerate_small_forward_adjust_rounding_error() -> None:
    class RoundedAdjustedQuote(ScreeningQuote):
        def history_candlesticks_by_offset(self, *args: object) -> list[OhlcCandle]:
            self.candle_calls.append(args)
            cursor = args[5]
            assert isinstance(cursor, datetime)
            return [
                OhlcCandle(
                    cursor,
                    Decimal("308.330"),
                    Decimal("312.770"),
                    Decimal("308.380"),
                    Decimal("311.260"),
                    5_649_807,
                )
            ]

    result = LongbridgeProvider(RoundedAdjustedQuote()).get_candle_series(
        ("AAPL.US",),
        CandleInterval.MIN_60,
        1,
        datetime(2026, 8, 7, 20, tzinfo=UTC),
        operation_control=control(),
    )

    candle = result.series_by_symbol["AAPL.US"].candles[0]
    assert candle.low == Decimal("308.330")
    assert "AAPL.US" not in result.errors


def test_screening_candles_still_reject_material_ohlc_error() -> None:
    class InvalidAdjustedQuote(ScreeningQuote):
        def history_candlesticks_by_offset(self, *args: object) -> list[OhlcCandle]:
            self.candle_calls.append(args)
            cursor = args[5]
            assert isinstance(cursor, datetime)
            return [
                OhlcCandle(
                    cursor,
                    Decimal("300.00"),
                    Decimal("312.00"),
                    Decimal("301.00"),
                    Decimal("311.00"),
                    1_000,
                )
            ]

    result = LongbridgeProvider(InvalidAdjustedQuote()).get_candle_series(
        ("AAPL.US",),
        CandleInterval.MIN_60,
        1,
        datetime(2026, 8, 7, 20, tzinfo=UTC),
        operation_control=control(),
    )

    assert result.errors == {"AAPL.US": "malformed_data"}
    assert "AAPL.US" not in result.series_by_symbol


def test_naive_sdk_candle_timestamp_is_interpreted_in_host_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_timezone = timezone(timedelta(hours=8))
    monkeypatch.setattr(longbridge_module, "_LOCAL_TIMEZONE", local_timezone)

    timestamp = LongbridgeProvider._timestamp(
        datetime.fromisoformat("2026-07-29T21:30:00")
    )

    assert timestamp == datetime(2026, 7, 29, 13, 30, tzinfo=UTC)


def test_screening_candle_pages_handle_inclusive_second_precision_cursor() -> None:
    quote = InclusiveSecondPagingQuote()
    provider = LongbridgeProvider(quote)

    result = provider.get_candle_series(
        ("IREN.US",),
        CandleInterval.MIN_30,
        650,
        datetime(2026, 7, 24, 23, 59, 59, 999999, UTC),
        operation_control=control(),
    )

    candles = result.series_by_symbol["IREN.US"].candles
    assert len(candles) == 650
    assert len({item.timestamp for item in candles}) == 650
    assert "IREN.US" not in result.errors


@pytest.mark.parametrize(
    ("interval", "sdk_suffix"),
    (
        (CandleInterval.MIN_120, "Min_120"),
        (CandleInterval.MIN_240, "Min_240"),
        (CandleInterval.WEEK, "Week"),
    ),
)
def test_extreme_deviation_intervals_map_to_longbridge_periods(
    interval: CandleInterval,
    sdk_suffix: str,
) -> None:
    quote = ScreeningQuote()
    provider = LongbridgeProvider(quote)

    provider.get_candle_series(
        ("IREN.US",),
        interval,
        1,
        datetime(2026, 7, 24, 20, tzinfo=UTC),
        operation_control=control(),
    )

    assert str(quote.candle_calls[0][1]).endswith(sdk_suffix)
