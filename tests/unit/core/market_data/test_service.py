from __future__ import annotations

from datetime import date
from decimal import Decimal

from stock_toolbox.core.market_data.models import (
    DailyBarsDataset,
    DailySeriesProgress,
    PricePoint,
    PriceSeries,
)
from stock_toolbox.core.market_data.service import SharedMarketDataService
from stock_toolbox.core.operations.registry import OperationControl


class _Control:
    def cancellation_requested(self) -> bool:
        return False


class _Provider:
    def __init__(self) -> None:
        self.requested_symbols: tuple[str, ...] = ()
        self.progress = None

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress=None,
    ) -> DailyBarsDataset:
        del start_date, end_date, operation_control
        self.requested_symbols = symbols
        self.progress = progress
        return DailyBarsDataset(
            "virtual",
            "Virtual Provider",
            {
                symbol: PriceSeries(
                    symbol,
                    (PricePoint(date(2026, 7, 24), Decimal(1)),),
                )
                for symbol in symbols
            },
            {},
        )


def test_shared_service_normalizes_and_deduplicates_symbols() -> None:
    provider = _Provider()
    service = SharedMarketDataService(provider)

    result = service.get_daily_series(
        (" aapl.us ", "AAPL.US", "spy.us"),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=_Control(),
    )

    assert provider.requested_symbols == ("AAPL.US", "SPY.US")
    assert tuple(result.series_by_symbol) == ("AAPL.US", "SPY.US")
    assert result.provider_id == "virtual"


def test_shared_service_returns_defensive_immutable_maps() -> None:
    provider = _Provider()
    result = SharedMarketDataService(provider).get_daily_series(
        ("AAPL.US",),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=_Control(),
    )

    assert type(result.series_by_symbol).__name__ == "mappingproxy"
    assert type(result.errors).__name__ == "mappingproxy"


def test_shared_service_forwards_daily_series_progress() -> None:
    provider = _Provider()
    events: list[DailySeriesProgress] = []

    SharedMarketDataService(provider).get_daily_series(
        ("AAPL.US",),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=_Control(),
        progress=events.append,
    )

    assert provider.progress == events.append
