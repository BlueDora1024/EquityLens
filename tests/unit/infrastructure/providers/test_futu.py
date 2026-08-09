from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.infrastructure.providers.futu import (
    FutuProvider,
    from_futu_symbol,
    futu_kl_type,
    to_futu_symbol,
)


def control():
    registry = OperationRegistry(clock=lambda: datetime(2026, 7, 31, tzinfo=UTC))
    registry.reserve("op-futu", "key", "provider")
    context = registry.begin_reserved("op-futu")
    assert context is not None
    return context.operation_control


class Quote:
    def __init__(
        self,
        *,
        static_rows: list[dict[str, Any]] | None = None,
        snapshot_rows: list[dict[str, Any]] | None = None,
        plate_rows: list[dict[str, Any]] | None = None,
        trading_rows: list[dict[str, Any]] | None = None,
        history_pages: list[list[dict[str, Any]]] | None = None,
        quota: tuple[int, int, list[dict[str, Any]]] = (0, 100, []),
    ) -> None:
        self.static_rows = static_rows
        self.snapshot_rows = snapshot_rows
        self.plate_rows = plate_rows or []
        self.trading_rows = trading_rows or []
        self.history_pages = list(history_pages or [])
        self.quota = quota
        self.static_calls: list[list[str]] = []
        self.snapshot_calls: list[list[str]] = []
        self.plate_calls: list[list[str]] = []
        self.history_calls: list[dict[str, object]] = []
        self.history_field_container_types: list[type[object]] = []
        self.quota_calls = 0

    def get_stock_basicinfo(
        self,
        market: object,
        stock_type: object = "STOCK",
        code_list: list[str] | None = None,
    ) -> tuple[int, object]:
        del market, stock_type
        codes = list(code_list or [])
        self.static_calls.append(codes)
        rows = self.static_rows
        if rows is None:
            rows = [
                {
                    "code": code,
                    "name": code.removeprefix("US."),
                    "stock_type": "STOCK",
                    "delisting": False,
                    "exchange_type": "NASDAQ",
                }
                for code in codes
            ]
        return 0, pd.DataFrame(row for row in rows if not codes or row["code"] in codes)

    def get_market_snapshot(
        self,
        code_list: list[str],
    ) -> tuple[int, object]:
        codes = list(code_list)
        self.snapshot_calls.append(codes)
        rows = self.snapshot_rows
        if rows is None:
            rows = [
                {
                    "code": code,
                    "last_price": "123.45",
                    "total_market_val": "25000000000",
                    "equity_valid": True,
                }
                for code in codes
            ]
        return 0, pd.DataFrame(row for row in rows if row["code"] in codes)

    def get_owner_plate(
        self,
        code_list: list[str],
    ) -> tuple[int, object]:
        codes = list(code_list)
        self.plate_calls.append(codes)
        return 0, pd.DataFrame(row for row in self.plate_rows if row["code"] in codes)

    def request_trading_days(
        self,
        market: object = None,
        start: str | None = None,
        end: str | None = None,
        code: str | None = None,
    ) -> tuple[int, object]:
        del market, start, end, code
        return 0, list(self.trading_rows)

    def get_history_kl_quota(
        self,
        get_detail: bool = False,
    ) -> tuple[int, object]:
        del get_detail
        self.quota_calls += 1
        used, remaining, rows = self.quota
        return 0, (used, remaining, pd.DataFrame(rows))

    def request_history_kline(
        self,
        code: str,
        start: str | None = None,
        end: str | None = None,
        ktype: object = "K_DAY",
        autype: object = "qfq",
        fields: Sequence[object] = ("",),
        max_count: int = 1000,
        page_req_key: object | None = None,
        extended_time: bool = False,
        session: object = "N/A",
    ) -> tuple[int, object, object | None]:
        self.history_field_container_types.append(type(fields))
        self.history_calls.append(
            {
                "code": code,
                "start": start,
                "end": end,
                "ktype": ktype,
                "autype": autype,
                "fields": tuple(fields),
                "max_count": max_count,
                "page_req_key": page_req_key,
                "extended_time": extended_time,
                "session": session,
            }
        )
        rows = self.history_pages.pop(0) if self.history_pages else []
        next_key = b"next" if self.history_pages else None
        return 0, pd.DataFrame(rows), next_key


def test_futu_symbol_mapping_is_reversible() -> None:
    assert to_futu_symbol("aapl.us") == "US.AAPL"
    assert from_futu_symbol("us.aapl") == "AAPL.US"


def test_profiles_are_batched_and_include_coarse_plate_candidates() -> None:
    quote = Quote(
        plate_rows=[
            {
                "code": "US.S0",
                "plate_code": "US.BK1001",
                "plate_name": "Semiconductors",
                "plate_type": "INDUSTRY",
            },
            {
                "code": "US.S0",
                "plate_code": "US.BK2001",
                "plate_name": "Artificial Intelligence",
                "plate_type": "CONCEPT",
            },
        ]
    )
    symbols = tuple(f"S{number}.US" for number in range(101))

    result = FutuProvider(quote).get_security_profiles(
        symbols,
        operation_control=control(),
    )

    assert tuple(len(call) for call in quote.static_calls) == (100, 1)
    assert tuple(len(call) for call in quote.plate_calls) == (100, 1)
    assert len(result.profiles) == 101
    first = result.profiles[0]
    assert first.symbol == "S0.US"
    assert first.asset_hints[0].normalized_type == "COMMON_STOCK"
    assert first.asset_hints[0].reliability == "reliable"
    assert first.business_profile["company"] == {
        "sector": "Semiconductors",
        "category": "Artificial Intelligence",
    }


def test_profiles_reject_delisted_and_non_stock_rows() -> None:
    quote = Quote(
        static_rows=[
            {
                "code": "US.AAPL",
                "name": "Apple",
                "stock_type": "STOCK",
                "delisting": False,
                "exchange_type": "NASDAQ",
            },
            {
                "code": "US.OLD",
                "name": "Unknown Stock",
                "stock_type": "STOCK",
                "delisting": True,
                "exchange_type": "NASDAQ",
            },
            {
                "code": "US.SPY",
                "name": "SPDR S&P 500 ETF",
                "stock_type": "ETF",
                "delisting": False,
                "exchange_type": "NYSE",
            },
        ]
    )

    result = FutuProvider(quote).get_security_profiles(
        ("AAPL.US", "OLD.US", "SPY.US"),
        operation_control=control(),
    )

    assert [profile.symbol for profile in result.profiles] == ["AAPL.US", "SPY.US"]
    assert result.profiles[1].asset_hints[0].normalized_type == "ETF"
    assert [(error.symbol, error.code) for error in result.errors] == [
        ("OLD.US", "security_delisted")
    ]


def test_snapshot_batches_at_official_400_symbol_limit() -> None:
    quote = Quote()
    symbols = tuple(f"S{number}.US" for number in range(401))

    result = FutuProvider(quote).get_security_snapshots(
        symbols,
        operation_control=control(),
    )

    assert tuple(len(call) for call in quote.snapshot_calls) == (400, 1)
    assert len(result.snapshots_by_symbol) == 401
    assert result.snapshots_by_symbol["S0.US"].last_price == Decimal("123.45")
    assert result.snapshots_by_symbol["S0.US"].total_market_value == Decimal(25000000000)


def test_latest_completed_trading_day_uses_last_eligible_day() -> None:
    quote = Quote(
        trading_rows=[
            {"time": "2026-07-29", "trade_date_type": "WHOLE"},
            {"time": "2026-07-30", "trade_date_type": "WHOLE"},
        ]
    )
    provider = FutuProvider(
        quote,
        clock=lambda: datetime(2026, 7, 31, 15, tzinfo=UTC),
    )

    assert provider.latest_completed_trading_day(
        operation_control=control(),
    ) == date(2026, 7, 30)


def candle_row(
    timestamp: str,
    close: str,
) -> dict[str, object]:
    price = Decimal(close)
    return {
        "code": "US.AAPL",
        "time_key": timestamp,
        "open": price - 1,
        "high": price + 1,
        "low": price - 2,
        "close": price,
        "volume": 1000,
    }


def test_all_supported_intervals_map_to_native_futu_kline_types() -> None:
    assert {
        interval: futu_kl_type(interval)
        for interval in (
            CandleInterval.MIN_30,
            CandleInterval.MIN_60,
            CandleInterval.MIN_120,
            CandleInterval.MIN_240,
            CandleInterval.DAY,
            CandleInterval.WEEK,
        )
    } == {
        CandleInterval.MIN_30: "K_30M",
        CandleInterval.MIN_60: "K_60M",
        CandleInterval.MIN_120: "K_120M",
        CandleInterval.MIN_240: "K_240M",
        CandleInterval.DAY: "K_DAY",
        CandleInterval.WEEK: "K_WEEK",
    }


def test_candles_are_unadjusted_regular_session_and_request_up_to_1000() -> None:
    quote = Quote(
        history_pages=[
            [
                candle_row("2026-07-29 10:00:00", "101"),
                candle_row("2026-07-29 09:30:00", "100"),
            ],
            [
                candle_row("2026-07-29 10:30:00", "102"),
                candle_row("2026-07-29 10:00:00", "101"),
            ],
        ]
    )
    provider = FutuProvider(quote, minimum_request_interval=0)

    result = provider.get_candle_series(
        ("AAPL.US",),
        CandleInterval.MIN_30,
        3,
        datetime(2026, 7, 30, tzinfo=UTC),
        operation_control=control(),
    )

    assert len(quote.history_calls) == 2
    assert all(call["max_count"] == 1000 for call in quote.history_calls)
    assert all(call["autype"] == "None" for call in quote.history_calls)
    assert all(call["extended_time"] is False for call in quote.history_calls)
    assert all(call["session"] == "RTH" for call in quote.history_calls)
    candles = result.series_by_symbol["AAPL.US"].candles
    assert [item.close for item in candles] == [
        Decimal(100),
        Decimal(101),
        Decimal(102),
    ]
    assert all(item.timestamp.tzinfo is not None for item in candles)


def test_history_continuation_pages_do_not_consume_first_request_throttle() -> None:
    quote = Quote(
        history_pages=[
            [candle_row("2026-07-29 09:30:00", "100")],
            [candle_row("2026-07-29 10:00:00", "101")],
        ]
    )
    sleeps: list[float] = []
    provider = FutuProvider(
        quote,
        minimum_request_interval=0.5,
        monotonic_clock=lambda: 0.0,
        sleeper=sleeps.append,
    )

    provider.get_candle_series(
        ("AAPL.US",),
        CandleInterval.MIN_30,
        2,
        datetime(2026, 7, 30, tzinfo=UTC),
        operation_control=control(),
    )

    assert sleeps == []


def test_daily_series_uses_only_date_and_close_fields() -> None:
    quote = Quote(
        history_pages=[
            [
                candle_row("2026-07-28 00:00:00", "100"),
                candle_row("2026-07-29 00:00:00", "102"),
            ]
        ]
    )
    provider = FutuProvider(quote, minimum_request_interval=0)

    result = provider.get_daily_series(
        ("AAPL.US",),
        date(2026, 7, 28),
        date(2026, 7, 29),
        operation_control=control(),
    )

    assert quote.history_calls[0]["fields"] == ("1", "3")
    assert quote.history_field_container_types == [list]
    assert [point.close for point in result.series_by_symbol["AAPL.US"].points] == [
        Decimal(100),
        Decimal(102),
    ]


def test_history_quota_shortage_stops_before_any_kline_request() -> None:
    quote = Quote(quota=(100, 0, []))
    provider = FutuProvider(quote, minimum_request_interval=0)

    result = provider.get_candle_series(
        ("AAPL.US",),
        CandleInterval.DAY,
        100,
        datetime(2026, 7, 30, tzinfo=UTC),
        operation_control=control(),
    )

    assert result.errors == {"AAPL.US": "quota_exhausted"}
    assert quote.history_calls == []


def test_recently_used_symbol_can_be_requested_with_zero_remaining_quota() -> None:
    quote = Quote(
        quota=(
            100,
            0,
            [
                {
                    "code": "US.AAPL",
                    "name": "Apple",
                    "request_time": "2026-07-30 10:00:00",
                }
            ],
        ),
        history_pages=[[candle_row("2026-07-29 00:00:00", "100")]],
    )
    provider = FutuProvider(quote, minimum_request_interval=0)

    result = provider.get_candle_series(
        ("AAPL.US",),
        CandleInterval.DAY,
        100,
        datetime(2026, 7, 30, tzinfo=UTC),
        operation_control=control(),
    )

    assert "AAPL.US" in result.series_by_symbol
    assert len(quote.history_calls) == 1


def test_quota_snapshot_is_reused_across_intervals_in_one_provider_session() -> None:
    quote = Quote(
        quota=(0, 100, []),
        history_pages=[
            [candle_row("2026-07-29 00:00:00", "100")],
            [candle_row("2026-07-29 00:00:00", "101")],
        ],
    )
    provider = FutuProvider(quote, minimum_request_interval=0)
    provider.get_history_quota(operation_control=control())

    for interval in (CandleInterval.DAY, CandleInterval.WEEK):
        result = provider.get_candle_series(
            ("AAPL.US",),
            interval,
            100,
            datetime(2026, 7, 30, tzinfo=UTC),
            operation_control=control(),
        )
        assert result.errors.get("AAPL.US") != "quota_exhausted"

    assert quote.quota_calls == 1


def test_repeated_infrastructure_failures_open_shared_history_breaker() -> None:
    class TimeoutQuote(Quote):
        def request_history_kline(self, code: str, **kwargs):
            self.history_calls.append({"code": code, **kwargs})
            return -1, "timeout", None

    quote = TimeoutQuote(quota=(0, 100, []))
    provider = FutuProvider(
        quote,
        minimum_request_interval=0,
        max_retries=0,
    )
    symbols = tuple(f"S{index}.US" for index in range(20))

    result = provider.get_candle_series(
        symbols,
        CandleInterval.DAY,
        100,
        datetime(2026, 7, 30, tzinfo=UTC),
        operation_control=control(),
    )

    assert len(quote.history_calls) == 8
    assert result.errors[symbols[7]] == "timeout"
    assert all(result.errors[symbol] == "circuit_open" for symbol in symbols[8:])
