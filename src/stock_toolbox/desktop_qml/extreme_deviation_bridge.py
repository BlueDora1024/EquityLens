"""QML adapter for extreme-deviation runs, details, history, and reports."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    Property,
    QCoreApplication,
    QObject,
    QProcess,
    QRunnable,
    QThreadPool,
    QUrl,
    Signal,
    Slot,
)

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationProgress,
    ExtremeDeviationRequest,
    ExtremeDeviationRunResult,
    ExtremeDeviationRunStatus,
    SymbolDeviationResult,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import (
    SUPPORTED_INTERVALS,
)
from stock_toolbox.analyses.extreme_deviation.application.report import (
    TechnicalReport,
)
from stock_toolbox.analyses.extreme_deviation.domain.scoring import (
    pressure_contrast_series,
)
from stock_toolbox.analyses.resource_budget import AnalysisBudgetSnapshot
from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.core.market_data.date_policy import (
    display_today,
    maximum_historical_date,
    parse_iso_date,
    validate_historical_date,
)
from stock_toolbox.core.market_data.fallback import FallbackOffer
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.master_data.models import SecurityDetailDTO
from stock_toolbox.core.operations.executor import OperationAdmissionClosedError
from stock_toolbox.core.operations.failure_policy import AnalysisReliability, FailureCode
from stock_toolbox.core.operations.registry import CancelResult
from stock_toolbox.core.operations.reliability_wire import reliability_from_payload
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback
from stock_toolbox.core.operations.storage_guard import StorageState
from stock_toolbox.desktop_qml.analysis_budget_task import AnalysisBudgetTask
from stock_toolbox.desktop_qml.failure_presentation import (
    FailureState,
    advance_feedback,
    advance_running,
    finish_outcome,
    group_failures,
    present_ai_report_failure,
)
from stock_toolbox.desktop_qml.fallback_consent import FallbackConsentGate
from stock_toolbox.desktop_qml.progress_diagnostics import (
    ProgressEventSampler,
    emit_progress,
)
from stock_toolbox.desktop_qml.report_operation import (
    execute_report_operation,
    reserve_report_operation,
)
from stock_toolbox.desktop_qml.time_display import display_datetime
from stock_toolbox.desktop_qml.ui_change_coalescer import UiChangeCoalescer
from stock_toolbox.runtime.environment import RuntimeEnvironment

_INTERVAL_LABELS = {
    CandleInterval.MIN_30: "30 分钟",
    CandleInterval.MIN_60: "1 小时",
    CandleInterval.DAY: "日线",
    CandleInterval.WEEK: "周线",
}
_CONSENSUS_LABELS = {
    "BUY_RESONANCE": "买入共振",
    "SELL_RESONANCE": "卖出共振",
    "SINGLE_PERIOD_EXTREME": "单周期极值",
    "PERIOD_DIVERGENCE": "周期分歧",
    "NEUTRAL": "中性",
}
_CONFIDENCE_LABELS = {
    "FULL": "完整",
    "LOW": "低",
    "INSUFFICIENT": "不足",
}
_STAGES = (
    "FREEZE_WATCHLIST",
    "CHECK_CACHE",
    "FETCH_CANDLES",
    "VALIDATE",
    "COMPUTE",
    "SAVE",
)
_STAGE_LABELS = {
    "FREEZE_WATCHLIST": "冻结证券",
    "CHECK_CACHE": "检查缓存",
    "FETCH_CANDLES": "读取原始 K 线",
    "VALIDATE": "校验样本",
    "COMPUTE": "本地公式计算",
    "SAVE": "保存结果",
}


def _security_option_name(symbol: str, company_name: str) -> str:
    code = symbol.removesuffix(".US")
    name = company_name.strip()
    if not name or name.casefold() == code.casefold():
        return code
    return f"{code} · {name}"


class _TaskSignals(QObject):
    progress = Signal(object)
    finished = Signal(str, object)


class _Task(QRunnable):
    def __init__(
        self,
        application: StockToolboxApplication,
        *,
        request: ExtremeDeviationRequest | None = None,
        run_id: str = "",
        symbols: tuple[str, ...] = (),
        support: bool = False,
        calendar_boundary: date | None = None,
        fallback_gate: FallbackConsentGate | None = None,
        force_yahoo: bool = False,
    ) -> None:
        super().__init__()
        self.application = application
        self.request = request
        self.run_id = run_id
        self.symbols = symbols
        self.support = support
        self.calendar_boundary = calendar_boundary
        self.fallback_gate = fallback_gate
        self.force_yahoo = force_yahoo
        self.operation_id = str(uuid.uuid4()) if request is not None or bool(run_id) else ""
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        if self.support:
            try:
                result: object = self.application.master_data.list_securities()
            except Exception as error:  # noqa: BLE001 - UI boundary
                result = error
            self.signals.finished.emit("support", result)
            return
        if self.request is not None:
            try:
                result = self.application.run_extreme_deviation(
                    self.request,
                    operation_id=self.operation_id,
                    progress=self.signals.progress.emit,
                    force_yahoo=self.force_yahoo,
                    fallback_consent=(
                        self.fallback_gate.request if self.fallback_gate is not None else None
                    ),
                )
            except OperationAdmissionClosedError as error:
                self.signals.finished.emit("run", error)
                return
            self.signals.finished.emit("run", result)
            return
        if self.run_id:
            report = execute_report_operation(
                self.application,
                self.operation_id,
                lambda control: self.application.generate_extreme_deviation_report(
                    self.run_id,
                    self.symbols,
                    operation_control=control,
                ),
            )
            self.signals.finished.emit("report", (self.run_id, report))
            return
        try:
            result = self.application.latest_completed_trading_day(
                on_or_before=self.calendar_boundary,
            )
        except Exception as error:  # noqa: BLE001 - UI boundary
            result = error
        self.signals.finished.emit(
            "calendar",
            (self.calendar_boundary, result),
        )


class ExtremeDeviationBridge(QObject):
    changed = Signal()
    finished = Signal(object)
    report_finished = Signal(object)
    support_finished = Signal()
    calendar_finished = Signal()

    def __init__(
        self,
        application: StockToolboxApplication,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._display_timezone = application.settings().display_timezone
        self._security_id = ""
        self._selected_intervals = set(SUPPORTED_INTERVALS)
        self._security_cache: dict[str, SecurityDetailDTO] = {}
        self._securities_loaded = False
        self._support_task: _Task | None = None
        self._requested_end_date: date | None = maximum_historical_date(self._display_timezone)
        self._end_date: date | None = self._requested_end_date
        self._date_resolution_text = "等待确认交易日"
        self._budget_task: AnalysisBudgetTask | None = None
        self._budget_request: ExtremeDeviationRequest | None = None
        self._budget_snapshot: AnalysisBudgetSnapshot | None = None
        self._task: _Task | None = None
        self._run_process: QProcess | None = None
        self._run_process_buffer = b""
        self._run_process_result: dict[str, object] | None = None
        self._run_cancel_requested = False
        self._calendar_task: _Task | None = None
        self._report_task: _Task | None = None
        self._running = False
        self._progress_updates = UiChangeCoalescer(self)
        self._progress_updates.changed.connect(self.changed.emit)
        self._progress_diagnostics = ProgressEventSampler()
        self._progress = 0.0
        self._active_stage = -1
        self._status_text = "就绪 · 选择一只证券和至少一个周期"
        self._last_status = ""
        self._cache_hits = 0
        self._fetched = 0
        self._failures = 0
        self._failure_state = FailureState()
        self._terminal_has_usable_results = False
        self._results: list[dict[str, object]] = []
        self._selected_symbol = ""
        self._latest_run_id = ""
        self._report_symbols: set[str] = set()
        self._report_text = ""
        self._report_error = ""
        self._fallback_gate = FallbackConsentGate(self)
        self._fallback_gate.changed.connect(self._on_fallback_changed)
        self._fallback_gate.settings_requested.connect(self.cancel)

    @Property(list, notify=changed)
    def securities(self) -> list[dict[str, object]]:
        return [
            {
                "id": item.id,
                "name": _security_option_name(
                    item.canonical_symbol,
                    item.display_name,
                ),
                "symbol": item.canonical_symbol,
            }
            for item in sorted(
                self._security_cache.values(),
                key=lambda row: (row.canonical_symbol, row.display_name.casefold()),
            )
        ]

    @Property(QObject, notify=changed)
    def fallback_gate(self) -> QObject:
        return self._fallback_gate

    @Property(bool, notify=changed)
    def securities_loading(self) -> bool:
        return self._support_task is not None

    @Property(bool, notify=changed)
    def securities_loaded(self) -> bool:
        return self._securities_loaded

    @Property(str, notify=changed)
    def selected_security_id(self) -> str:
        return self._security_id

    @Property(int, notify=changed)
    def member_count(self) -> int:
        return 1 if self._security_id else 0

    def _member_count(self) -> int:
        return 1 if self._security_id else 0

    @Property(str, notify=changed)
    def end_date(self) -> str:
        return self._end_date.isoformat() if self._end_date is not None else ""

    @Property(str, notify=changed)
    def maximum_historical_date(self) -> str:
        return maximum_historical_date(self._display_timezone).isoformat()

    @Property(bool, notify=changed)
    def calendar_loading(self) -> bool:
        return self._calendar_task is not None

    @Property(str, notify=changed)
    def date_resolution_text(self) -> str:
        return self._date_resolution_text

    @Property(int, notify=changed)
    def selected_interval_count(self) -> int:
        return len(self._selected_intervals)

    @Property(list, notify=changed)
    def interval_options(self) -> list[dict[str, object]]:
        return [
            {
                "value": interval.value,
                "label": _INTERVAL_LABELS[interval],
                "selected": interval in self._selected_intervals,
            }
            for interval in SUPPORTED_INTERVALS
        ]

    @Property(int, notify=changed)
    def combination_count(self) -> int:
        return self._member_count() * len(self._selected_intervals)

    @Property(bool, notify=changed)
    def can_start(self) -> bool:
        return (
            bool(self._security_id)
            and bool(self._selected_intervals)
            and self._securities_loaded
            and self._end_date is not None
            and self._calendar_task is None
            and self._support_task is None
            and not self._running
            and self._budget_task is None
        )

    @Property(bool, notify=changed)
    def running(self) -> bool:
        return self._running or self._budget_task is not None

    @Property(bool, notify=changed)
    def budget_loading(self) -> bool:
        return self._budget_task is not None

    @Property(int, notify=changed)
    def estimated_total(self) -> int:
        return self._budget_snapshot.total_tasks if self._budget_snapshot else 0

    @Property(int, notify=changed)
    def estimated_cache_hits(self) -> int:
        return self._budget_snapshot.cache_hits if self._budget_snapshot else 0

    @Property(int, notify=changed)
    def estimated_cold_requests(self) -> int:
        return self._budget_snapshot.cold_requests if self._budget_snapshot else 0

    @Property(str, notify=changed)
    def data_path(self) -> str:
        return self._budget_snapshot.data_path if self._budget_snapshot else "等待资源预检"

    @Property(str, notify=changed)
    def quota_notice(self) -> str:
        return self._budget_snapshot.quota_notice if self._budget_snapshot else ""

    @Property(int, notify=changed)
    def quota_remaining(self) -> int:
        value = self._budget_snapshot.quota_remaining if self._budget_snapshot else None
        return value if value is not None else -1

    @Property(int, notify=changed)
    def quota_new_symbols(self) -> int:
        value = self._budget_snapshot.quota_new_symbols if self._budget_snapshot else None
        return value if value is not None else -1

    @Property(int, notify=changed)
    def quota_shortfall(self) -> int:
        return self._budget_snapshot.quota_shortfall if self._budget_snapshot else 0

    @Property(bool, notify=changed)
    def quota_blocked(self) -> bool:
        return bool(self._budget_snapshot and self._budget_snapshot.quota_blocked)

    @Property(str, notify=changed)
    def futu_serial_notice(self) -> str:
        return self._budget_snapshot.futu_serial_notice if self._budget_snapshot else ""

    @Property(bool, notify=changed)
    def requires_budget_confirmation(self) -> bool:
        return (
            self._budget_snapshot is not None
            and self._budget_request == self.build_request()
            and self._budget_snapshot.storage_state is not StorageState.BLOCKED
            and self._budget_snapshot.requires_confirmation
            and not self._running
        )

    @Property(float, notify=changed)
    def progress(self) -> float:
        return self._progress

    @Property(int, notify=changed)
    def active_stage(self) -> int:
        return self._active_stage

    @Property(str, notify=changed)
    def status_text(self) -> str:
        return self._status_text

    @Property(str, notify=changed)
    def last_status(self) -> str:
        return self._last_status

    @Property(bool, notify=changed)
    def recovery_visible(self) -> bool:
        return self._failure_state.recovery_visible

    @Property(str, notify=changed)
    def recovery_tone(self) -> str:
        return self._failure_state.recovery_tone

    @Property(str, notify=changed)
    def recovery_message(self) -> str:
        return self._failure_state.recovery_message

    @Property(int, notify=changed)
    def retry_count(self) -> int:
        return self._failure_state.retry_count

    @Property(float, notify=changed)
    def wait_seconds(self) -> float:
        return self._failure_state.wait_seconds

    @Property(int, notify=changed)
    def active_concurrency(self) -> int:
        return self._failure_state.active_concurrency

    @Property(bool, notify=changed)
    def outcome_visible(self) -> bool:
        return self._failure_state.outcome_visible

    @Property(str, notify=changed)
    def outcome_tone(self) -> str:
        return self._failure_state.outcome_tone

    @Property(str, notify=changed)
    def outcome_title(self) -> str:
        return self._failure_state.outcome_title

    @Property(str, notify=changed)
    def outcome_summary(self) -> str:
        return self._failure_state.outcome_summary

    @Property(str, notify=changed)
    def outcome_primary_action(self) -> str:
        return self._failure_state.outcome_primary_action

    @Property(str, notify=changed)
    def outcome_primary_label(self) -> str:
        return self._failure_state.outcome_primary_label

    @Property(bool, notify=changed)
    def terminal_has_usable_results(self) -> bool:
        return self._terminal_has_usable_results

    @Property(list, notify=changed)
    def failure_groups(self) -> list[dict[str, object]]:
        return group_failures(self._failure_state.failures)

    @Property(int, notify=changed)
    def cache_hits(self) -> int:
        return self._cache_hits

    @Property(int, notify=changed)
    def fetched(self) -> int:
        return self._fetched

    @Property(int, notify=changed)
    def failure_count(self) -> int:
        return self._failures

    @Property(list, notify=changed)
    def results(self) -> list[dict[str, object]]:
        return [
            {
                **row,
                "reportSelected": row["symbol"] in self._report_symbols,
            }
            for row in self._results
        ]

    @Property(dict, notify=changed)
    def selected_detail(self) -> dict[str, object]:
        return self._selected_detail()

    def _selected_detail(self) -> dict[str, object]:
        return next(
            (row for row in self._results if row["symbol"] == self._selected_symbol),
            {},
        )

    @Property(list, notify=changed)
    def period_details(self) -> list[dict[str, object]]:
        return cast(
            list[dict[str, object]],
            self._selected_detail().get("periods", []),
        )

    @Property(str, notify=changed)
    def report_text(self) -> str:
        return self._report_text

    @Property(str, notify=changed)
    def report_error(self) -> str:
        return self._report_error

    @Property(bool, notify=changed)
    def report_available(self) -> bool:
        return bool(self._report_text)

    @Property(bool, notify=changed)
    def report_running(self) -> bool:
        return self._report_task is not None

    @Property(bool, notify=changed)
    def ai_configured(self) -> bool:
        return self._application.settings().ai_configured

    @Property(int, notify=changed)
    def report_symbol_count(self) -> int:
        return len(self._report_symbols)

    @Property(list, notify=changed)
    def history(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for record in self._application.list_extreme_deviation_history(limit=10):
            payload = cast(dict[str, object], record["payload"])
            request = cast(dict[str, object], payload.get("request", {}))
            results = cast(list[dict[str, object]], payload.get("results", []))
            reports = cast(list[dict[str, object]], payload.get("ai_reports", []))
            intervals = cast(list[object], request.get("intervals", []))
            rows.append(
                {
                    "runId": str(record["run_id"]),
                    "name": str(record["display_name"]),
                    "completedAt": display_datetime(
                        record["completed_at"],
                        self._application.settings().display_timezone,
                    ),
                    "pinned": bool(record["pinned"]),
                    "symbolCount": len(results),
                    "intervalCount": len(intervals),
                    "reportCount": len(reports),
                    "provider": str(payload.get("provider_display_name", "未记录")),
                    "requestedDateWindow": _window_text(payload.get("requested_date_window")),
                    "actualDateWindow": _window_text(payload.get("actual_date_window")),
                }
            )
        return rows

    @Property(list, notify=changed)
    def result_history(self) -> list[dict[str, object]]:
        """Project persisted single-security runs into the results list."""
        rows: list[dict[str, object]] = []
        for record in self._application.list_extreme_deviation_history(limit=10):
            payload = cast(dict[str, object], record["payload"])
            results = _payload_rows(cast(list[dict[str, object]], payload.get("results", [])))
            if len(results) != 1:
                continue
            result = results[0]
            status = _result_status_label(str(result["status"]))
            rows.append(
                {
                    "runId": str(record["run_id"]),
                    "completedAt": display_datetime(
                        record["completed_at"],
                        self._application.settings().display_timezone,
                    ),
                    "symbol": str(result["symbol"]),
                    "companyName": str(result["companyName"]),
                    "summary": f"{result['consensusLabel']} · {status}",
                    "status": status,
                }
            )
        return rows

    @Slot(str)
    def select_security(self, security_id: str) -> None:
        self._security_id = security_id if security_id in self._security_cache else ""
        self.changed.emit()

    @Slot(str, bool, result=bool)
    def set_interval_selected(self, raw: str, selected: bool) -> bool:
        try:
            interval = CandleInterval(raw)
        except ValueError:
            return False
        if interval not in SUPPORTED_INTERVALS:
            return False
        if selected:
            self._selected_intervals.add(interval)
        elif len(self._selected_intervals) > 1:
            self._selected_intervals.discard(interval)
        else:
            return False
        self._budget_request = None
        self._budget_snapshot = None
        self.changed.emit()
        return True

    @Slot(result=bool)
    def prepare_new_run(self) -> bool:
        """Open a clean configuration form without deleting saved history."""
        if self._running or self._budget_task is not None:
            return False
        self._security_id = ""
        self._selected_intervals = set(SUPPORTED_INTERVALS)
        self._budget_request = None
        self._budget_snapshot = None
        self._progress = 0.0
        self._active_stage = -1
        self._status_text = "就绪 · 选择一只证券和至少一个周期"
        self._last_status = ""
        self._cache_hits = 0
        self._fetched = 0
        self._failures = 0
        self._failure_state = FailureState()
        self._terminal_has_usable_results = False
        self._results = []
        self._selected_symbol = ""
        self._latest_run_id = ""
        self._report_symbols.clear()
        self._report_text = ""
        self._report_error = ""
        self.changed.emit()
        # The page can be instantiated before the first securities import.
        # Refresh on every entry so that early empty data does not remain
        # cached for the lifetime of the desktop process.
        self.load_support_data()
        return True

    @Slot(str)
    def select_watchlist(self, watchlist_id: str) -> None:
        """Compatibility route for saved automation scripts.

        The visible product no longer accepts a watchlist for this analysis.
        A legacy caller selecting a pool is mapped deterministically to its
        first member, rather than silently reviving the costly pool run.
        """
        try:
            watchlist = self._application.master_data.get_watchlist(watchlist_id)
        except (KeyError, ValueError):
            self.select_security("")
            return
        security_id = watchlist.memberships[0].security_id if watchlist.memberships else ""
        self.select_security(security_id)

    @Slot(result=bool)
    def load_support_data(self) -> bool:
        if self._support_task is not None:
            return False
        task = _Task(self._application, support=True)
        self._support_task = task
        task.signals.finished.connect(self._on_finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(str)
    def set_end_date(self, raw: str) -> None:
        candidate = parse_iso_date(raw)
        today = display_today(self._display_timezone)
        if candidate is None or not validate_historical_date(candidate, today):
            self._requested_end_date = None
            self._end_date = None
            self._date_resolution_text = "只能选择今天之前的日期"
            self.changed.emit()
            return
        if self._calendar_task is not None:
            return
        self._requested_end_date = candidate
        self._end_date = candidate
        self._date_resolution_text = "正在确认交易日…"
        self.changed.emit()
        self._start_calendar(candidate)

    @Slot(result=bool)
    def refresh_latest_trading_day(self) -> bool:
        if self._calendar_task is not None:
            return False
        boundary = maximum_historical_date(self._display_timezone)
        self._requested_end_date = boundary
        self._end_date = boundary
        self._date_resolution_text = "正在确认最近完整交易日…"
        self.changed.emit()
        self._start_calendar(boundary)
        return True

    @Slot()
    def refresh_settings(self) -> None:
        """Reproject visible result timestamps after settings change."""
        self._display_timezone = self._application.settings().display_timezone
        self.changed.emit()

    def _start_calendar(self, boundary: date) -> None:
        task = _Task(self._application, calendar_boundary=boundary)
        self._calendar_task = task
        task.signals.finished.connect(self._on_finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)

    def build_request(self) -> ExtremeDeviationRequest | None:
        if (
            not self._security_id
            or not self._securities_loaded
            or self._end_date is None
            or self._calendar_task is not None
            or self._support_task is not None
        ):
            return None
        return ExtremeDeviationRequest(
            "",
            tuple(
                interval for interval in SUPPORTED_INTERVALS if interval in self._selected_intervals
            ),
            self._end_date,
            security_id=self._security_id,
        )

    @Slot(result=bool)
    def start(self) -> bool:
        request = self.build_request()
        if request is None or self._running or self._budget_task is not None:
            return False
        self._budget_request = request
        self._budget_snapshot = None
        self._failure_state = FailureState()
        self._terminal_has_usable_results = False
        task = AnalysisBudgetTask(self._application, request)
        self._budget_task = task
        self._status_text = "正在检查资源预算 · 只读取本机缓存"
        task.signals.finished.connect(self._on_budget_finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(result=bool)
    def confirm_budget_and_start(self) -> bool:
        request = self._budget_request
        snapshot = self._budget_snapshot
        if (
            request is None
            or snapshot is None
            or snapshot.storage_state is StorageState.BLOCKED
            or not snapshot.requires_confirmation
            or not snapshot.can_confirm_primary
            or self._running
        ):
            return False
        self._budget_request = None
        self._budget_snapshot = None
        self._launch_run(request)
        return True

    @Slot(result=bool)
    def use_yahoo_for_budget_and_start(self) -> bool:
        request = self._budget_request
        snapshot = self._budget_snapshot
        if (
            request is None
            or snapshot is None
            or snapshot.storage_state is StorageState.BLOCKED
            or not snapshot.can_force_yahoo
            or self._running
        ):
            return False
        self._budget_request = None
        self._budget_snapshot = None
        self._launch_run(request, force_yahoo=True)
        return True

    @Slot()
    def dismiss_budget_confirmation(self) -> None:
        self._budget_request = None
        self._budget_snapshot = None
        self._status_text = "已取消本次复盘"
        self.changed.emit()

    def _launch_run(
        self,
        request: ExtremeDeviationRequest,
        *,
        force_yahoo: bool = False,
    ) -> None:
        self._fallback_gate = FallbackConsentGate(self)
        self._fallback_gate.changed.connect(self._on_fallback_changed)
        self._fallback_gate.settings_requested.connect(self.cancel)
        self._fallback_gate.resolved.connect(self._on_process_fallback_resolved)
        self._running = True
        self._progress = 0.0
        self._active_stage = 0
        self._status_text = "准备复盘"
        self._last_status = ""
        self._cache_hits = 0
        self._fetched = 0
        self._failures = 0
        self._failure_state = FailureState()
        self._progress_diagnostics.reset()
        self.changed.emit()
        program = self._worker_program()
        if program is None:
            task = _Task(
                self._application,
                request=request,
                fallback_gate=(None if force_yahoo else self._fallback_gate),
                force_yahoo=force_yahoo,
            )
            self._task = task
            task.signals.progress.connect(self._on_progress)
            task.signals.finished.connect(self._on_finished)
            QThreadPool.globalInstance().start(task)
            return
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._on_run_process_output)
        process.readyReadStandardError.connect(self._drain_run_process_error)
        process.finished.connect(self._on_run_process_finished)
        process.errorOccurred.connect(self._on_run_process_error)
        self._run_process = process
        self._run_process_buffer = b""
        self._run_process_result = None
        self._run_cancel_requested = False
        arguments = (
            self._worker_arguments(request, force_yahoo=True)
            if force_yahoo
            else self._worker_arguments(request)
        )
        process.start(str(program), arguments)

    def _worker_program(self) -> Path | None:
        if self._application.paths.environment not in {
            RuntimeEnvironment.PRODUCTION,
            RuntimeEnvironment.DEVELOPMENT,
        }:
            return None
        candidate = Path(QCoreApplication.applicationDirPath()) / "stock-toolbox"
        return candidate if candidate.is_file() else None

    def _worker_arguments(
        self,
        request: ExtremeDeviationRequest,
        *,
        force_yahoo: bool = False,
    ) -> list[str]:
        environment = self._application.paths.environment
        environment_name = "production" if environment is RuntimeEnvironment.PRODUCTION else "dev"
        home = next(
            (
                parent.parent
                for parent in self._application.paths.data_root.parents
                if parent.name == "Library"
            ),
            Path.home(),
        )
        arguments = [
            "--env",
            environment_name,
            "--home",
            str(home),
            "analysis",
            "extreme-deviation",
            "run-worker",
            "--security-id",
            request.security_id,
            "--end-date",
            request.requested_end_date.isoformat(),
        ]
        for interval in request.intervals:
            arguments.extend(("--interval", interval.value))
        if force_yahoo:
            arguments.append("--force-yahoo")
        return arguments

    @Slot(object, object)
    def _on_budget_finished(
        self,
        request: object,
        raw: object,
    ) -> None:
        self._budget_task = None
        if not isinstance(request, ExtremeDeviationRequest) or request != self._budget_request:
            self.changed.emit()
            return
        if not isinstance(raw, AnalysisBudgetSnapshot):
            self._budget_request = None
            self._budget_snapshot = None
            self._last_status = "FAILED"
            self._status_text = "资源预检失败，请稍后重试"
            self._failure_state = finish_outcome(
                FailureState(),
                "FAILED",
                None,
                "internal",
            )
            self.changed.emit()
            return
        self._budget_snapshot = raw
        if raw.storage_state is StorageState.BLOCKED:
            code = raw.error_code or "storage_unavailable"
            self._last_status = "FAILED"
            self._status_text = f"资源预检失败 · {code}"
            self._failure_state = finish_outcome(
                FailureState(),
                "FAILED",
                None,
                code,
            )
            self.changed.emit()
            return
        if raw.requires_confirmation:
            self._status_text = f"任务较大 · {raw.cold_requests} 个冷请求等待确认"
            self.changed.emit()
            return
        self._launch_run(request)

    @Slot(result=bool)
    def cancel(self) -> bool:
        if self._run_process is not None:
            self._run_cancel_requested = True
            self._run_process.terminate()
            self._status_text = "正在安全取消…"
            self.changed.emit()
            return True
        if self._task is None:
            return False
        self._fallback_gate.cancel()
        accepted = (
            self._application.cancel_operation(self._task.operation_id) == CancelResult.ACCEPTED
        )
        if accepted:
            self._status_text = "正在安全取消…"
            self.changed.emit()
        return accepted

    @Slot()
    def _on_fallback_changed(self) -> None:
        if self._fallback_gate.pending:
            provider = self._application.provider_identity().display_name
            self._status_text = f"{provider} 暂不可用 · 等待是否使用 Yahoo 备用数据"
        self.changed.emit()

    @Slot(str, result=bool)
    def select_symbol(self, symbol: str) -> bool:
        if not any(row["symbol"] == symbol for row in self._results):
            return False
        self._selected_symbol = symbol
        self.changed.emit()
        return True

    @Slot(str, bool)
    def set_report_symbol(self, symbol: str, selected: bool) -> None:
        if not any(row["symbol"] == symbol for row in self._results):
            return
        if selected:
            self._report_symbols.add(symbol)
        else:
            self._report_symbols.discard(symbol)
        self.changed.emit()

    @Slot(result=bool)
    def generate_report(self) -> bool:
        symbols = tuple(
            str(row["symbol"])
            for row in self._results
            if str(row["symbol"]) in self._report_symbols
        )
        return self._start_report(symbols)

    @Slot(result=bool)
    def generate_selected_report(self) -> bool:
        return self._start_report((self._selected_symbol,) if self._selected_symbol else ())

    def _start_report(self, symbols: tuple[str, ...]) -> bool:
        if (
            not self._latest_run_id
            or not symbols
            or len(symbols) > 20
            or self._report_task is not None
        ):
            return False
        task = _Task(
            self._application,
            run_id=self._latest_run_id,
            symbols=symbols,
        )
        if not reserve_report_operation(
            self._application,
            task.operation_id,
        ):
            return False
        self._report_task = task
        self._report_error = ""
        task.signals.finished.connect(self._on_finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(str, result=bool)
    def select_run(self, run_id: str) -> bool:
        record = next(
            (
                item
                for item in self._application.list_extreme_deviation_history(limit=10)
                if str(item["run_id"]) == run_id
            ),
            None,
        )
        if record is None:
            return False
        payload = cast(dict[str, object], record["payload"])
        self._results = _payload_rows(cast(list[dict[str, object]], payload.get("results", [])))
        reports = cast(list[dict[str, object]], payload.get("ai_reports", []))
        self._report_text = str(reports[-1].get("content", "")) if reports else ""
        self._report_error = ""
        self._latest_run_id = run_id
        self._selected_symbol = str(self._results[0]["symbol"]) if self._results else ""
        self._report_symbols.clear()
        self.changed.emit()
        return True

    @Slot(str, bool, result=bool)
    def set_pinned(self, run_id: str, pinned: bool) -> bool:
        try:
            self._application.pin_extreme_deviation_history(run_id, pinned)
        except (KeyError, RuntimeError, ValueError):
            return False
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def delete_history(self, run_id: str) -> bool:
        try:
            self._application.delete_extreme_deviation_history(run_id)
        except (KeyError, RuntimeError, ValueError):
            return False
        if self._latest_run_id == run_id:
            self._latest_run_id = ""
            self._results = []
            self._selected_symbol = ""
            self._report_text = ""
            self._report_error = ""
        self.changed.emit()
        return True

    @Slot(str, str, str, result=bool)
    def export_history(
        self,
        run_id: str,
        format_name: str,
        target: str,
    ) -> bool:
        local_target = QUrl(target).toLocalFile() if target.startswith("file:") else target
        try:
            content = self._application.export_extreme_deviation_history(
                run_id,
                format_name,
            )
            Path(local_target).write_text(content, encoding="utf-8")
        except (KeyError, OSError, RuntimeError, ValueError):
            return False
        return True

    @Slot(object)
    def _on_progress(self, raw: object) -> None:
        if not isinstance(raw, ExtremeDeviationProgress):
            return
        if self._task is not None and self._progress_diagnostics.accept(
            raw.stage,
            raw.completed,
            raw.total,
            has_feedback=raw.feedback is not None,
        ):
            emit_progress(
                self._application.diagnostics,
                module="extreme_deviation",
                task_id=self._task.operation_id,
                stage=raw.stage,
                completed=raw.completed,
                total=raw.total,
                ticker=raw.current or "",
                feedback=raw.feedback,
            )
        stage = "FETCH_CANDLES" if raw.stage == "FETCH_FALLBACK" else raw.stage
        if stage not in _STAGES:
            return
        self._active_stage = _STAGES.index(stage)
        fraction = raw.completed / raw.total if raw.total else 0.0
        self._progress = (self._active_stage + fraction) / len(_STAGES)
        self._cache_hits = raw.cache_hits
        self._fetched = raw.fetched
        self._failures = raw.failures
        current = f" · {raw.current}" if raw.current else ""
        stage_label = (
            "正在使用 Yahoo 备用数据补充"
            if raw.stage == "FETCH_FALLBACK"
            else _STAGE_LABELS[raw.stage]
        )
        self._status_text = f"{stage_label} · {raw.completed}/{raw.total}{current}"
        if raw.feedback is not None:
            self._failure_state = advance_feedback(
                self._failure_state,
                raw.feedback,
            )
        else:
            self._failure_state = advance_running(self._failure_state)
        self._progress_updates.request()

    @Slot()
    def _on_run_process_output(self) -> None:
        process = self._run_process
        if process is None:
            return
        self._run_process_buffer += process.readAllStandardOutput().data()
        while b"\n" in self._run_process_buffer:
            raw_line, self._run_process_buffer = self._run_process_buffer.split(b"\n", 1)
            self._consume_process_line(raw_line)

    @Slot()
    def _drain_run_process_error(self) -> None:
        process = self._run_process
        if process is not None:
            process.readAllStandardError()

    def _consume_process_line(self, raw_line: bytes) -> None:
        try:
            payload = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("type", ""))
        if event_type == "progress":
            raw_feedback = payload.get("feedback")
            feedback: RunFeedback | None = None
            if isinstance(raw_feedback, dict):
                try:
                    raw_code = raw_feedback.get("failure_code")
                    feedback = RunFeedback(
                        FeedbackKind(str(raw_feedback["kind"])),
                        FailureCode(str(raw_code)) if raw_code else None,
                        str(raw_feedback.get("symbol", "")),
                        str(raw_feedback.get("interval", "")),
                        int(raw_feedback.get("attempt", 0)),
                        int(raw_feedback.get("max_attempts", 0)),
                        float(raw_feedback.get("wait_seconds", 0)),
                        int(raw_feedback.get("active_concurrency", 4)),
                    )
                except (KeyError, TypeError, ValueError):
                    feedback = None
            self._on_progress(
                ExtremeDeviationProgress(
                    str(payload.get("stage", "")),
                    int(payload.get("completed", 0)),
                    int(payload.get("total", 0)),
                    str(payload.get("current", "")) or None,
                    int(payload.get("cache_hits", 0)),
                    int(payload.get("fetched", 0)),
                    int(payload.get("failures", 0)),
                    feedback,
                )
            )
        elif event_type == "result":
            self._run_process_result = payload
        elif event_type == "fallback":
            try:
                self._fallback_gate.present(
                    FallbackOffer(
                        str(payload.get("operation_kind", "extreme_deviation")),
                        tuple(str(item) for item in payload.get("failed_symbols", [])),
                        tuple(str(item) for item in payload.get("intervals", [])),
                        tuple(FailureCode(str(item)) for item in payload.get("failure_codes", [])),
                        int(payload.get("completed", 0)),
                        int(payload.get("total", 0)),
                    )
                )
            except (TypeError, ValueError):
                return
        elif event_type == "error":
            self._run_process_result = {
                "status": "FAILED",
                "run_id": None,
                "error_code": str(payload.get("code", "extreme_deviation_worker_failed")),
            }

    @Slot(bool)
    def _on_process_fallback_resolved(self, accepted: bool) -> None:
        process = self._run_process
        if process is None:
            return
        process.write(b"accept\n" if accepted else b"decline\n")

    @Slot(int, object)
    def _on_run_process_finished(self, exit_code: int, _exit_status: object) -> None:
        self._progress_updates.cancel()
        process = self._run_process
        if process is None:
            return
        self._on_run_process_output()
        if self._run_process_buffer.strip():
            self._consume_process_line(self._run_process_buffer.strip())
        raw = self._run_process_result or {}
        canceled = self._run_cancel_requested
        self._run_process = None
        self._run_process_buffer = b""
        self._run_process_result = None
        self._run_cancel_requested = False
        process.deleteLater()
        status_text = "CANCELED" if canceled else str(raw.get("status", "FAILED"))
        try:
            status = ExtremeDeviationRunStatus(status_text)
        except ValueError:
            status = ExtremeDeviationRunStatus.FAILED
        error_code = (
            None
            if canceled
            else str(raw.get("error_code") or "")
            or (None if exit_code == 0 else "extreme_deviation_worker_failed")
        )
        run_id = str(raw.get("run_id") or "")
        self._finish_process_run(
            status,
            run_id,
            error_code,
            reliability_from_payload(raw.get("reliability")),
        )

    def _finish_process_run(
        self,
        status: ExtremeDeviationRunStatus,
        run_id: str,
        error_code: str | None,
        reliability: AnalysisReliability | None = None,
    ) -> None:
        self._running = False
        self._last_status = status.value
        self._failure_state = finish_outcome(
            self._failure_state,
            status.value,
            reliability,
            error_code,
        )
        self._terminal_has_usable_results = bool(
            run_id
            and status in {ExtremeDeviationRunStatus.READY, ExtremeDeviationRunStatus.PARTIAL}
            and self.select_run(run_id)
        )
        self._status_text = {
            "READY": "复盘完成",
            "PARTIAL": "复盘完成 · 部分周期低置信度",
            "FAILED": f"复盘失败 · {error_code or 'unknown'}",
            "CANCELED": "已取消",
        }[status.value]
        if self._terminal_has_usable_results:
            self._progress = 1.0
            self._active_stage = len(_STAGES) - 1
        result = ExtremeDeviationRunResult(
            status,
            error_code=error_code,
            reliability=reliability,
        )
        self.changed.emit()
        self.finished.emit(result)

    @Slot(object)
    def _on_run_process_error(self, _error: object) -> None:
        self._progress_updates.cancel()
        process = self._run_process
        if process is None or process.state() is not QProcess.ProcessState.NotRunning:
            return
        self._run_process = None
        process.deleteLater()
        self._running = False
        self._last_status = "FAILED"
        self._status_text = "复盘进程启动失败"
        self.changed.emit()
        self.finished.emit(
            ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.FAILED,
                error_code="extreme_deviation_worker_start_failed",
            )
        )

    @Slot(str, object)
    def _on_finished(self, kind: str, raw: object) -> None:
        if isinstance(raw, OperationAdmissionClosedError):
            if kind == "support":
                self._support_task = None
            elif kind == "calendar":
                self._calendar_task = None
            elif kind == "report":
                self._report_task = None
            else:
                self._task = None
                self._running = False
            self.changed.emit()
            return
        if kind == "support":
            self._support_task = None
            if isinstance(raw, tuple) and all(isinstance(item, SecurityDetailDTO) for item in raw):
                self._security_cache = {item.id: item for item in raw}
                self._securities_loaded = True
                if self._security_id and self._security_id not in self._security_cache:
                    self._security_id = ""
            else:
                self._securities_loaded = False
            self.changed.emit()
            self.support_finished.emit()
            return
        if kind == "calendar":
            self._calendar_task = None
            boundary = None
            result: object = raw
            if isinstance(raw, tuple) and len(raw) == 2:
                boundary, result = raw
            if boundary != self._requested_end_date:
                self.calendar_finished.emit()
                return
            today = display_today(self._display_timezone)
            if isinstance(result, date) and validate_historical_date(
                result,
                today,
            ):
                self._end_date = result
                self._date_resolution_text = (
                    "已确认完整交易日"
                    if result == boundary
                    else f"所选日期休市，已回退至 {result.isoformat()}"
                )
            else:
                self._end_date = None
                self._date_resolution_text = "未能确认交易日，请稍后重试"
            self.changed.emit()
            self.calendar_finished.emit()
            return
        if kind == "report":
            self._report_task = None
            completed_run_id = ""
            report: object = raw
            if isinstance(raw, tuple) and len(raw) == 2:
                completed_run_id = str(raw[0])
                report = raw[1]
            if completed_run_id == self._latest_run_id:
                if isinstance(report, TechnicalReport):
                    self._report_text = report.content
                    self._report_error = ""
                else:
                    self._report_error = present_ai_report_failure(report).message
            self.changed.emit()
            self.report_finished.emit(report)
            return
        if not isinstance(raw, ExtremeDeviationRunResult):
            return
        self._task = None
        self._running = False
        self._last_status = raw.status.value
        self._failure_state = finish_outcome(
            self._failure_state,
            self._last_status,
            raw.reliability,
            raw.error_code,
        )
        self._terminal_has_usable_results = (
            self._last_status in {"READY", "PARTIAL"}
            and raw.run is not None
            and bool(raw.run.results)
        )
        self._status_text = {
            "READY": "复盘完成",
            "PARTIAL": "复盘完成 · 部分周期失败",
            "FAILED": f"复盘失败 · {raw.error_code or 'unknown'}",
            "CANCELED": "已取消",
        }.get(self._last_status, self._last_status)
        if raw.run is not None:
            self._progress = 1.0
            self._active_stage = len(_STAGES) - 1
            self._cache_hits = raw.run.cache_hits
            self._fetched = raw.run.fetched
            self._latest_run_id = raw.run.run_id
            self._report_text = ""
            self._report_error = ""
            self._report_symbols.clear()
            self._results = [_result_row(item) for item in raw.run.results]
            self._selected_symbol = str(self._results[0]["symbol"]) if self._results else ""
        self.changed.emit()
        self.finished.emit(raw)


def _window_text(value: object) -> str:
    if not isinstance(value, list) or len(value) != 2:
        return ""
    return f"{value[0]} — {value[1]}"


def _chart_points_with_visual_strength(
    points: list[dict[str, object]],
) -> list[dict[str, object]]:
    buy_strengths, sell_strengths = pressure_contrast_series(
        tuple(_float_value(point.get("buyPressure")) for point in points),
        tuple(_float_value(point.get("sellPressure")) for point in points),
    )
    return [
        {
            **point,
            "buyVisualStrength": buy_strength,
            "sellVisualStrength": sell_strength,
        }
        for point, buy_strength, sell_strength in zip(
            points,
            buy_strengths,
            sell_strengths,
            strict=True,
        )
    ]


def _completed_bar_timestamp(interval: str, value: object) -> str:
    """Project intraday provider start times to user-facing close times."""
    duration = {
        CandleInterval.MIN_30.value: timedelta(minutes=30),
        CandleInterval.MIN_60.value: timedelta(minutes=60),
    }.get(interval)
    if duration is None:
        return _text(value)
    parsed = value if isinstance(value, datetime) else None
    if parsed is None and isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
    return _text(parsed + duration) if parsed is not None else _text(value)


def _result_row(result: SymbolDeviationResult) -> dict[str, object]:
    periods = []
    scores: dict[str, int | None] = {}
    for period in result.periods:
        score = period.score
        scores[period.interval.value] = score.score if score is not None else None
        periods.append(
            {
                "interval": period.interval.value,
                "intervalLabel": _INTERVAL_LABELS[period.interval],
                "score": score.score if score is not None else None,
                "label": score.label if score is not None else "数据失败",
                "buyDeviation": score.buy_deviation if score is not None else None,
                "sellDeviation": score.sell_deviation if score is not None else None,
                "confidence": (
                    _CONFIDENCE_LABELS[score.confidence.value] if score is not None else "—"
                ),
                "latestAt": _text(score.latest_at if score is not None else None),
                "status": "完成" if period.error_code is None else "数据异常",
                "buyPercentile": score.buy_percentile if score is not None else None,
                "sellPercentile": score.sell_percentile if score is not None else None,
                "rangePosition": score.range_position if score is not None else None,
                "buyTriggerAge": score.buy_trigger_age if score is not None else None,
                "sellTriggerAge": score.sell_trigger_age if score is not None else None,
                "chartPoints": _chart_points_with_visual_strength(
                    [
                        {
                            "timestamp": _completed_bar_timestamp(
                                period.interval.value,
                                item.timestamp,
                            ),
                            "open": item.open,
                            "high": item.high,
                            "low": item.low,
                            "close": item.close,
                            "score": item.score,
                            "label": item.label or "中性",
                            "buyPressure": item.buy_pressure,
                            "sellPressure": item.sell_pressure,
                        }
                        for item in period.chart_points
                    ],
                ),
            }
        )
    return {
        "symbol": result.symbol,
        "companyName": result.company_name,
        "classification": result.classification_name,
        "consensus": result.consensus.kind.value,
        "consensusLabel": _CONSENSUS_LABELS[result.consensus.kind.value],
        "score": result.consensus.score,
        "attentionScore": result.consensus.attention_score,
        "status": result.status,
        "scores": scores,
        "periods": periods,
    }


def _payload_rows(results: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for result in results:
        consensus = cast(dict[str, object], result.get("consensus", {}))
        kind = str(consensus.get("kind", "NEUTRAL"))
        consensus_score = _optional_int(consensus.get("score")) or 0
        attention_score = _optional_int(consensus.get("attention_score"))
        periods = []
        scores: dict[str, int | None] = {}
        for period in cast(list[dict[str, object]], result.get("periods", [])):
            raw_score = period.get("score")
            score = cast(dict[str, object], raw_score) if isinstance(raw_score, dict) else {}
            interval = str(period.get("interval", ""))
            numeric_score = _optional_int(score.get("score"))
            scores[interval] = numeric_score
            periods.append(
                {
                    "interval": interval,
                    "intervalLabel": _interval_label(interval),
                    "score": numeric_score,
                    "label": str(score.get("label", "数据失败")),
                    "buyDeviation": score.get("buy_deviation"),
                    "sellDeviation": score.get("sell_deviation"),
                    "confidence": _CONFIDENCE_LABELS.get(
                        str(score.get("confidence", "")),
                        "—",
                    ),
                    "latestAt": str(score.get("latest_at") or "—"),
                    "status": ("完成" if not period.get("error_code") else "数据异常"),
                    "buyPercentile": score.get("buy_percentile"),
                    "sellPercentile": score.get("sell_percentile"),
                    "rangePosition": score.get("range_position"),
                    "buyTriggerAge": score.get("buy_trigger_age"),
                    "sellTriggerAge": score.get("sell_trigger_age"),
                    "chartPoints": _chart_points_with_visual_strength(
                        [
                            {
                                "timestamp": _completed_bar_timestamp(
                                    interval,
                                    item.get("timestamp", ""),
                                ),
                                "open": item.get("open"),
                                "high": item.get("high"),
                                "low": item.get("low"),
                                "close": item.get("close"),
                                "score": item.get("score"),
                                "label": str(item.get("label") or "中性"),
                                "buyPressure": item.get("buy_pressure", 0.0),
                                "sellPressure": item.get("sell_pressure", 0.0),
                            }
                            for item in cast(
                                list[dict[str, object]], period.get("chart_points", [])
                            )
                            if isinstance(item, dict)
                        ],
                    ),
                }
            )
        rows.append(
            {
                "symbol": str(result.get("symbol", "")),
                "companyName": str(result.get("company_name", "")),
                "classification": str(result.get("classification_name", "")),
                "consensus": kind,
                "consensusLabel": _CONSENSUS_LABELS.get(kind, kind),
                "score": consensus_score,
                "attentionScore": (
                    abs(consensus_score) if attention_score is None else attention_score
                ),
                "status": str(result.get("status", "")),
                "scores": scores,
                "periods": periods,
            }
        )
    return rows


def _interval_label(raw: str) -> str:
    try:
        return _INTERVAL_LABELS[CandleInterval(raw)]
    except ValueError:
        return raw


def _result_status_label(raw: str) -> str:
    return {
        "READY": "完成",
        "PARTIAL": "部分完成",
    }.get(raw, "数据异常")


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _float_value(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _text(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "—")
