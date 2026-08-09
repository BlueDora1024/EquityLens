"""Coordinate one complete turning-point screening run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Protocol

from stock_toolbox.analyses.turning_point.application.models import (
    PeriodScreenResult,
    SymbolTurningResult,
    TurningPointProgress,
    TurningPointRequest,
    TurningPointRun,
    TurningPointRunResult,
    TurningPointRunStatus,
)
from stock_toolbox.analyses.turning_point.application.quant import request_for
from stock_toolbox.analyses.turning_point.application.risk import (
    build_risk_annotation,
)
from stock_toolbox.analyses.turning_point.domain.engine import (
    TurningPointEngine,
    recent_window_bars,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    ScreeningDecision,
    SymbolScreenResult,
    TurningPointTradeSide,
)
from stock_toolbox.core.market_data.fallback import (
    FallbackOffer,
    FallbackSession,
    eligible_fallback_errors,
    provider_summary,
    record_source,
)
from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    SnapshotDataset,
)
from stock_toolbox.core.market_data.quant import (
    QuantMarketDataPort,
    QuantProgress,
    QuantSeries,
)
from stock_toolbox.core.master_data.models import WatchlistDTO
from stock_toolbox.core.operations.failure_policy import (
    RunTerminal,
    freeze_reliability,
    reliability_summary,
)
from stock_toolbox.core.operations.registry import OperationControl, OperationExecutionContext


class TurningPointMasterDataPort(Protocol):
    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO: ...


class TurningPointHistoryPort(Protocol):
    def save_turning_point(self, run: TurningPointRun) -> None: ...


class TurningCandleDataPort(Protocol):
    def get_candle_series(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CandleDataset: ...

    def get_security_snapshots(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> SnapshotDataset: ...


_NATIVE_INTRADAY_INTERVALS = frozenset({CandleInterval.MIN_120, CandleInterval.MIN_240})


class StartTurningPointRun:
    def __init__(
        self,
        master_data: TurningPointMasterDataPort,
        market_data: TurningCandleDataPort,
        history_store: TurningPointHistoryPort,
        *,
        quant_market_data: QuantMarketDataPort | None = None,
        fallback_market_data: TurningCandleDataPort | None = None,
        fallback_session: FallbackSession | None = None,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
        progress: Callable[[TurningPointProgress], None] = lambda _item: None,
        today: Callable[[], date] = date.today,
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
        self._today = today

    def execute(
        self,
        request: TurningPointRequest,
        context: OperationExecutionContext,
    ) -> TurningPointRunResult:
        control = context.operation_control
        if request.requested_end_date >= self._today():
            return TurningPointRunResult(
                TurningPointRunStatus.FAILED,
                error_code="historical_date_required",
            )
        self._progress(TurningPointProgress("FREEZE_WATCHLIST", 0, 1))
        try:
            watchlist = self._master.get_watchlist(request.watchlist_id)
        except (KeyError, ValueError):
            reliability = reliability_summary(
                0,
                0,
                0,
                core_input_valid=False,
                canceled=control.cancellation_requested(),
            )
            return TurningPointRunResult(
                TurningPointRunStatus.FAILED,
                error_code="watchlist_freeze_failed",
                reliability=freeze_reliability(
                    reliability,
                    circuit_opened=False,
                    primary_failure_code="watchlist_freeze_failed",
                ),
            )
        symbols = tuple(item.canonical_symbol for item in watchlist.memberships)
        if not symbols:
            return TurningPointRunResult(
                TurningPointRunStatus.FAILED,
                error_code="watchlist_empty",
            )
        if len(symbols) > 600:
            return TurningPointRunResult(
                TurningPointRunStatus.FAILED,
                error_code="watchlist_too_large",
            )
        by_symbol = {item.canonical_symbol: item for item in watchlist.memberships}
        started_at = self._clock()
        provider_id = provider_name = ""
        source_by_symbol: dict[str, str] = {}
        actual_dates: list[date] = []
        eligible = list(symbols)
        if control.cancellation_requested():
            return TurningPointRunResult(TurningPointRunStatus.CANCELED)

        engine = TurningPointEngine()
        outcomes: dict[str, list[PeriodScreenResult]] = {symbol: [] for symbol in symbols}
        total = len(eligible) * len(request.intervals)
        completed = 0
        end_at = datetime.combine(
            request.requested_end_date,
            time.max,
            UTC,
        )
        for interval in request.intervals:
            if control.cancellation_requested():
                return TurningPointRunResult(TurningPointRunStatus.CANCELED)
            use_quant = self._quant is not None and interval not in _NATIVE_INTRADAY_INTERVALS
            stage = "FETCH_INDICATORS" if use_quant else "FETCH_CANDLES"
            self._progress(TurningPointProgress(stage, completed, total, interval.value))
            interval_results: dict[str, SymbolScreenResult] = {}
            if use_quant:
                assert self._quant is not None
                offset = completed

                def report_quant_progress(
                    item: QuantProgress,
                    *,
                    current_interval: object = interval,
                    completed_offset: int = offset,
                ) -> None:
                    active_interval = str(getattr(current_interval, "value", current_interval))
                    item_completed = item.completed
                    current_symbol = item.current_symbol
                    self._progress(
                        TurningPointProgress(
                            "FETCH_INDICATORS",
                            min(total, completed_offset + item_completed),
                            total,
                            f"{current_symbol} · {active_interval}",
                            item.feedback,
                        )
                    )

                derived = self._quant.get_quant_series(
                    tuple(eligible),
                    request_for(interval, request.requested_end_date),
                    operation_control=control,
                    progress=report_quant_progress,
                )
                provider_id = derived.provider_id
                provider_name = derived.provider_display_name
                primary_succeeded = bool(derived.series_by_symbol)
                for symbol in eligible:
                    series = derived.series_by_symbol.get(symbol)
                    if isinstance(series, QuantSeries) and series.timestamps:
                        record_source(
                            source_by_symbol,
                            symbol,
                            derived.source_by_symbol.get(
                                symbol,
                                derived.provider_id,
                            ),
                        )
                        actual_dates.append(series.timestamps[-1].date())
                    interval_results[symbol] = (
                        _screen_quant(
                            engine,
                            symbol,
                            series,
                            request.trade_side,
                            interval,
                        )
                        if series is not None
                        else SymbolScreenResult(
                            symbol,
                            ScreeningDecision.FAILED,
                            derived.errors.get(
                                symbol,
                                "quant_result_unavailable",
                            ),
                        )
                    )
                fallback_symbols, fallback_codes = eligible_fallback_errors(
                    tuple(eligible),
                    derived.errors,
                )
                if (
                    fallback_symbols
                    and self._fallback_market is not None
                    and self._fallback_session is not None
                    and self._fallback_session.allow(
                        FallbackOffer(
                            "turning_point",
                            fallback_symbols,
                            (interval.value,),
                            fallback_codes,
                            len(derived.series_by_symbol),
                            len(eligible),
                        )
                    )
                ):
                    self._progress(
                        TurningPointProgress(
                            "FETCH_FALLBACK",
                            completed,
                            total,
                            interval.value,
                        )
                    )
                    fallback = self._fallback_market.get_candle_series(
                        fallback_symbols,
                        interval,
                        220,
                        end_at,
                        operation_control=control,
                    )
                    fallback_succeeded = False
                    for symbol in fallback_symbols:
                        candle_series = fallback.series_by_symbol.get(symbol)
                        if candle_series is None:
                            interval_results[symbol] = SymbolScreenResult(
                                symbol,
                                ScreeningDecision.FAILED,
                                fallback.errors.get(
                                    symbol,
                                    derived.errors.get(
                                        symbol,
                                        "fallback_unavailable",
                                    ),
                                ),
                            )
                            continue
                        fallback_succeeded = True
                        record_source(
                            source_by_symbol,
                            symbol,
                            fallback.source_by_symbol.get(
                                symbol,
                                fallback.provider_id,
                            ),
                        )
                        actual_dates.append(candle_series.candles[-1].timestamp.date())
                        interval_results[symbol] = engine.screen(
                            symbol,
                            candle_series.candles,
                            request.trade_side,
                            signal_lookback=recent_window_bars(interval),
                        )
                    if fallback_succeeded and not primary_succeeded:
                        provider_id = fallback.provider_id
                        provider_name = fallback.provider_display_name
            else:
                dataset = self._market.get_candle_series(
                    tuple(eligible),
                    interval,
                    220,
                    end_at,
                    operation_control=control,
                )
                provider_id = dataset.provider_id
                provider_name = dataset.provider_display_name
                for symbol in eligible:
                    candle_series = dataset.series_by_symbol.get(symbol)
                    if candle_series is not None:
                        record_source(
                            source_by_symbol,
                            symbol,
                            dataset.source_by_symbol.get(
                                symbol,
                                dataset.provider_id,
                            ),
                        )
                        actual_dates.append(candle_series.candles[-1].timestamp.date())
                    interval_results[symbol] = (
                        engine.screen(
                            symbol,
                            candle_series.candles,
                            request.trade_side,
                            signal_lookback=recent_window_bars(interval),
                        )
                        if candle_series is not None
                        else SymbolScreenResult(
                            symbol,
                            ScreeningDecision.FAILED,
                            dataset.errors.get(
                                symbol,
                                "candles_unavailable",
                            ),
                        )
                    )
            for symbol in eligible:
                outcomes[symbol].append(
                    PeriodScreenResult.from_screen(
                        interval,
                        interval_results[symbol],
                    )
                )
                completed += 1
                self._progress(
                    TurningPointProgress(
                        "COMPUTE",
                        completed,
                        total,
                        f"{symbol} · {interval.value}",
                    )
                )
        if control.cancellation_requested():
            return TurningPointRunResult(TurningPointRunStatus.CANCELED)

        ordered = tuple(
            SymbolTurningResult.build(
                symbol,
                by_symbol[symbol].company_name,
                by_symbol[symbol].participating_classification_name,
                tuple(outcomes[symbol]),
            )
            for symbol in symbols
        )
        ordered = self._annotate_risks(ordered, control)
        periods = tuple(period for item in ordered for period in item.period_results)
        succeeded_tasks = sum(
            period.decision != ScreeningDecision.FAILED.value for period in periods
        )
        unexecuted_tasks = sum(
            period.decision == ScreeningDecision.FAILED.value and period.reason == "circuit_open"
            for period in periods
        )
        failed_tasks = len(periods) - succeeded_tasks - unexecuted_tasks
        primary_failure_code = next(
            (
                period.reason
                for period in periods
                if period.decision == ScreeningDecision.FAILED.value
            ),
            None,
        )
        reliability = reliability_summary(
            succeeded=succeeded_tasks,
            failed=failed_tasks,
            unexecuted=unexecuted_tasks,
            core_input_valid=any(item.status != "FAILED" for item in ordered),
            canceled=control.cancellation_requested(),
        )
        evidence = freeze_reliability(
            reliability,
            circuit_opened=unexecuted_tasks > 0,
            primary_failure_code=primary_failure_code,
        )
        if control.cancellation_requested():
            return TurningPointRunResult(
                TurningPointRunStatus.CANCELED,
                reliability=evidence,
            )
        if not reliability.should_save:
            return TurningPointRunResult(
                TurningPointRunStatus.FAILED,
                error_code="insufficient_reliable_results",
                reliability=evidence,
            )
        completed_at = self._clock()
        provider_id, provider_name = provider_summary(
            source_by_symbol,
            provider_id,
            provider_name,
        )
        run = TurningPointRun(
            self._new_id(),
            context.operation_id,
            started_at,
            completed_at,
            request,
            watchlist.display_name,
            watchlist.revision,
            provider_id,
            provider_name,
            ordered,
            reliability=evidence,
            source_by_symbol=source_by_symbol,
            requested_date_window=(
                request.requested_end_date,
                request.requested_end_date,
            ),
            actual_date_window=((min(actual_dates), max(actual_dates)) if actual_dates else None),
        )
        self._progress(TurningPointProgress("SAVE", total, total))
        if not control.try_enter_committing():
            canceled_reliability = reliability_summary(
                succeeded=succeeded_tasks,
                failed=failed_tasks,
                unexecuted=unexecuted_tasks,
                core_input_valid=any(item.status != "FAILED" for item in ordered),
                canceled=True,
            )
            return TurningPointRunResult(
                TurningPointRunStatus.CANCELED,
                reliability=freeze_reliability(
                    canceled_reliability,
                    circuit_opened=unexecuted_tasks > 0,
                    primary_failure_code=primary_failure_code,
                ),
            )
        try:
            self._history.save_turning_point(run)
        except MemoryError:
            raise
        except Exception:  # noqa: BLE001 - persistence boundary is sanitized
            return TurningPointRunResult(
                TurningPointRunStatus.FAILED,
                error_code="history_save_failed",
                reliability=evidence,
            )
        status = (
            TurningPointRunStatus.READY
            if reliability.terminal is RunTerminal.READY
            else TurningPointRunStatus.PARTIAL
        )
        return TurningPointRunResult(status, run, reliability=evidence)

    def _annotate_risks(
        self,
        results: tuple[SymbolTurningResult, ...],
        control: OperationControl,
    ) -> tuple[SymbolTurningResult, ...]:
        matched = tuple(item.symbol for item in results if item.matched_periods)
        if not matched:
            return results
        self._progress(TurningPointProgress("ANNOTATE_RISK", 0, len(matched)))
        market_values: dict[str, int] = {}
        try:
            snapshots = self._market.get_security_snapshots(
                matched,
                operation_control=control,
            )
            for symbol, snapshot in snapshots.snapshots_by_symbol.items():
                if snapshot.total_market_value is not None:
                    market_values[symbol] = int(snapshot.total_market_value)
        except MemoryError:
            raise
        except Exception:  # noqa: BLE001 - optional annotation boundary
            market_values = {}
        output: list[SymbolTurningResult] = []
        completed = 0
        for item in results:
            if not item.matched_periods:
                output.append(item)
                continue
            market_value = market_values.get(item.symbol)
            flags = build_risk_annotation(market_value)
            output.append(
                replace(
                    item,
                    market_value_usd=market_value,
                    risk_flags=flags,
                )
            )
            completed += 1
            self._progress(
                TurningPointProgress(
                    "ANNOTATE_RISK",
                    completed,
                    len(matched),
                    item.symbol,
                )
            )
        return tuple(output)


def _screen_quant(
    engine: TurningPointEngine,
    symbol: str,
    series: object,
    trade_side: TurningPointTradeSide,
    interval: CandleInterval,
) -> SymbolScreenResult:
    if not isinstance(series, QuantSeries):
        return SymbolScreenResult(
            symbol,
            ScreeningDecision.FAILED,
            "malformed_quant_response",
        )
    names = (
        "high",
        "close",
        "high_ema26",
        "high_ema89",
        "dif",
        "hist",
        "volume",
    )
    selected = {name: tuple(series.values[name][-220:]) for name in names}
    if any(
        len(values) < 119 or any(value is None for value in values) for values in selected.values()
    ):
        return SymbolScreenResult(
            symbol,
            ScreeningDecision.FAILED,
            "insufficient_quant_history",
        )
    volume = tuple(float(value) for value in selected["volume"] if value is not None)
    average = sum(volume[-20:]) / 20.0 if len(volume) >= 20 else 0.0
    ratio = None if average <= 0 else volume[-1] / average
    return engine.screen_derived(
        symbol,
        series.timestamps[-len(selected["close"]) :],
        tuple(float(value) for value in selected["high"] if value is not None),
        tuple(float(value) for value in selected["close"] if value is not None),
        tuple(float(value) for value in selected["high_ema26"] if value is not None),
        tuple(float(value) for value in selected["high_ema89"] if value is not None),
        tuple(float(value) for value in selected["dif"] if value is not None),
        tuple(float(value) for value in selected["hist"] if value is not None),
        ratio,
        trade_side,
        signal_lookback=recent_window_bars(interval),
    )
