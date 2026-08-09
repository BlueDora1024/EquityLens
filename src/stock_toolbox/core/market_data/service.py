"""Shared market-data request normalization and provider isolation."""

from __future__ import annotations

from datetime import date, datetime

from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    DailyBarsDataset,
    DailyBarsProviderPort,
    DailySeriesProgressSink,
    ScreeningMarketDataPort,
    SnapshotDataset,
)
from stock_toolbox.core.operations.registry import OperationControl


class SharedMarketDataService:
    """Normalizes one analysis request before crossing the provider boundary."""

    def __init__(
        self,
        provider: DailyBarsProviderPort,
        *,
        daily_provider: DailyBarsProviderPort | None = None,
    ) -> None:
        self._provider = provider
        self._daily_provider = daily_provider or provider

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
        raw = self._daily_provider.get_daily_series(
            normalized,
            start_date,
            end_date,
            operation_control=operation_control,
            progress=progress,
        )
        return DailyBarsDataset(
            raw.provider_id,
            raw.provider_display_name,
            raw.series_by_symbol,
            raw.errors,
            raw.source_by_symbol,
        )

    def get_candle_series(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CandleDataset:
        provider = self._provider
        if not isinstance(provider, ScreeningMarketDataPort):
            raise TypeError("provider does not support screening market data")
        normalized = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        )
        return provider.get_candle_series(
            normalized,
            interval,
            count,
            end_at,
            operation_control=operation_control,
        )

    def get_security_snapshots(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> SnapshotDataset:
        provider = self._provider
        if not isinstance(provider, ScreeningMarketDataPort):
            raise TypeError("provider does not support screening market data")
        normalized = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        )
        return provider.get_security_snapshots(
            normalized,
            operation_control=operation_control,
        )
