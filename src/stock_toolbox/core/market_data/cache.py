"""Cache-first candle retrieval while preserving the provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Protocol

from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    CandleSeries,
    MarketCandle,
    SnapshotDataset,
)
from stock_toolbox.core.market_data.service import SharedMarketDataService
from stock_toolbox.core.operations.registry import OperationControl


class CandleCachePort(Protocol):
    def load(
        self,
        provider_id: str,
        symbol: str,
        interval: CandleInterval,
        end_at: datetime,
        limit: int,
    ) -> tuple[MarketCandle, ...]: ...

    def upsert(self, provider_id: str, series: CandleSeries) -> None: ...

    def covered_through(
        self,
        provider_id: str,
        symbol: str,
        interval: CandleInterval,
    ) -> datetime | None: ...

    def request_coverage(
        self,
        provider_id: str,
        symbol: str,
        interval: CandleInterval,
    ) -> CandleRequestCoverage | None: ...

    def mark_covered_through(
        self,
        provider_id: str,
        symbol: str,
        interval: CandleInterval,
        end_at: datetime,
        *,
        requested_count: int,
        returned_count: int,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class CandleRequestCoverage:
    covered_through: datetime
    requested_count: int
    returned_count: int


def cache_covers_request(
    coverage: CandleRequestCoverage | None,
    *,
    cached_count: int,
    end_at: datetime,
    requested_count: int,
) -> bool:
    """Whether a previous provider response authoritatively covers this request.

    A provider can legitimately return fewer rows than requested for a newly
    listed security.  Persisting both counts lets a repeated identical request
    reuse that complete short history without treating any arbitrary partial
    cache as complete.
    """

    if coverage is None or coverage.covered_through < end_at:
        return False
    if coverage.requested_count < requested_count:
        return False
    expected_rows = min(requested_count, coverage.returned_count)
    return expected_rows > 0 and cached_count >= expected_rows


@dataclass(frozen=True, slots=True)
class CandleCacheStats:
    cache_hits: int
    fetched: int
    failures: int


@dataclass(frozen=True, slots=True)
class CachedCandleResult:
    dataset: CandleDataset
    stats: CandleCacheStats


class CachedCandleService:
    def __init__(
        self,
        market_data: SharedMarketDataService,
        cache: CandleCachePort,
        provider_id: str,
        provider_display_name: str | None = None,
    ) -> None:
        self._market_data = market_data
        self._cache = cache
        self._provider_id = provider_id
        self._provider_display_name = provider_display_name or provider_id

    def get(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CachedCandleResult:
        normalized = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        )
        cached: dict[str, tuple[MarketCandle, ...]] = {
            symbol: self._cache.load(self._provider_id, symbol, interval, end_at, count)
            for symbol in normalized
        }
        coverage = {
            symbol: self._cache.request_coverage(
                self._provider_id,
                symbol,
                interval,
            )
            for symbol in normalized
        }
        misses = tuple(
            symbol
            for symbol in normalized
            if not cache_covers_request(
                coverage[symbol],
                cached_count=len(cached[symbol]),
                end_at=end_at,
                requested_count=count,
            )
        )
        errors: dict[str, str] = {}
        fetched = 0
        if misses and not operation_control.cancellation_requested():
            request_counts = {
                symbol: _tail_request_count(
                    interval,
                    count,
                    len(cached[symbol]),
                    _covered_through(coverage[symbol]),
                    end_at,
                )
                for symbol in misses
            }
            # The provider port accepts one count for the whole batch.  Use the
            # largest required tail so every symbol in this call remains safe.
            remote_count = max(request_counts.values())
            remote = self._market_data.get_candle_series(
                misses,
                interval,
                remote_count,
                end_at,
                operation_control=operation_control,
            )
            self._provider_display_name = remote.provider_display_name
            for symbol in misses:
                series = remote.series_by_symbol.get(symbol)
                if series is None:
                    errors[symbol] = remote.errors.get(symbol, "candles_unavailable")
                    continue
                self._cache.upsert(self._provider_id, series)
                cached[symbol] = self._cache.load(
                    self._provider_id, symbol, interval, end_at, count
                )
                self._cache.mark_covered_through(
                    self._provider_id,
                    symbol,
                    interval,
                    end_at,
                    requested_count=count,
                    returned_count=len(cached[symbol]),
                )
                fetched += 1

        output = {
            symbol: CandleSeries(symbol, interval, candles)
            for symbol, candles in cached.items()
            if candles and symbol not in errors
        }
        return CachedCandleResult(
            CandleDataset(
                self._provider_id,
                self._provider_display_name,
                interval,
                output,
                errors,
            ),
            CandleCacheStats(
                len(normalized) - len(misses),
                fetched,
                len(errors),
            ),
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
        """Expose the provider port shape for cache-first analysis services."""

        return self.get(
            symbols,
            interval,
            count,
            end_at,
            operation_control=operation_control,
        ).dataset

    def get_security_snapshots(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> SnapshotDataset:
        return self._market_data.get_security_snapshots(
            symbols,
            operation_control=operation_control,
        )


_MAX_REGULAR_BARS_PER_DAY = {
    CandleInterval.MIN_30: 13,
    CandleInterval.MIN_60: 7,
    CandleInterval.MIN_120: 4,
    CandleInterval.MIN_240: 2,
    CandleInterval.DAY: 1,
}


def _covered_through(coverage: CandleRequestCoverage | None) -> datetime | None:
    return coverage.covered_through if coverage is not None else None


def _tail_request_count(
    interval: CandleInterval,
    requested_count: int,
    cached_count: int,
    covered_through: datetime | None,
    end_at: datetime,
) -> int:
    """Return a conservative tail size without trusting row count as freshness.

    The cache watermark records the requested completed-bar boundary, including
    weekends and holidays where the latest actual candle can legitimately be
    older.  Existing databases have no watermark, so their first read performs
    one full safe refresh.  Once covered, a calendar-day upper bound plus a
    small overlap is enough to bridge the old and new tails idempotently.
    """

    if cached_count < requested_count or covered_through is None:
        return requested_count
    elapsed_seconds = max(0.0, (end_at - covered_through).total_seconds())
    elapsed_days = max(1, ceil(elapsed_seconds / 86_400))
    if interval is CandleInterval.WEEK:
        estimated = ceil(elapsed_days / 7) + 2
    else:
        estimated = elapsed_days * _MAX_REGULAR_BARS_PER_DAY[interval] + 4
    return min(requested_count, max(1, estimated))
