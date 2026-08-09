"""Exact-envelope persistent cache for raw daily close series."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from stock_toolbox.core.market_data.models import (
    DailyBarsDataset,
    DailyBarsProviderPort,
    DailySeriesProgress,
    DailySeriesProgressSink,
    PriceSeries,
)
from stock_toolbox.core.operations.registry import OperationControl


class DailySeriesCachePort(Protocol):
    def load(
        self,
        provider_id: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> PriceSeries | None: ...

    def upsert(
        self,
        provider_id: str,
        series: PriceSeries,
        start_date: date,
        end_date: date,
    ) -> None: ...


class CachedDailyBarsProvider:
    """Avoid repeating an identical historical RS envelope."""

    def __init__(
        self,
        provider: DailyBarsProviderPort,
        cache: DailySeriesCachePort,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self.provider_id = str(getattr(provider, "provider_id", "market"))
        self.provider_display_name = str(
            getattr(provider, "provider_display_name", self.provider_id)
        )

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress: DailySeriesProgressSink | None = None,
    ) -> DailyBarsDataset:
        normalized = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        )
        ready = {
            symbol: cached
            for symbol in normalized
            if (
                cached := self._cache.load(
                    self.provider_id,
                    symbol,
                    start_date,
                    end_date,
                )
            )
            is not None
        }
        misses = tuple(symbol for symbol in normalized if symbol not in ready)
        errors: dict[str, str] = {}
        if misses and not operation_control.cancellation_requested():
            remote = self._provider.get_daily_series(
                misses,
                start_date,
                end_date,
                operation_control=operation_control,
                progress=None,
            )
            self.provider_display_name = remote.provider_display_name
            for symbol, series in remote.series_by_symbol.items():
                self._cache.upsert(
                    self.provider_id,
                    series,
                    start_date,
                    end_date,
                )
                ready[symbol] = series
            errors.update(remote.errors)
        elif misses:
            errors.update({symbol: "canceled" for symbol in misses})

        if progress is not None:
            succeeded = failed = 0
            for completed, symbol in enumerate(normalized, start=1):
                if symbol in ready:
                    succeeded += 1
                else:
                    failed += 1
                progress(
                    DailySeriesProgress(
                        completed,
                        len(normalized),
                        symbol,
                        succeeded,
                        failed,
                    )
                )
        ordered = {symbol: ready[symbol] for symbol in normalized if symbol in ready}
        return DailyBarsDataset(
            self.provider_id,
            self.provider_display_name,
            ordered,
            errors,
            {symbol: self.provider_id for symbol in ordered},
        )
