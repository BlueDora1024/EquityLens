"""Synchronous orchestration of one complete RS run."""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import date, timedelta

from stock_toolbox.analyses.rs_strength.application.models import (
    Clock,
    CompletedRun,
    CompletedRunStorePort,
    CustomRange,
    IdGenerator,
    ProgressSink,
    RunBarsPort,
    RunProgress,
    RunRequest,
    RunResult,
    RunStatus,
    RunWatchlistPort,
)
from stock_toolbox.analyses.rs_strength.application.staged_calculation import (
    calculate_run_staged,
)
from stock_toolbox.analyses.rs_strength.domain.models import (
    ALGORITHM_VERSION,
    CalculationFatalIssue,
    CalculationMember,
    MemberDataIssue,
    RequestedRange,
    RunCalculationInput,
)
from stock_toolbox.analyses.rs_strength.domain.validation import (
    align_benchmark_to_member_coverage,
)
from stock_toolbox.core.market_data.fallback import merge_daily_datasets
from stock_toolbox.core.market_data.models import DailySeriesProgress
from stock_toolbox.core.market_data.probe import probe_window, resolve_boundaries
from stock_toolbox.core.operations.failure_policy import (
    FailureCode,
    RunTerminal,
    freeze_reliability,
    reliability_summary,
)
from stock_toolbox.core.operations.registry import OperationExecutionContext
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback

_PRESETS = {
    "1W": ("近 1 周", "PRESET_1W", "days", 7),
    "2W": ("近 2 周", "PRESET_2W", "days", 14),
    "1M": ("近 1 个月", "PRESET_1M", "months", 1),
    "3M": ("近 3 个月", "PRESET_3M", "months", 3),
    "6M": ("近 6 个月", "PRESET_6M", "months", 6),
    "1Y": ("近 1 年", "PRESET_1Y", "months", 12),
}


class StartRun:
    def __init__(
        self,
        watchlists: RunWatchlistPort,
        provider: RunBarsPort,
        history: CompletedRunStorePort,
        *,
        clock: Clock,
        new_id: IdGenerator,
        progress: ProgressSink,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._watchlists = watchlists
        self._provider = provider
        self._history = history
        self._clock = clock
        self._new_id = new_id
        self._progress = progress
        self._today = today or (lambda: self._clock().date())

    def execute(
        self,
        request: RunRequest,
        context: OperationExecutionContext,
    ) -> RunResult:
        started_at = self._clock()
        self._report("PREFLIGHT", 0, 1, current=request.watchlist_id)
        try:
            watchlist = self._watchlists.get_watchlist(request.watchlist_id)
            ranges = self._ranges(request)
        except (KeyError, ValueError):
            return RunResult(RunStatus.FAILED, error_code="PREFLIGHT_FAILED")
        if (
            request.benchmark_symbol not in {"SPY.US", "QQQ.US"}
            or not 1 <= len(watchlist.memberships) <= 600
            or not ranges
        ):
            return RunResult(RunStatus.FAILED, error_code="PREFLIGHT_FAILED")
        today = self._today()
        if any(
            item.requested_start_date >= today
            or item.requested_end_date >= today
            for item in ranges
        ):
            return RunResult(
                RunStatus.FAILED,
                error_code="HISTORICAL_DATE_REQUIRED",
            )
        if context.operation_control.cancellation_requested():
            return RunResult(RunStatus.CANCELED)
        self._report("PREFLIGHT", 1, 1, current=watchlist.display_name)

        members = tuple(
            CalculationMember(
                self._new_id(),
                ordinal,
                member.canonical_symbol,
                member.participating_classification_id,
                member.participating_classification_name,
                member.participating_classification_name.casefold(),
            )
            for ordinal, member in enumerate(watchlist.memberships)
        )
        member_symbols = tuple(member.symbol for member in members)
        symbols = (request.benchmark_symbol, *member_symbols)
        self._report("FETCHING", 0, len(symbols), current=symbols[0])
        start_date, end_date = requested_envelope(request)
        probe = probe_window(
            start_date,
            end_date,
            cap=today - timedelta(days=1),
        )
        benchmark_failure_code: FailureCode | None = None
        benchmark_circuit_opened = False

        def report_benchmark_progress(event: DailySeriesProgress) -> None:
            nonlocal benchmark_circuit_opened, benchmark_failure_code
            feedback = event.feedback
            if feedback is not None:
                benchmark_failure_code = (
                    feedback.failure_code or benchmark_failure_code
                )
                benchmark_circuit_opened = (
                    benchmark_circuit_opened
                    or feedback.kind is FeedbackKind.CIRCUIT_OPEN
                )
            self._report(
                "FETCHING",
                event.completed,
                len(symbols),
                current=event.current_symbol,
                succeeded=event.succeeded,
                failed=event.failed,
                feedback=feedback,
            )

        benchmark_bars = self._provider.get_daily_series(
            (request.benchmark_symbol,),
            probe.fetch_start,
            probe.fetch_end,
            operation_control=context.operation_control,
            progress=report_benchmark_progress,
        )
        if context.operation_control.cancellation_requested():
            return RunResult(RunStatus.CANCELED)
        if (
            request.benchmark_symbol in benchmark_bars.errors
            or request.benchmark_symbol not in benchmark_bars.series_by_symbol
        ):
            raw_code = benchmark_bars.errors.get(request.benchmark_symbol)
            if benchmark_failure_code is None and raw_code is not None:
                try:
                    benchmark_failure_code = FailureCode(raw_code)
                except ValueError:
                    pass
            evidence = freeze_reliability(
                reliability_summary(
                    0,
                    1,
                    0,
                    core_input_valid=False,
                ),
                circuit_opened=benchmark_circuit_opened,
                primary_failure_code=(
                    benchmark_failure_code.value
                    if benchmark_failure_code is not None
                    else None
                ),
            )
            return RunResult(
                RunStatus.FAILED,
                error_code="BENCHMARK_FETCH_FAILED",
                reliability=evidence,
            )
        self._report(
            "FETCHING",
            1,
            len(symbols),
            current=request.benchmark_symbol,
            succeeded=1,
            failed=0,
        )

        def report_member_progress(event: DailySeriesProgress) -> None:
            self._report(
                "FETCHING",
                event.completed + 1,
                len(symbols),
                current=event.current_symbol,
                succeeded=event.succeeded + 1,
                failed=event.failed,
                feedback=event.feedback,
            )

        member_bars = self._provider.get_daily_series(
            member_symbols,
            probe.fetch_start,
            probe.fetch_end,
            operation_control=context.operation_control,
            progress=report_member_progress,
        )
        bars = merge_daily_datasets(
            benchmark_bars,
            member_bars,
            requested=symbols,
        )
        if context.operation_control.cancellation_requested():
            return RunResult(RunStatus.CANCELED)
        self._report(
            "FETCHING",
            len(symbols),
            len(symbols),
            current=symbols[-1],
            succeeded=len(bars.series_by_symbol),
            failed=len(bars.errors),
        )

        issues = tuple(
            MemberDataIssue(
                member.ordinal,
                member.symbol,
                "FETCH",
                bars.errors[member.symbol],
                (),
            )
            for member in members
            if member.symbol in bars.errors
        )
        calculation_input = align_benchmark_to_member_coverage(
            RunCalculationInput(
                ALGORITHM_VERSION,
                request.benchmark_symbol,
                ranges,
                members,
                bars.series_by_symbol,
                issues,
            )
        )
        output = calculate_run_staged(
            calculation_input,
            context.operation_control,
            self._progress,
        )
        if output is None:
            return RunResult(RunStatus.CANCELED)
        if isinstance(output, CalculationFatalIssue):
            return RunResult(RunStatus.FAILED, error_code=output.code)
        valid_ordinals = {
            item.member_ordinal for item in output.stock_results
        }
        unexecuted_tasks = sum(
            member.ordinal not in valid_ordinals
            and bars.errors.get(member.symbol) == "circuit_open"
            for member in members
        )
        primary_failure_code = (
            output.failure_candidates[0].code
            if output.failure_candidates
            else None
        )
        reliability = reliability_summary(
            succeeded=output.valid_member_count,
            failed=output.failed_member_count - unexecuted_tasks,
            unexecuted=unexecuted_tasks,
            core_input_valid=bool(output.stock_results),
            canceled=context.operation_control.cancellation_requested(),
        )
        evidence = freeze_reliability(
            reliability,
            circuit_opened=unexecuted_tasks > 0,
            primary_failure_code=primary_failure_code,
        )
        if context.operation_control.cancellation_requested():
            return RunResult(
                RunStatus.CANCELED,
                output=output,
                reliability=evidence,
            )
        if not reliability.should_save:
            return RunResult(
                RunStatus.FAILED,
                output=output,
                error_code="insufficient_reliable_results",
                reliability=evidence,
            )

        run_id = self._new_id()
        benchmark_series = bars.series_by_symbol[request.benchmark_symbol]
        resolved = resolve_boundaries(
            start_date,
            end_date,
            available=tuple(point.date for point in benchmark_series.points),
        )
        actual_window = (
            (resolved.actual_start, resolved.actual_end)
            if (
                resolved.actual_start is not None
                and resolved.actual_end is not None
            )
            else None
        )
        completed = CompletedRun(
            run_id,
            context.operation_id,
            started_at,
            self._clock(),
            request,
            watchlist,
            bars.provider_id,
            bars.provider_display_name,
            tuple(member.run_member_id for member in members),
            output,
            evidence,
            bars.source_by_symbol,
            (start_date, end_date),
            actual_window,
        )
        self._report("SAVING", 0, 1, current=run_id)
        if not self._history.save(
            completed,
            operation_control=context.operation_control,
        ):
            canceled = context.operation_control.cancellation_requested()
            status = RunStatus.CANCELED if canceled else RunStatus.FAILED
            if canceled:
                canceled_reliability = reliability_summary(
                    succeeded=output.valid_member_count,
                    failed=output.failed_member_count - unexecuted_tasks,
                    unexecuted=unexecuted_tasks,
                    core_input_valid=bool(output.stock_results),
                    canceled=True,
                )
                evidence = freeze_reliability(
                    canceled_reliability,
                    circuit_opened=unexecuted_tasks > 0,
                    primary_failure_code=primary_failure_code,
                )
            return RunResult(
                status,
                error_code="HISTORY_SAVE_FAILED",
                reliability=evidence,
            )
        self._report("SAVING", 1, 1, current=run_id, succeeded=1, failed=0)
        status = (
            RunStatus.READY
            if reliability.terminal is RunTerminal.READY
            else RunStatus.PARTIAL
        )
        return RunResult(status, run_id, output, reliability=evidence)

    def _ranges(self, request: RunRequest) -> tuple[RequestedRange, ...]:
        ranges: list[RequestedRange] = []
        seen = set()
        for key in request.preset_ranges:
            if key in seen:
                continue
            seen.add(key)
            label, kind, unit, amount = _PRESETS[key]
            start_date = (
                request.requested_end_date - timedelta(days=amount)
                if unit == "days"
                else _shift_months(request.requested_end_date, -amount)
            )
            ranges.append(
                RequestedRange(
                    self._new_id(),
                    key,
                    label,
                    kind,
                    len(ranges),
                    start_date,
                    request.requested_end_date,
                )
            )
        if request.custom_range is not None:
            custom = request.custom_range
            if custom.start_date > custom.end_date:
                raise ValueError("Custom range is invalid")
            ranges.append(self._custom_range(custom, len(ranges)))
        return tuple(ranges)

    def _custom_range(
        self,
        custom: CustomRange,
        ordinal: int,
    ) -> RequestedRange:
        return RequestedRange(
            self._new_id(),
            "CUSTOM",
            "自定义",
            "CUSTOM",
            ordinal,
            custom.start_date,
            custom.end_date,
        )

    def _report(
        self,
        stage: str,
        completed: int,
        total: int,
        *,
        current: str | None = None,
        succeeded: int | None = None,
        failed: int | None = None,
        feedback: RunFeedback | None = None,
    ) -> None:
        self._progress(
            RunProgress(
                stage,
                completed,
                total,
                current,
                succeeded,
                failed,
                feedback,
            )
        )


def _shift_months(value: date, months: int) -> date:
    zero_based = value.month - 1 + months
    year = value.year + zero_based // 12
    month = zero_based % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def requested_envelope(request: RunRequest) -> tuple[date, date]:
    """Return the one daily range shared by every selected RS window."""

    starts = []
    ends = []
    for key in dict.fromkeys(request.preset_ranges):
        _label, _kind, unit, amount = _PRESETS[key]
        starts.append(
            request.requested_end_date - timedelta(days=amount)
            if unit == "days"
            else _shift_months(request.requested_end_date, -amount)
        )
        ends.append(request.requested_end_date)
    if request.custom_range is not None:
        if request.custom_range.start_date > request.custom_range.end_date:
            raise ValueError("Custom range is invalid")
        starts.append(request.custom_range.start_date)
        ends.append(request.custom_range.end_date)
    if not starts:
        raise ValueError("At least one RS range is required")
    return min(starts), max(ends)
