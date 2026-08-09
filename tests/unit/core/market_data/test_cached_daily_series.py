from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from stock_toolbox.core.market_data.daily_cache import CachedDailyBarsProvider
from stock_toolbox.core.market_data.models import (
    DailyBarsDataset,
    PricePoint,
    PriceSeries,
)
from stock_toolbox.core.operations.registry import OperationRegistry


class Cache:
    def __init__(self) -> None:
        self.values = {}

    def load(self, provider_id, symbol, start_date, end_date):
        return self.values.get((provider_id, symbol, start_date, end_date))

    def upsert(self, provider_id, series, start_date, end_date):
        self.values[(provider_id, series.symbol, start_date, end_date)] = series


class Provider:
    provider_id = "yahoo"
    provider_display_name = "Yahoo"

    def __init__(self) -> None:
        self.calls = 0

    def get_daily_series(self, symbols, start_date, end_date, *, operation_control, progress=None):
        del start_date, end_date, operation_control, progress
        self.calls += 1
        return DailyBarsDataset(
            self.provider_id,
            self.provider_display_name,
            {
                symbol: PriceSeries(
                    symbol,
                    (PricePoint(date(2026, 7, 1), Decimal(100)),),
                )
                for symbol in symbols
            },
            {},
        )


def control():
    registry = OperationRegistry(clock=lambda: datetime(2026, 7, 2, tzinfo=UTC))
    registry.reserve("op", "key", "test")
    context = registry.begin_reserved("op")
    assert context is not None
    return context.operation_control


def test_identical_daily_envelope_is_served_from_persistent_cache_port() -> None:
    provider = Provider()
    cached = CachedDailyBarsProvider(provider, Cache())
    arguments = (("AAPL.US",), date(2026, 7, 1), date(2026, 7, 2))

    first = cached.get_daily_series(*arguments, operation_control=control())
    second = cached.get_daily_series(*arguments, operation_control=control())

    assert tuple(first.series_by_symbol) == ("AAPL.US",)
    assert tuple(second.series_by_symbol) == ("AAPL.US",)
    assert provider.calls == 1
