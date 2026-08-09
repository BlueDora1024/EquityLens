"""Cache-only resource preflight shared by the analysis tools."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from typing import Protocol

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import (
    SCRIPT_VERSION as EXTREME_VERSION,
)
from stock_toolbox.analyses.rs_strength.application.models import RunRequest
from stock_toolbox.analyses.rs_strength.application.service import (
    requested_envelope,
)
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
)
from stock_toolbox.analyses.turning_point.application.quant import (
    SCRIPT_VERSION as TURNING_VERSION,
)
from stock_toolbox.analyses.turning_point.application.quant import (
    request_for as turning_request_for,
)
from stock_toolbox.core.market_data.budget import (
    DEFAULT_COLD_REQUEST_BUDGET,
    RequestBudget,
    estimate_multi_period,
    estimate_rs,
)
from stock_toolbox.core.market_data.models import (
    CandleInterval,
    MarketCandle,
    PriceSeries,
)
from stock_toolbox.core.market_data.provider_health import HistoryQuotaSnapshot
from stock_toolbox.core.market_data.quant import (
    QuantResultCachePort,
    QuantSeriesRequest,
)
from stock_toolbox.core.market_data.quant_daily import (
    SCRIPT_VERSION as DAILY_VERSION,
)
from stock_toolbox.core.market_data.quant_daily import daily_request_for
from stock_toolbox.core.market_data.request_plan import (
    PhysicalRequestPlan,
    plan_extreme_requests,
    plan_rs_requests,
    plan_turning_requests,
)
from stock_toolbox.core.master_data.models import SecurityDetailDTO, WatchlistDTO
from stock_toolbox.core.operations.storage_guard import (
    READY_FREE_BYTES,
    StorageCheck,
    StorageState,
)


class BudgetMasterDataPort(Protocol):
    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO: ...

    def get_security(self, security_id: str) -> SecurityDetailDTO: ...


class StorageInspectionPort(Protocol):
    def inspect(self) -> StorageCheck: ...


class CandleBudgetCachePort(Protocol):
    def load(
        self,
        provider_id: str,
        symbol: str,
        interval: CandleInterval,
        end_at: datetime,
        limit: int,
    ) -> tuple[MarketCandle, ...]: ...

    def covered_through(
        self,
        provider_id: str,
        symbol: str,
        interval: CandleInterval,
    ) -> datetime | None: ...


class DailyBudgetCachePort(Protocol):
    def load(
        self,
        provider_id: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> PriceSeries | None: ...


@dataclass(frozen=True, slots=True)
class AnalysisBudgetSnapshot:
    member_count: int
    dimension_count: int
    total_tasks: int
    cache_hits: int
    cold_requests: int
    cold_limit: int
    data_path: str
    storage_state: StorageState = StorageState.READY
    free_bytes: int = READY_FREE_BYTES
    cache_cleaned: bool = False
    reusable_bytes: int = 0
    error_code: str = ""
    quota_remaining: int | None = None
    quota_new_symbols: int | None = None
    quota_shortfall: int = 0
    calculation_calls: int = 0
    annotation_calls: int = 0
    quota_checks: int = 0
    minimum_seconds: float = 0.0
    provider_page_size: int = 0
    provider_id: str = ""

    @property
    def requires_confirmation(self) -> bool:
        return self.cold_requests > self.cold_limit or self.quota_shortfall > 0

    @property
    def quota_blocked(self) -> bool:
        return self.provider_id == "futu" and self.quota_shortfall > 0

    @property
    def can_force_yahoo(self) -> bool:
        return self.provider_id == "futu" and (
            self.quota_blocked or self.cold_requests > self.cold_limit
        )

    @property
    def can_confirm_primary(self) -> bool:
        return not self.quota_blocked

    @property
    def effective_available_bytes(self) -> int:
        return max(0, self.free_bytes) + self.reusable_bytes

    @property
    def quota_notice(self) -> str:
        if self.quota_remaining is None or self.quota_new_symbols is None:
            return ""
        if self.quota_shortfall:
            return (
                "富途历史额度不足：本次新增 "
                f"{self.quota_new_symbols}，剩余 {self.quota_remaining}，"
                f"缺口 {self.quota_shortfall}"
            )
        return f"富途历史额度：本次新增 {self.quota_new_symbols}，剩余 {self.quota_remaining}"

    @property
    def futu_serial_notice(self) -> str:
        if self.provider_id != "futu" or self.cold_requests <= self.cold_limit:
            return ""
        minutes = max(1, math.ceil(self.minimum_seconds / 60))
        return (
            "富途历史 K 线严格串行，首次请求至少间隔 0.5 秒（约 2 次/秒）。"
            f"本次预计 {self.cold_requests} 次外部请求，最快约 {minutes} 分钟；"
            "可继续使用富途，或改用较慢但可批量下载的 Yahoo 备用行情从第一步重算。"
        )


class AnalysisBudgetService:
    """Estimate provider work without making any provider request."""

    def __init__(
        self,
        master_data: BudgetMasterDataPort,
        cache: QuantResultCachePort,
        *,
        provider_id: str,
        provider_display_name: str,
        quant_script_versions: set[str] | frozenset[str],
        cold_limit: int = DEFAULT_COLD_REQUEST_BUDGET,
        storage_guard: StorageInspectionPort | None = None,
        history_quota: Callable[[], HistoryQuotaSnapshot] | None = None,
        candle_cache: CandleBudgetCachePort | None = None,
        daily_cache: DailyBudgetCachePort | None = None,
    ) -> None:
        self._master = master_data
        self._cache = cache
        self._provider_id = provider_id.strip()
        self._provider_name = provider_display_name.strip()
        self._versions = frozenset(quant_script_versions)
        self._cold_limit = cold_limit
        self._storage = storage_guard
        self._history_quota = history_quota
        self._candle_cache = candle_cache
        self._daily_cache = daily_cache

    def estimate_rs(self, request: RunRequest) -> AnalysisBudgetSnapshot:
        symbols = self._symbols(request.watchlist_id)
        start_date, end_date = requested_envelope(request)
        quant_request = daily_request_for(start_date, end_date)
        all_symbols = (request.benchmark_symbol, *symbols)
        hit_symbols = self._hit_symbols(
            all_symbols,
            quant_request,
            DAILY_VERSION,
        )
        if DAILY_VERSION not in self._versions and self._daily_cache is not None:
            hit_symbols = frozenset(
                symbol
                for symbol in all_symbols
                if self._daily_cache.load(
                    self._provider_id,
                    symbol,
                    start_date,
                    end_date,
                )
                is not None
            )
        cache_hits = len(hit_symbols)
        budget = estimate_rs(
            member_count=len(symbols),
            range_count=(len(set(request.preset_ranges)) + int(request.custom_range is not None)),
            cache_hits=cache_hits,
            cold_limit=self._cold_limit,
        )
        physical = plan_rs_requests(
            self._provider_id,
            member_count=len(symbols),
            cache_hits=cache_hits,
            quant_supported=DAILY_VERSION in self._versions,
        )
        return self._snapshot(
            len(symbols),
            len(set(request.preset_ranges)) + int(request.custom_range is not None),
            budget,
            DAILY_VERSION,
            all_symbols,
            physical,
            quota_symbols=tuple(
                symbol for symbol in all_symbols if symbol not in hit_symbols
            ),
        )

    def estimate_turning(
        self,
        request: TurningPointRequest,
    ) -> AnalysisBudgetSnapshot:
        symbols = self._symbols(request.watchlist_id)
        native_intervals = {
            CandleInterval.MIN_120,
            CandleInterval.MIN_240,
        }
        hit_count_by_symbol = {symbol: 0 for symbol in symbols}
        quant_hit_sets = tuple(
            self._hit_symbols(
                symbols,
                turning_request_for(interval, request.requested_end_date),
                TURNING_VERSION,
            )
            for interval in request.intervals
            if not (self._provider_id == "longbridge" and interval in native_intervals)
        )
        quant_cache_hits = sum(len(items) for items in quant_hit_sets)
        for items in quant_hit_sets:
            for symbol in items:
                hit_count_by_symbol[symbol] += 1
        raw_intervals = (
            tuple(interval for interval in request.intervals if interval in native_intervals)
            if self._provider_id == "longbridge" and TURNING_VERSION in self._versions
            else (() if TURNING_VERSION in self._versions else request.intervals)
        )
        end_at = datetime.combine(request.requested_end_date, time.max, UTC)
        raw_hit_sets = self._candle_hit_sets(
            symbols,
            raw_intervals,
            220,
            end_at,
        )
        raw_cache_hits = sum(len(items) for items in raw_hit_sets)
        for items in raw_hit_sets:
            for symbol in items:
                hit_count_by_symbol[symbol] += 1
        cache_hits = quant_cache_hits + raw_cache_hits
        # Only the matched rows actually need a market-value snapshot.  The
        # preflight deliberately reserves one batch per 100 pool members so
        # the estimate stays conservative while the signal calculation itself
        # remains the only per-symbol/per-period work.
        extra_requests = math.ceil(len(symbols) / 100)
        budget = estimate_multi_period(
            member_count=len(symbols),
            period_count=len(request.intervals),
            cache_hits=cache_hits,
            extra_requests=extra_requests,
            cold_limit=self._cold_limit,
        )
        physical = plan_turning_requests(
            self._provider_id,
            member_count=len(symbols),
            intervals=request.intervals,
            quant_cache_hits=quant_cache_hits,
            raw_cache_hits=raw_cache_hits,
            quant_supported=TURNING_VERSION in self._versions,
        )
        snapshot = self._snapshot(
            len(symbols),
            len(request.intervals),
            budget,
            TURNING_VERSION,
            symbols,
            physical,
            quota_symbols=tuple(
                symbol
                for symbol, count in hit_count_by_symbol.items()
                if count < len(request.intervals)
            ),
        )
        if self._provider_id == "longbridge" and any(
            interval in native_intervals for interval in request.intervals
        ):
            return replace(
                snapshot,
                data_path=(
                    "Longbridge 服务端量化 + 原生 2/4 小时 K 线"
                    if any(interval not in native_intervals for interval in request.intervals)
                    else "Longbridge 原生 2/4 小时 K 线 · 本地算法"
                ),
            )
        return snapshot

    def estimate_extreme(
        self,
        request: ExtremeDeviationRequest,
    ) -> AnalysisBudgetSnapshot:
        symbols: tuple[str, ...]
        if request.security_id:
            symbols = (self._master.get_security(request.security_id).canonical_symbol,)
        else:
            pool_symbols = self._symbols(request.watchlist_id)
            symbols = request.selected_symbols or pool_symbols
        # The frozen extreme-deviation implementation intentionally uses raw
        # OHLC plus the local corrected formula.  Quant-result rows are not
        # interchangeable and must not reduce the physical request estimate.
        end_at = datetime.combine(request.requested_end_date, time.max, UTC)
        hit_sets = self._candle_hit_sets(
            symbols,
            request.intervals,
            650,
            end_at,
        )
        cache_hits = sum(len(items) for items in hit_sets)
        complete_symbols = (
            set.intersection(*(set(items) for items in hit_sets))
            if hit_sets
            else set()
        )
        budget = estimate_multi_period(
            member_count=len(symbols),
            period_count=len(request.intervals),
            cache_hits=cache_hits,
            cold_limit=self._cold_limit,
        )
        physical = plan_extreme_requests(
            self._provider_id,
            member_count=len(symbols),
            intervals=request.intervals,
            cache_hits=cache_hits,
        )
        return self._snapshot(
            len(symbols),
            len(request.intervals),
            budget,
            EXTREME_VERSION,
            symbols,
            physical,
            force_raw=True,
            quota_symbols=tuple(
                symbol for symbol in symbols if symbol not in complete_symbols
            ),
        )

    def _symbols(self, watchlist_id: str) -> tuple[str, ...]:
        watchlist = self._master.get_watchlist(watchlist_id)
        return tuple(membership.canonical_symbol for membership in watchlist.memberships)

    def _hits(
        self,
        symbols: tuple[str, ...],
        request: QuantSeriesRequest,
        script_version: str,
    ) -> int:
        return len(self._hit_symbols(symbols, request, script_version))

    def _hit_symbols(
        self,
        symbols: tuple[str, ...],
        request: QuantSeriesRequest,
        script_version: str,
    ) -> frozenset[str]:
        if script_version not in self._versions:
            return frozenset()
        return frozenset(
            self._cache.load_many(
                self._provider_id,
                symbols,
                request,
            )
        )

    def _candle_hits(
        self,
        symbols: tuple[str, ...],
        intervals: tuple[CandleInterval, ...],
        count: int,
        end_at: datetime,
    ) -> int:
        return sum(
            len(items)
            for items in self._candle_hit_sets(symbols, intervals, count, end_at)
        )

    def _candle_hit_sets(
        self,
        symbols: tuple[str, ...],
        intervals: tuple[CandleInterval, ...],
        count: int,
        end_at: datetime,
    ) -> tuple[frozenset[str], ...]:
        if self._candle_cache is None:
            return tuple(frozenset() for _interval in intervals)
        hits_by_interval: list[frozenset[str]] = []
        for interval in intervals:
            hits: set[str] = set()
            for symbol in symbols:
                coverage = self._candle_cache.covered_through(
                    self._provider_id,
                    symbol,
                    interval,
                )
                if coverage is None or coverage < end_at:
                    continue
                if (
                    len(
                        self._candle_cache.load(
                            self._provider_id,
                            symbol,
                            interval,
                            end_at,
                            count,
                        )
                    )
                    >= count
                ):
                    hits.add(symbol)
            hits_by_interval.append(frozenset(hits))
        return tuple(hits_by_interval)

    def _snapshot(
        self,
        member_count: int,
        dimension_count: int,
        budget: RequestBudget,
        script_version: str,
        symbols: tuple[str, ...],
        physical: PhysicalRequestPlan,
        *,
        force_raw: bool = False,
        quota_symbols: tuple[str, ...] | None = None,
    ) -> AnalysisBudgetSnapshot:
        if script_version in self._versions and not force_raw:
            data_path = f"{self._provider_name} 服务端量化"
        elif self._provider_id == "futu":
            data_path = "富途本机 OpenD · 本地算法"
        else:
            data_path = f"{self._provider_name} 原始行情兼容"
        storage = (
            self._storage.inspect()
            if self._storage is not None
            else StorageCheck(StorageState.READY, READY_FREE_BYTES)
        )
        quota_remaining: int | None = None
        quota_new_symbols: int | None = None
        quota_shortfall = 0
        if self._history_quota is not None:
            quota = self._history_quota()
            requested = frozenset(symbols if quota_symbols is None else quota_symbols)
            quota_remaining = quota.remaining
            quota_new_symbols = len(requested - quota.reusable_symbols)
            quota_shortfall = max(
                0,
                quota_new_symbols - quota_remaining,
            )
        return AnalysisBudgetSnapshot(
            member_count=member_count,
            dimension_count=dimension_count,
            total_tasks=budget.total_tasks,
            cache_hits=budget.cache_hits,
            cold_requests=physical.provider_calls,
            cold_limit=physical.warning_threshold,
            data_path=data_path,
            storage_state=storage.state,
            free_bytes=storage.free_bytes,
            cache_cleaned=storage.cleaned,
            reusable_bytes=storage.reusable_bytes,
            error_code=storage.error_code,
            quota_remaining=quota_remaining,
            quota_new_symbols=quota_new_symbols,
            quota_shortfall=quota_shortfall,
            calculation_calls=physical.calculation_calls,
            annotation_calls=physical.annotation_calls,
            quota_checks=physical.quota_checks,
            minimum_seconds=physical.minimum_seconds,
            provider_page_size=physical.page_size,
            provider_id=self._provider_id,
        )
