"""Provider-independent contract for server-side indicator execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Protocol

from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.core.operations.run_feedback import RunFeedback


@dataclass(frozen=True, slots=True)
class QuantSeriesRequest:
    script_version: str
    interval: CandleInterval
    start_at: datetime
    end_at: datetime
    script: str
    series_names: tuple[str, ...]
    retain_last: int | None = None

    def __post_init__(self) -> None:
        names = tuple(name.strip() for name in self.series_names)
        if (
            not self.script_version.strip()
            or not self.script.strip()
            or self.start_at.tzinfo is None
            or self.end_at.tzinfo is None
            or self.start_at > self.end_at
            or not names
            or any(not name for name in names)
            or len(names) != len(set(names))
            or (
                self.retain_last is not None
                and self.retain_last < 1
            )
        ):
            raise ValueError("invalid quant request series or range")
        object.__setattr__(self, "series_names", names)


@dataclass(frozen=True, slots=True)
class QuantSeries:
    symbol: str
    interval: CandleInterval
    timestamps: tuple[datetime, ...]
    values: Mapping[str, tuple[float | None, ...]]
    source_count: int | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        timestamps = tuple(self.timestamps)
        values = {
            str(name): tuple(series)
            for name, series in self.values.items()
        }
        source_count = (
            len(timestamps)
            if self.source_count is None
            else self.source_count
        )
        if (
            not symbol
            or any(item.tzinfo is None for item in timestamps)
            or any(
                len(series) != len(timestamps)
                for series in values.values()
            )
            or source_count < len(timestamps)
        ):
            message = (
                "quant source count cannot be smaller than retained count"
                if source_count < len(timestamps)
                else "quant series must be aligned"
            )
            raise ValueError(message)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "timestamps", timestamps)
        object.__setattr__(self, "values", MappingProxyType(values))
        object.__setattr__(self, "source_count", source_count)

    @property
    def retained_count(self) -> int:
        return len(self.timestamps)


@dataclass(frozen=True, slots=True)
class QuantSeriesDataset:
    provider_id: str
    provider_display_name: str
    series_by_symbol: Mapping[str, QuantSeries]
    errors: Mapping[str, str]
    cache_hits: int = 0
    fetched: int = 0
    source_by_symbol: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "series_by_symbol",
            MappingProxyType(dict(self.series_by_symbol)),
        )
        object.__setattr__(self, "errors", MappingProxyType(dict(self.errors)))
        object.__setattr__(
            self,
            "source_by_symbol",
            MappingProxyType(
                dict(self.source_by_symbol)
                or {
                    symbol: self.provider_id
                    for symbol in self.series_by_symbol
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class QuantProgress:
    completed: int
    total: int
    current_symbol: str
    succeeded: int
    failed: int
    cache_hits: int = 0
    feedback: RunFeedback | None = None


QuantProgressSink = Callable[[QuantProgress], None]


class QuantMarketDataPort(Protocol):
    def get_quant_series(
        self,
        symbols: tuple[str, ...],
        request: QuantSeriesRequest,
        *,
        operation_control: OperationControl,
        progress: QuantProgressSink | None = None,
    ) -> QuantSeriesDataset: ...


class QuantResultCachePort(Protocol):
    def load_many(
        self,
        provider_id: str,
        symbols: tuple[str, ...],
        request: QuantSeriesRequest,
    ) -> Mapping[str, QuantSeries]: ...

    def upsert_many(
        self,
        provider_id: str,
        request: QuantSeriesRequest,
        series: tuple[QuantSeries, ...],
    ) -> None: ...


class CachedQuantMarketDataService:
    """Share immutable completed-bar indicator results across stock pools."""

    def __init__(
        self,
        provider: QuantMarketDataPort,
        cache: QuantResultCachePort,
        provider_id: str,
        provider_display_name: str,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._provider_id = provider_id
        self._provider_name = provider_display_name

    def get_quant_series(
        self,
        symbols: tuple[str, ...],
        request: QuantSeriesRequest,
        *,
        operation_control: OperationControl,
        progress: QuantProgressSink | None = None,
    ) -> QuantSeriesDataset:
        normalized = tuple(
            dict.fromkeys(
                symbol.strip().upper()
                for symbol in symbols
                if symbol.strip()
            )
        )
        ready = dict(
            self._cache.load_many(
                self._provider_id,
                normalized,
                request,
            )
        )
        missing = [
            symbol for symbol in normalized if symbol not in ready
        ]
        if progress is not None:
            for completed, symbol in enumerate(ready, start=1):
                progress(
                    QuantProgress(
                        completed,
                        len(normalized),
                        symbol,
                        completed,
                        0,
                        completed,
                    )
                )

        cached_count = len(ready)

        def report_fetched(item: QuantProgress) -> None:
            if progress is not None:
                progress(
                    QuantProgress(
                        cached_count + item.completed,
                        len(normalized),
                        item.current_symbol,
                        cached_count + item.succeeded,
                        item.failed,
                        cached_count,
                        item.feedback,
                    )
                )

        fetched = self._provider.get_quant_series(
            tuple(missing),
            request,
            operation_control=operation_control,
            progress=report_fetched,
        )
        fetched_series = tuple(fetched.series_by_symbol.values())
        self._cache.upsert_many(
            self._provider_id,
            request,
            fetched_series,
        )
        ready.update(fetched.series_by_symbol)
        return QuantSeriesDataset(
            self._provider_id,
            self._provider_name,
            ready,
            fetched.errors,
            cache_hits=len(ready) - len(fetched.series_by_symbol),
            fetched=len(fetched.series_by_symbol),
        )
