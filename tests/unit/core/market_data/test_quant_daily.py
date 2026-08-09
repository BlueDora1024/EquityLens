from __future__ import annotations

from datetime import date
from decimal import Decimal

from stock_toolbox.core.market_data.models import (
    DailyBarsDataset,
    PricePoint,
    PriceSeries,
)
from stock_toolbox.core.market_data.quant import QuantSeriesDataset
from stock_toolbox.core.market_data.quant_daily import QuantDailyBarsService


class _Control:
    def cancellation_requested(self) -> bool:
        return False

    def wait_for_cancellation(self, _timeout: float) -> bool:
        return False


class _MalformedQuant:
    def get_quant_series(self, symbols, _request, *, operation_control, progress=None):
        del operation_control, progress
        return QuantSeriesDataset(
            "longbridge",
            "Longbridge",
            {},
            {symbol: "malformed_quant_response" for symbol in symbols},
        )


class _NativeDaily:
    provider_id = "longbridge"
    provider_display_name = "Longbridge"

    def __init__(self) -> None:
        self.requests: list[tuple[str, ...]] = []

    def get_daily_series(
        self,
        symbols,
        start_date,
        end_date,
        *,
        operation_control,
        progress=None,
    ):
        del end_date, operation_control, progress
        self.requests.append(symbols)
        return DailyBarsDataset(
            self.provider_id,
            self.provider_display_name,
            {
                symbol: PriceSeries(
                    symbol,
                    (
                        PricePoint(start_date, Decimal(10)),
                        PricePoint(date(2026, 8, 7), Decimal(12)),
                    ),
                )
                for symbol in symbols
            },
            {},
        )


def test_quant_daily_recovers_only_failed_symbols_with_native_longbridge() -> None:
    native = _NativeDaily()
    service = QuantDailyBarsService(
        _MalformedQuant(),
        etf_fallback=native,
    )

    result = service.get_daily_series(
        ("NBSE.US",),
        date(2025, 8, 1),
        date(2026, 8, 7),
        operation_control=_Control(),  # type: ignore[arg-type]
    )

    assert native.requests == [("NBSE.US",)]
    assert tuple(result.series_by_symbol) == ("NBSE.US",)
    assert result.errors == {}
    assert result.source_by_symbol["NBSE.US"] == "longbridge"


def test_quant_daily_does_not_native_retry_fatal_failures() -> None:
    class _FatalQuant:
        def get_quant_series(
            self,
            symbols,
            _request,
            *,
            operation_control,
            progress=None,
        ):
            del operation_control, progress
            return QuantSeriesDataset(
                "longbridge",
                "Longbridge",
                {},
                {symbol: "authentication_failed" for symbol in symbols},
            )

    native = _NativeDaily()
    service = QuantDailyBarsService(_FatalQuant(), etf_fallback=native)

    result = service.get_daily_series(
        ("NBSE.US",),
        date(2025, 8, 1),
        date(2026, 8, 7),
        operation_control=_Control(),  # type: ignore[arg-type]
    )

    assert native.requests == []
    assert result.errors == {"NBSE.US": "authentication_failed"}
