"""Coordinate a cache-first completed-bar extreme-deviation run."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time
from typing import Protocol

from stock_toolbox.analyses.extreme_deviation.application.models import (
    DeviationChartPoint,
    ExtremeDeviationProgress,
    ExtremeDeviationRequest,
    ExtremeDeviationRun,
    ExtremeDeviationRunResult,
    ExtremeDeviationRunStatus,
    FrozenSecurity,
    PeriodOutcome,
    SymbolDeviationResult,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import (
    SUPPORTED_INTERVALS,
    request_for,
)
from stock_toolbox.analyses.extreme_deviation.domain.consensus import build_consensus
from stock_toolbox.analyses.extreme_deviation.domain.indicator import (
    ExtremeDeviationIndicator,
)
from stock_toolbox.analyses.extreme_deviation.domain.models import IndicatorPoint
from stock_toolbox.analyses.extreme_deviation.domain.scoring import score_latest, score_series
from stock_toolbox.core.market_data.cache import CachedCandleResult
from stock_toolbox.core.market_data.fallback import (
    FallbackOffer,
    FallbackSession,
    eligible_fallback_errors,
    provider_summary,
    record_source,
)
from stock_toolbox.core.market_data.models import CandleInterval, CandleSeries
from stock_toolbox.core.market_data.quant import (
    QuantMarketDataPort,
    QuantProgress,
    QuantSeries,
)
from stock_toolbox.core.market_data.service import SharedMarketDataService
from stock_toolbox.core.master_data.models import SecurityDetailDTO, WatchlistDTO
from stock_toolbox.core.operations.failure_policy import (
    RunTerminal,
    freeze_reliability,
    reliability_summary,
)
from stock_toolbox.core.operations.registry import (
    OperationControl,
    OperationExecutionContext,
)


class ExtremeDeviationMasterDataPort(Protocol):
    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO: ...

    def get_security(self, security_id: str) -> SecurityDetailDTO: ...


class ExtremeDeviationMarketDataPort(Protocol):
    def get(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CachedCandleResult: ...


class ExtremeDeviationHistoryPort(Protocol):
    def save_extreme_deviation(self, run: ExtremeDeviationRun) -> None: ...


class StartExtremeDeviationRun:
    def __init__(
        self,
        master_data: ExtremeDeviationMasterDataPort,
        market_data: ExtremeDeviationMarketDataPort,
        history_store: ExtremeDeviationHistoryPort,
        *,
        quant_market_data: QuantMarketDataPort | None = None,
        fallback_market_data: SharedMarketDataService | None = None,
        fallback_session: FallbackSession | None = None,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
        progress: Callable[[ExtremeDeviationProgress], None] = lambda _item: None,
    ) -> None:
        self._master = master_data
        self._market = market_data
        self._history = history_store
        self._quant = quant_market_data
        self._fallback_market = fallback_market_data
        self._fallback_session = fallback_session
        self._clock = clock
        self._new_id = new_id
        self._progress = progress

    def execute(
        self,
        request: ExtremeDeviationRequest,
        context: OperationExecutionContext,
    ) -> ExtremeDeviationRunResult:
        control = context.operation_control
        self._progress(ExtremeDeviationProgress("FREEZE_WATCHLIST", 0, 1))
        selected_symbol_invalid = False
        frozen: tuple[FrozenSecurity, ...]
        symbols: tuple[str, ...]
        watchlist_name: str
        watchlist_revision: int
        if request.security_id:
            try:
                selected_security = self._master.get_security(request.security_id)
            except (KeyError, ValueError):
                selected_security = None
            if selected_security is not None:
                binding = (
                    selected_security.bindings[0]
                    if selected_security.bindings
                    else None
                )
                frozen = (
                    FrozenSecurity(
                        selected_security.canonical_symbol,
                        selected_security.display_name,
                        binding.classification_name if binding else "未分类",
                    ),
                )
                symbols = (selected_security.canonical_symbol,)
                watchlist_name = "单证券复盘"
                watchlist_revision = 0
            else:
                frozen = ()
                symbols = ()
                watchlist_name = ""
                watchlist_revision = 0
        else:
            try:
                watchlist = self._master.get_watchlist(request.watchlist_id)
            except (KeyError, ValueError):
                watchlist = None
            if watchlist is not None:
                by_symbol = {
                    item.canonical_symbol: item for item in watchlist.memberships
                }
                selected = tuple(
                    dict.fromkeys(
                        symbol.strip().upper()
                        for symbol in request.selected_symbols
                        if symbol.strip()
                    )
                )
                selected_symbol_invalid = any(symbol not in by_symbol for symbol in selected)
                symbols = selected or tuple(by_symbol)
                frozen = tuple(
                    FrozenSecurity(
                        symbol,
                        by_symbol[symbol].company_name,
                        by_symbol[symbol].participating_classification_name,
                    )
                    for symbol in symbols
                    if symbol in by_symbol
                )
                watchlist_name = watchlist.display_name
                watchlist_revision = watchlist.revision
            else:
                symbols = ()
                frozen = ()
                watchlist_name = ""
                watchlist_revision = 0
        if selected_symbol_invalid:
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.FAILED,
                error_code="selected_symbol_not_in_watchlist",
            )
        if not frozen:
            reliability = reliability_summary(
                0,
                0,
                0,
                core_input_valid=False,
                canceled=control.cancellation_requested(),
            )
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.FAILED,
                error_code="security_freeze_failed" if request.security_id else "watchlist_freeze_failed",
                reliability=freeze_reliability(
                    reliability,
                    circuit_opened=False,
                    primary_failure_code="security_freeze_failed" if request.security_id else "watchlist_freeze_failed",
                ),
            )
        if not request.security_id and len(frozen) > 600:
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.FAILED,
                error_code="watchlist_too_large",
            )
        intervals = tuple(dict.fromkeys(request.intervals))
        if not intervals:
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.FAILED,
                error_code="interval_required",
            )
        if any(interval not in SUPPORTED_INTERVALS for interval in intervals):
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.FAILED,
                error_code="unsupported_interval",
            )
        started_at = self._clock()
        end_at = datetime.combine(request.requested_end_date, time.max, UTC)
        outcomes: dict[str, list[PeriodOutcome]] = {symbol: [] for symbol in symbols}
        cache_hits = fetched = failures = 0
        provider_id = provider_name = ""
        source_by_symbol: dict[str, str] = {}
        actual_dates: list[datetime] = []
        total = len(symbols) * len(intervals)
        completed = 0
        self._progress(ExtremeDeviationProgress("CHECK_CACHE", 0, total))
        for interval in intervals:
            if control.cancellation_requested():
                return ExtremeDeviationRunResult(ExtremeDeviationRunStatus.CANCELED)
            self._progress(
                ExtremeDeviationProgress(
                    "FETCH_CANDLES",
                    completed,
                    total,
                    interval.value,
                    cache_hits,
                    fetched,
                    failures,
                )
            )
            if self._quant is not None:

                def report_quant_progress(
                    item: QuantProgress,
                    *,
                    offset: int = completed,
                    current_interval: CandleInterval = interval,
                    prior_cache_hits: int = cache_hits,
                    prior_fetched: int = fetched,
                    prior_failures: int = failures,
                ) -> None:
                    self._progress(
                        ExtremeDeviationProgress(
                            "FETCH_CANDLES",
                            offset + item.completed,
                            total,
                            (f"{item.current_symbol} · {current_interval.value}"),
                            prior_cache_hits + item.cache_hits,
                            (prior_fetched + item.succeeded - item.cache_hits),
                            prior_failures + item.failed,
                            item.feedback,
                        )
                    )

                derived = self._quant.get_quant_series(
                    symbols,
                    request_for(interval, request.requested_end_date),
                    operation_control=control,
                    progress=report_quant_progress,
                )
                provider_id = derived.provider_id
                provider_name = derived.provider_display_name
                cache_hits += derived.cache_hits
                fetched += derived.fetched
                failures += len(derived.errors)
                for symbol in symbols:
                    quant_series = derived.series_by_symbol.get(symbol)
                    if quant_series is None:
                        outcomes[symbol].append(
                            PeriodOutcome(
                                interval,
                                0,
                                None,
                                derived.errors.get(
                                    symbol,
                                    "quant_result_unavailable",
                                ),
                            )
                        )
                    else:
                        record_source(
                            source_by_symbol,
                            symbol,
                            derived.source_by_symbol.get(
                                symbol,
                                derived.provider_id,
                            ),
                        )
                        if quant_series.timestamps:
                            actual_dates.append(quant_series.timestamps[-1])
                        points = _indicator_points(quant_series)
                        source_count = (
                            quant_series.source_count
                            if quant_series.source_count is not None
                            else len(quant_series.timestamps)
                        )
                        outcomes[symbol].append(
                            PeriodOutcome(
                                interval,
                                source_count,
                                score_latest(
                                    interval,
                                    source_count,
                                    points,
                                ),
                                (None if points else "insufficient_quant_history"),
                                _chart_points_from_quant(quant_series, points, source_count),
                            )
                        )
                fallback_symbols, fallback_codes = eligible_fallback_errors(
                    symbols,
                    derived.errors,
                )
                if (
                    fallback_symbols
                    and self._fallback_market is not None
                    and self._fallback_session is not None
                    and self._fallback_session.allow(
                        FallbackOffer(
                            "extreme_deviation",
                            fallback_symbols,
                            (interval.value,),
                            fallback_codes,
                            len(derived.series_by_symbol),
                            len(symbols),
                        )
                    )
                ):
                    self._progress(
                        ExtremeDeviationProgress(
                            "FETCH_FALLBACK",
                            completed,
                            total,
                            interval.value,
                            cache_hits,
                            fetched,
                            failures,
                        )
                    )
                    fallback = self._fallback_market.get_candle_series(
                        fallback_symbols,
                        interval,
                        650,
                        end_at,
                        operation_control=control,
                    )
                    recovered = 0
                    for symbol in fallback_symbols:
                        candle_series = fallback.series_by_symbol.get(symbol)
                        if candle_series is None:
                            continue
                        record_source(
                            source_by_symbol,
                            symbol,
                            fallback.source_by_symbol.get(
                                symbol,
                                fallback.provider_id,
                            ),
                        )
                        actual_dates.append(candle_series.candles[-1].timestamp)
                        points = ExtremeDeviationIndicator().calculate(candle_series.candles)
                        outcomes[symbol][-1] = PeriodOutcome(
                            interval,
                            len(candle_series.candles),
                            score_latest(
                                interval,
                                len(candle_series.candles),
                                points,
                            ),
                            chart_points=_chart_points_from_candles(
                                candle_series,
                                points,
                            ),
                        )
                        recovered += 1
                    if recovered:
                        failures -= recovered
                        fetched += recovered
                        if not derived.series_by_symbol:
                            provider_id = fallback.provider_id
                            provider_name = fallback.provider_display_name
            else:
                cached = self._market.get(
                    symbols,
                    interval,
                    650,
                    end_at,
                    operation_control=control,
                )
                provider_id = cached.dataset.provider_id
                provider_name = cached.dataset.provider_display_name
                cache_hits += cached.stats.cache_hits
                fetched += cached.stats.fetched
                failures += cached.stats.failures
                for symbol in symbols:
                    candle_series = cached.dataset.series_by_symbol.get(symbol)
                    if candle_series is None:
                        outcomes[symbol].append(
                            PeriodOutcome(
                                interval,
                                0,
                                None,
                                cached.dataset.errors.get(
                                    symbol,
                                    "candles_unavailable",
                                ),
                            )
                        )
                    else:
                        record_source(
                            source_by_symbol,
                            symbol,
                            cached.dataset.source_by_symbol.get(
                                symbol,
                                cached.dataset.provider_id,
                            ),
                        )
                        actual_dates.append(candle_series.candles[-1].timestamp)
                        points = ExtremeDeviationIndicator().calculate(candle_series.candles)
                        outcomes[symbol].append(
                            PeriodOutcome(
                                interval,
                                len(candle_series.candles),
                                score_latest(
                                    interval,
                                    len(candle_series.candles),
                                    points,
                                ),
                                chart_points=_chart_points_from_candles(
                                    candle_series,
                                    points,
                                ),
                            )
                        )
            for symbol in symbols:
                completed += 1
                self._progress(
                    ExtremeDeviationProgress(
                        "COMPUTE",
                        completed,
                        total,
                        f"{symbol} · {interval.value}",
                        cache_hits,
                        fetched,
                        failures,
                    )
                )
        if control.cancellation_requested():
            return ExtremeDeviationRunResult(ExtremeDeviationRunStatus.CANCELED)
        results: list[SymbolDeviationResult] = []
        for security in frozen:
            periods = tuple(outcomes[security.symbol])
            scores = tuple(
                item.score
                for item in periods
                if item.score is not None and item.score.score is not None
            )
            successful = len(scores)
            status = (
                "FAILED"
                if successful == 0
                else "READY"
                if successful == len(periods)
                else "PARTIAL"
            )
            results.append(
                SymbolDeviationResult(
                    security.symbol,
                    security.company_name,
                    security.classification_name,
                    periods,
                    build_consensus(scores),
                    status,
                )
            )
        periods = tuple(period for item in results for period in item.periods)
        succeeded_tasks = sum(
            period.score is not None and period.score.score is not None for period in periods
        )
        unexecuted_tasks = sum(
            not (period.score is not None and period.score.score is not None)
            and period.error_code == "circuit_open"
            for period in periods
        )
        failed_tasks = len(periods) - succeeded_tasks - unexecuted_tasks
        primary_failure_code = next(
            (
                period.error_code or "insufficient_data"
                for period in periods
                if period.score is None or period.score.score is None
            ),
            None,
        )
        reliability = reliability_summary(
            succeeded=succeeded_tasks,
            failed=failed_tasks,
            unexecuted=unexecuted_tasks,
            core_input_valid=any(item.successful_periods for item in results),
            canceled=control.cancellation_requested(),
        )
        evidence = freeze_reliability(
            reliability,
            circuit_opened=unexecuted_tasks > 0,
            primary_failure_code=primary_failure_code,
        )
        if control.cancellation_requested():
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.CANCELED,
                reliability=evidence,
            )
        # A single-security review is useful as soon as one period is valid.
        # The shared 80% threshold protects large batch analyses from being
        # dominated by missing rows, but applying it to four periods discards
        # the only trustworthy result for recently listed securities.
        usable_single_security = bool(request.security_id) and succeeded_tasks > 0
        if not reliability.should_save and not usable_single_security:
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.FAILED,
                error_code="insufficient_reliable_results",
                reliability=evidence,
            )
        completed_at = self._clock()
        provider_id, provider_name = provider_summary(
            source_by_symbol,
            provider_id,
            provider_name,
        )
        run = ExtremeDeviationRun(
            self._new_id(),
            context.operation_id,
            started_at,
            completed_at,
            request,
            watchlist_name,
            watchlist_revision,
            frozen,
            provider_id,
            provider_name,
            cache_hits,
            fetched,
            tuple(results),
            reliability=evidence,
            source_by_symbol=source_by_symbol,
            requested_date_window=(
                request.requested_end_date,
                request.requested_end_date,
            ),
            actual_date_window=(
                (
                    min(actual_dates).date(),
                    max(actual_dates).date(),
                )
                if actual_dates
                else None
            ),
        )
        self._progress(
            ExtremeDeviationProgress(
                "SAVE",
                total,
                total,
                cache_hits=cache_hits,
                fetched=fetched,
                failures=failures,
            )
        )
        if not control.try_enter_committing():
            canceled_reliability = reliability_summary(
                succeeded=succeeded_tasks,
                failed=failed_tasks,
                unexecuted=unexecuted_tasks,
                core_input_valid=any(item.successful_periods for item in results),
                canceled=True,
            )
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.CANCELED,
                reliability=freeze_reliability(
                    canceled_reliability,
                    circuit_opened=unexecuted_tasks > 0,
                    primary_failure_code=primary_failure_code,
                ),
            )
        try:
            self._history.save_extreme_deviation(run)
        except MemoryError:
            raise
        except Exception:  # noqa: BLE001 - persistence boundary is sanitized
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.FAILED,
                error_code="history_save_failed",
                reliability=evidence,
            )
        status = (
            ExtremeDeviationRunStatus.READY
            if reliability.terminal is RunTerminal.READY
            else ExtremeDeviationRunStatus.PARTIAL
        )
        return ExtremeDeviationRunResult(status, run, reliability=evidence)


def _indicator_points(
    series: QuantSeries,
) -> tuple[IndicatorPoint, ...]:
    required = (
        "close",
        "buy_anchor",
        "sell_anchor",
        "buy_raw",
        "sell_raw",
        "range_position",
        "buy_deviation",
        "sell_deviation",
    )
    points: list[IndicatorPoint] = []
    for index, timestamp in enumerate(series.timestamps):
        values = tuple(series.values[name][index] for name in required)
        if any(value is None for value in values):
            continue
        present = tuple(float(value) for value in values if value is not None)
        buy_age = series.values["buy_trigger_age"][index]
        sell_age = series.values["sell_trigger_age"][index]
        point = IndicatorPoint(
            timestamp,
            present[0],
            present[1],
            present[2],
            max(0.0, present[3]),
            max(0.0, present[4]),
            min(1.0, max(0.0, present[5])),
            max(0.0, present[6]),
            max(0.0, present[7]),
            None if buy_age is None else max(0, round(buy_age)),
            None if sell_age is None else max(0, round(sell_age)),
        )
        if point.is_finite():
            points.append(point)
    return tuple(points)


def _chart_points_from_quant(
    series: QuantSeries,
    points: tuple[IndicatorPoint, ...],
    source_count: int,
) -> tuple[DeviationChartPoint, ...]:
    scores = score_series(series.interval, source_count, points)
    index_by_timestamp = {value: index for index, value in enumerate(series.timestamps)}
    chart: list[DeviationChartPoint] = []
    for point, score in zip(points[-len(scores) :], scores):
        index = index_by_timestamp.get(point.timestamp)
        if index is None:
            continue
        values = series.values
        open_value = values["open"][index]
        high_value = values["high"][index]
        low_value = values["low"][index]
        close_value = values["close"][index]
        if (
            open_value is None
            or high_value is None
            or low_value is None
            or close_value is None
        ):
            continue
        chart.append(
            DeviationChartPoint(
                point.timestamp,
                float(open_value),
                float(high_value),
                float(low_value),
                float(close_value),
                score.score,
                score.label,
                point.buy_raw,
                point.sell_raw,
            )
        )
    return tuple(chart)


def _chart_points_from_candles(
    series: CandleSeries,
    points: tuple[IndicatorPoint, ...],
) -> tuple[DeviationChartPoint, ...]:
    scores = score_series(series.interval, len(series.candles), points)
    candles_by_timestamp = {candle.timestamp: candle for candle in series.candles}
    chart: list[DeviationChartPoint] = []
    for point, score in zip(points[-len(scores) :], scores):
        candle = candles_by_timestamp.get(point.timestamp)
        if candle is None:
            continue
        chart.append(
            DeviationChartPoint(
                point.timestamp,
                float(candle.open),
                float(candle.high),
                float(candle.low),
                float(candle.close),
                score.score,
                score.label,
                point.buy_raw,
                point.sell_raw,
            )
        )
    return tuple(chart)
