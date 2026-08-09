"""QML adapter for multi-period turning-point runs and history."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, cast

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

from stock_toolbox.analyses.resource_budget import AnalysisBudgetSnapshot
from stock_toolbox.analyses.turning_point.application.history import (
    project_turning_point_history,
)
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointProgress,
    TurningPointRequest,
    TurningPointRunResult,
    TurningPointRunStatus,
)
from stock_toolbox.analyses.turning_point.application.report import (
    TurningPointReport,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    TurningPointTradeSide,
)
from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.core.market_data.date_policy import (
    display_today,
    maximum_historical_date,
    parse_iso_date,
    validate_historical_date,
)
from stock_toolbox.core.market_data.fallback import FallbackOffer
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.operations.executor import OperationAdmissionClosedError
from stock_toolbox.core.operations.failure_policy import AnalysisReliability, FailureCode
from stock_toolbox.core.operations.registry import CancelResult, OperationStatus
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

_INTERVALS = (
    (CandleInterval.MIN_30, "30 分钟"),
    (CandleInterval.MIN_60, "1 小时"),
    (CandleInterval.MIN_120, "2 小时"),
    (CandleInterval.MIN_240, "4 小时"),
    (CandleInterval.DAY, "日线"),
    (CandleInterval.WEEK, "周线"),
)
_DEFAULT_INTERVALS = {
    CandleInterval.MIN_30,
    CandleInterval.MIN_60,
    CandleInterval.DAY,
}
_STAGES = (
    "FREEZE_WATCHLIST",
    "FETCH_CANDLES",
    "COMPUTE",
    "ANNOTATE_RISK",
    "SAVE",
)
_STAGE_LABELS = {
    "FREEZE_WATCHLIST": "冻结股票池",
    "FETCH_CANDLES": "服务端指标",
    "FETCH_INDICATORS": "服务端指标",
    "COMPUTE": "计算多周期信号",
    "ANNOTATE_RISK": "补充风险标注",
    "SAVE": "保存结果",
}
_RISK_LABELS = {
    "SMALL_MARKET_CAP": "小市值 · 低于 20 亿美元",
    "MARKET_VALUE_UNKNOWN": "市值未知",
}


class _TaskSignals(QObject):
    progress = Signal(object)
    finished = Signal(str, object)


class _Task(QRunnable):
    def __init__(
        self,
        application: StockToolboxApplication,
        *,
        request: TurningPointRequest | None = None,
        run_id: str = "",
        support: bool = False,
        fallback_gate: FallbackConsentGate | None = None,
        force_yahoo: bool = False,
    ) -> None:
        super().__init__()
        self.application = application
        self.request = request
        self.run_id = run_id
        self.support = support
        self.fallback_gate = fallback_gate
        self.force_yahoo = force_yahoo
        self.operation_id = str(uuid.uuid4()) if request is not None or bool(run_id) else ""
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        if self.support:
            try:
                result: object = {
                    "watchlists": self.application.master_data.list_watchlists(),
                    "history": self.application.list_turning_point_history(limit=10),
                    "ai_configured": (
                        self.application.settings().ai_configured
                        or self.application.paths.environment
                        in {
                            RuntimeEnvironment.SCENARIO,
                            RuntimeEnvironment.INTEGRATION,
                        }
                    ),
                }
            except Exception as error:  # noqa: BLE001 - UI boundary
                result = error
            self.signals.finished.emit("support", result)
            return
        if self.request is not None:
            try:
                result = self.application.run_turning_point(
                    self.request,
                    operation_id=self.operation_id,
                    progress=self.signals.progress.emit,
                    fallback_consent=(
                        self.fallback_gate.request if self.fallback_gate is not None else None
                    ),
                    force_yahoo=self.force_yahoo,
                )
            except OperationAdmissionClosedError as error:
                self.signals.finished.emit("run", error)
                return
            try:
                history: object = self.application.list_turning_point_history(limit=10)
            except Exception:  # noqa: BLE001 - run result remains usable
                history = []
            self.signals.finished.emit("run", (result, history))
            return
        if self.run_id:
            report = execute_report_operation(
                self.application,
                self.operation_id,
                lambda control: self.application.generate_turning_point_report(
                    self.run_id,
                    operation_control=control,
                ),
            )
            self.signals.finished.emit("report", (self.run_id, report))
            return
        try:
            result = self.application.latest_completed_trading_day()
        except OperationAdmissionClosedError as error:
            result = error
        self.signals.finished.emit("calendar", result)


class TurningPointBridge(QObject):
    changed = Signal()
    finished = Signal(object)
    report_finished = Signal(object)

    def __init__(
        self,
        application: StockToolboxApplication,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._display_timezone = application.settings().display_timezone
        self._watchlist_id = ""
        self._selected_intervals = set(_DEFAULT_INTERVALS)
        self._result_interval = "attention"
        self._result_intervals: tuple[str, ...] = ()
        self._end_date: date | None = None
        self._trade_side = TurningPointTradeSide.RIGHT_CONFIRMED
        self._budget_task: AnalysisBudgetTask | None = None
        self._budget_request: TurningPointRequest | None = None
        self._budget_snapshot: AnalysisBudgetSnapshot | None = None
        self._force_yahoo_run = False
        self._task: _Task | None = None
        self._run_process: QProcess | None = None
        self._run_process_buffer = b""
        self._run_process_result: dict[str, object] | None = None
        self._run_operation_id = ""
        self._run_cancel_requested = False
        self._calendar_task: _Task | None = None
        self._report_task: _Task | None = None
        self._running = False
        self._progress_updates = UiChangeCoalescer(self)
        self._progress_updates.changed.connect(self.changed.emit)
        self._progress_diagnostics = ProgressEventSampler()
        self._progress = 0.0
        self._active_stage = -1
        self._status_text = "就绪 · 选择股票池和一个或多个周期"
        self._last_status = ""
        self._all_results: list[dict[str, object]] = []
        self._failure_count = 0
        self._failure_state = FailureState()
        self._selected_run_id = ""
        self._report_text = ""
        self._report_error = ""
        self._watchlists: list[dict[str, object]] = []
        self._history: list[dict[str, object]] = []
        self._history_records: dict[str, dict[str, Any]] = {}
        self._ai_configured = self._application.paths.environment in {
            RuntimeEnvironment.SCENARIO,
            RuntimeEnvironment.INTEGRATION,
        }
        self._support_task: _Task | None = None
        self._support_loaded = False
        self._unmatched_results: list[dict[str, object]] = []
        self._results_available = False
        self._fallback_gate = FallbackConsentGate(self)
        self._fallback_gate.changed.connect(self._on_fallback_changed)
        self._fallback_gate.settings_requested.connect(self.cancel)

    @Property(list, notify=changed)
    def watchlists(self) -> list[dict[str, object]]:
        return self._watchlists

    @Property(QObject, notify=changed)
    def fallback_gate(self) -> QObject:
        return self._fallback_gate

    @Property(bool, notify=changed)
    def support_loading(self) -> bool:
        return self._support_task is not None

    @Property(bool, notify=changed)
    def support_loaded(self) -> bool:
        return self._support_loaded

    @Property(str, notify=changed)
    def selected_watchlist_id(self) -> str:
        return self._watchlist_id

    @Property(int, notify=changed)
    def member_count(self) -> int:
        for watchlist in self._watchlists:
            if watchlist.get("id") == self._watchlist_id:
                count = watchlist.get("memberCount", 0)
                return count if isinstance(count, int) else 0
        return 0

    @Property(list, notify=changed)
    def intervals(self) -> list[dict[str, object]]:
        return [
            {
                "value": interval.value,
                "label": label,
                "selected": interval in self._selected_intervals,
            }
            for interval, label in _INTERVALS
        ]

    @Property(int, notify=changed)
    def selected_interval_count(self) -> int:
        return len(self._selected_intervals)

    @Property(str, notify=changed)
    def end_date(self) -> str:
        return self._end_date.isoformat() if self._end_date is not None else ""

    @Property(str, notify=changed)
    def maximum_historical_date(self) -> str:
        return maximum_historical_date(
            self._display_timezone,
        ).isoformat()

    @Property(bool, notify=changed)
    def calendar_loading(self) -> bool:
        return self._calendar_task is not None

    @Property(str, notify=changed)
    def trade_side(self) -> str:
        return self._trade_side.value

    @Property(str, notify=changed)
    def trade_side_label(self) -> str:
        return _trade_side_label(self._trade_side)

    @Property(bool, notify=changed)
    def can_start(self) -> bool:
        return (
            bool(self._watchlist_id)
            and bool(self._selected_intervals)
            and self._end_date is not None
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
        return self._budget_snapshot.futu_serial_notice if self._budget_snapshot is not None else ""

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

    @Property(list, notify=changed)
    def failure_groups(self) -> list[dict[str, object]]:
        return group_failures(self._failure_state.failures)

    @Property(int, notify=changed)
    def matched_count(self) -> int:
        return len(self._all_results)

    @Property(int, notify=changed)
    def failure_count(self) -> int:
        return self._failure_count

    @Property(int, notify=changed)
    def unmatched_count(self) -> int:
        return len(self._unmatched_results)

    @Property(list, notify=changed)
    def unmatched_results(self) -> list[dict[str, object]]:
        return self._unmatched_results

    @Property(bool, notify=changed)
    def results_available(self) -> bool:
        return self._results_available

    @Property(str, notify=changed)
    def selected_run_id(self) -> str:
        return self._selected_run_id

    @Property(str, notify=changed)
    def result_view(self) -> str:
        return self._result_interval

    @Property(bool, notify=changed)
    def selected_run_pinned(self) -> bool:
        return next(
            (bool(row["pinned"]) for row in self._history if row["runId"] == self._selected_run_id),
            False,
        )

    @Property(list, notify=changed)
    def results(self) -> list[dict[str, object]]:
        if self._result_interval == "attention":
            return self._all_results
        rows: list[dict[str, object]] = []
        for row in self._all_results:
            raw_periods = row.get("periodResults", [])
            periods = (
                cast(list[dict[str, object]], raw_periods) if isinstance(raw_periods, list) else []
            )
            selected_period = next(
                (
                    period
                    for period in periods
                    if period.get("interval") == self._result_interval
                    and period.get("decision") == "MATCHED"
                ),
                None,
            )
            if selected_period is not None:
                rows.append({**row, "selectedPeriod": selected_period})
        return rows

    @Property(str, notify=changed)
    def result_empty_text(self) -> str:
        if not self._results_available:
            return "选择一条历史记录查看结果"
        if not self._all_results:
            return "本次没有证券命中所选周期；下方已按证券列出具体原因。"
        return "当前周期没有命中结果"

    @Property(list, notify=changed)
    def result_filters(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        if self._all_results:
            rows.append(
                {
                    "value": "attention",
                    "label": "综合关注",
                    "count": len(self._all_results),
                    "selected": self._result_interval == "attention",
                }
            )
        labels = {interval.value: label for interval, label in _INTERVALS}
        for raw in self._result_intervals:
            count = sum(
                raw
                in cast(
                    list[str],
                    row.get("matchedIntervals", []),
                )
                for row in self._all_results
            )
            if count == 0:
                continue
            rows.append(
                {
                    "value": raw,
                    "label": labels.get(raw, raw),
                    "count": count,
                    "selected": self._result_interval == raw,
                }
            )
        return rows

    @Property(str, notify=changed)
    def report_text(self) -> str:
        return self._report_text

    @Property(str, notify=changed)
    def report_error(self) -> str:
        return self._report_error

    @Property(bool, notify=changed)
    def report_running(self) -> bool:
        return self._report_task is not None

    @Property(str, notify=changed)
    def export_default_name(self) -> str:
        return self._export_default_name()

    def _export_default_name(self) -> str:
        if not self._selected_run_id:
            return "拐点筛选.csv"
        record = self._history_records.get(self._selected_run_id)
        if record is None:
            return "拐点筛选.csv"
        payload = cast(dict[str, Any], record.get("payload", {}))
        watchlist = _safe_filename_component(str(payload.get("watchlist_name", "股票池")))
        completed = (
            display_datetime(
                record["completed_at"],
                self._display_timezone,
            )
            .replace("-", "")
            .replace(":", "")
            .replace(" ", "-")
        )
        return f"拐点筛选_{watchlist}_{completed}.csv"

    @Property(str, notify=changed)
    def export_default_url(self) -> str:
        target = Path.home() / "Documents" / self._export_default_name()
        return QUrl.fromLocalFile(str(target)).toString()

    @Property(bool, notify=changed)
    def ai_configured(self) -> bool:
        return self._ai_configured

    @Property(list, notify=changed)
    def history(self) -> list[dict[str, object]]:
        return self._history

    @Slot(str, result=bool)
    def select_watchlist(self, watchlist_id: str) -> bool:
        if self._watchlists and watchlist_id not in {
            str(item.get("id", "")) for item in self._watchlists
        }:
            return False
        self._watchlist_id = watchlist_id
        self.changed.emit()
        return True

    @Slot(str)
    def set_interval(self, value: str) -> None:
        """Compatibility slot: select exactly one interval."""
        try:
            self._selected_intervals = {CandleInterval(value)}
        except ValueError:
            return
        self.changed.emit()

    @Slot(str, bool)
    def set_interval_selected(self, raw: str, selected: bool) -> None:
        try:
            interval = CandleInterval(raw)
        except ValueError:
            return
        if selected:
            self._selected_intervals.add(interval)
        elif len(self._selected_intervals) > 1:
            self._selected_intervals.discard(interval)
        self.changed.emit()

    @Slot(str, result=bool)
    def select_result_interval(self, raw: str) -> bool:
        valid = {"attention", *self._result_intervals}
        if raw not in valid:
            return False
        self._result_interval = raw
        self.changed.emit()
        return True

    @Slot(str)
    def set_end_date(self, raw: str) -> None:
        selected = parse_iso_date(raw)
        today = display_today(
            self._display_timezone,
        )
        self._end_date = (
            selected if selected is not None and validate_historical_date(selected, today) else None
        )
        self.changed.emit()

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

    @Slot(str, result=bool)
    def set_trade_side(self, raw: str) -> bool:
        if self._running:
            return False
        try:
            selected = TurningPointTradeSide(raw)
        except ValueError:
            return False
        if selected is self._trade_side:
            return True
        self._trade_side = selected
        self.changed.emit()
        return True

    @Slot()
    def refresh_latest_trading_day(self) -> None:
        if self._calendar_task is not None:
            return
        task = _Task(self._application)
        self._calendar_task = task
        task.signals.finished.connect(self._on_finished)
        QThreadPool.globalInstance().start(task)

    def build_request(self) -> TurningPointRequest | None:
        if not self._watchlist_id or not self._selected_intervals or self._end_date is None:
            return None
        intervals = tuple(
            interval for interval, _label in _INTERVALS if interval in self._selected_intervals
        )
        return TurningPointRequest(
            self._watchlist_id,
            intervals,
            self._end_date,
            trade_side=self._trade_side,
        )

    @Slot(result=bool)
    def start(self) -> bool:
        request = self.build_request()
        if request is None or self._running or self._budget_task is not None:
            return False
        self._budget_request = request
        self._budget_snapshot = None
        self._failure_state = FailureState()
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
        self._status_text = "已取消本次筛选"
        self.changed.emit()

    def _launch_run(
        self,
        request: TurningPointRequest,
        *,
        force_yahoo: bool = False,
    ) -> None:
        self._fallback_gate = FallbackConsentGate(self)
        self._fallback_gate.changed.connect(self._on_fallback_changed)
        self._fallback_gate.settings_requested.connect(self.cancel)
        self._fallback_gate.resolved.connect(self._on_process_fallback_resolved)
        self._running = True
        self._force_yahoo_run = force_yahoo
        self._progress = 0.0
        self._active_stage = 0
        self._status_text = f"准备筛选 · {_trade_side_label(self._trade_side)}"
        self._last_status = ""
        self._failure_state = FailureState()
        self._progress_diagnostics.reset()
        self.changed.emit()
        program = self._turning_worker_program()
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
        self._run_operation_id = str(uuid.uuid4())
        self._application.registry.reserve(
            self._run_operation_id,
            str(uuid.uuid4()),
            "turning_point_process",
        )
        self._application.registry.begin_reserved(self._run_operation_id)
        process.start(str(program), self._turning_worker_arguments(request))

    def _turning_worker_program(self) -> Path | None:
        if self._application.paths.environment not in {
            RuntimeEnvironment.PRODUCTION,
            RuntimeEnvironment.DEVELOPMENT,
        }:
            return None
        candidate = Path(QCoreApplication.applicationDirPath()) / "stock-toolbox"
        return candidate if candidate.is_file() else None

    def _turning_worker_arguments(
        self,
        request: TurningPointRequest,
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
            "turning-point",
            "run-worker",
            "--watchlist-id",
            request.watchlist_id,
            "--end-date",
            request.requested_end_date.isoformat(),
            "--trade-side",
            ("left" if request.trade_side is TurningPointTradeSide.LEFT_CD else "right"),
        ]
        for interval in request.intervals:
            arguments.extend(("--interval", interval.value))
        if self._force_yahoo_run:
            arguments.append("--force-yahoo")
        return arguments

    @Slot(object, object)
    def _on_budget_finished(
        self,
        request: object,
        raw: object,
    ) -> None:
        self._budget_task = None
        if not isinstance(request, TurningPointRequest) or request != self._budget_request:
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
            self._status_text = f"任务较大 · {raw.cold_requests} 个外部请求等待确认"
            self.changed.emit()
            return
        self._launch_run(request)

    @Slot(result=bool)
    def cancel(self) -> bool:
        if self._run_process is not None:
            self._run_cancel_requested = True
            self._fallback_gate.cancel()
            self._run_process.terminate()
            self._status_text = "正在取消 · 不保存半成品"
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

    @Slot(result=bool)
    def generate_report(self) -> bool:
        if (
            not self._selected_run_id
            or not self._all_results
            or not self.ai_configured
            or self._report_task is not None
        ):
            return False
        task = _Task(
            self._application,
            run_id=self._selected_run_id,
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
        record = self._history_records.get(run_id)
        if record is None:
            return False
        payload = cast(dict[str, Any], record["payload"])
        self._apply_projection(project_turning_point_history(payload))
        reports = payload.get("ai_reports", [])
        self._report_text = (
            str(reports[-1].get("content", "")) if isinstance(reports, list) and reports else ""
        )
        self._report_error = ""
        self._selected_run_id = run_id
        self.changed.emit()
        return True

    @Slot()
    def refresh_display_timezone(self) -> None:
        """Reproject saved instants after a display-timezone change."""
        timezone_name = self._application.settings().display_timezone
        if timezone_name == self._display_timezone:
            return
        self._display_timezone = timezone_name
        selected_run_id = self._selected_run_id
        self._apply_history(list(self._history_records.values()))
        if selected_run_id and self.select_run(selected_run_id):
            return
        self.changed.emit()

    @Slot(result=bool)
    def prepare_new_run(self) -> bool:
        if self._running or self._budget_task is not None:
            return False
        self._selected_run_id = ""
        self._all_results = []
        self._unmatched_results = []
        self._failure_count = 0
        self._results_available = False
        self._last_status = ""
        self._failure_state = FailureState()
        self._progress = 0.0
        self._active_stage = -1
        self._report_text = ""
        self._report_error = ""
        self.changed.emit()
        return True

    @Slot(str, bool, result=bool)
    def set_pinned(self, run_id: str, pinned: bool) -> bool:
        try:
            self._application.pin_turning_point_history(run_id, pinned)
        except (KeyError, RuntimeError, ValueError):
            return False
        for row in self._history:
            if row["runId"] == run_id:
                row["pinned"] = pinned
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def delete_history(self, run_id: str) -> bool:
        try:
            self._application.delete_turning_point_history(run_id)
        except (KeyError, RuntimeError, ValueError):
            return False
        if self._selected_run_id == run_id:
            self._selected_run_id = ""
            self._all_results = []
            self._report_text = ""
            self._report_error = ""
            self._failure_count = 0
            self._unmatched_results = []
            self._results_available = False
        self._history = [row for row in self._history if row["runId"] != run_id]
        self._history_records.pop(run_id, None)
        self.changed.emit()
        return True

    @Slot(str, str, result=bool)
    def export_history(self, run_id: str, target: str) -> bool:
        local_target = QUrl(target).toLocalFile() if target.startswith("file:") else target
        try:
            content = self._application.export_turning_point_history(
                run_id,
                "csv",
            )
            Path(local_target).write_text(content, encoding="utf-8-sig")
        except (KeyError, OSError, RuntimeError, ValueError):
            return False
        return True

    @Slot(object)
    def _on_progress(self, raw: object) -> None:
        if not isinstance(raw, TurningPointProgress):
            return
        task_id = self._task.operation_id if self._task is not None else self._run_operation_id
        if task_id and self._progress_diagnostics.accept(
            raw.stage,
            raw.completed,
            raw.total,
            has_feedback=raw.feedback is not None,
        ):
            emit_progress(
                self._application.diagnostics,
                module="turning_point",
                task_id=task_id,
                stage=raw.stage,
                completed=raw.completed,
                total=raw.total,
                ticker=raw.current or "",
                feedback=raw.feedback,
            )
        stage = (
            "FETCH_CANDLES" if raw.stage in {"FETCH_INDICATORS", "FETCH_FALLBACK"} else raw.stage
        )
        if stage not in _STAGES:
            return
        stage_index = _STAGES.index(stage)
        self._active_stage = max(self._active_stage, stage_index)
        fraction = raw.completed / raw.total if raw.total else 0.0
        self._progress = max(
            self._progress,
            (stage_index + fraction) / len(_STAGES),
        )
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
            self._consume_run_process_line(raw_line)

    @Slot()
    def _drain_run_process_error(self) -> None:
        process = self._run_process
        if process is not None:
            process.readAllStandardError()

    def _consume_run_process_line(self, raw_line: bytes) -> None:
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
                TurningPointProgress(
                    str(payload.get("stage", "")),
                    int(payload.get("completed", 0)),
                    int(payload.get("total", 0)),
                    str(payload.get("current", "")) or None,
                    feedback,
                )
            )
        elif event_type == "result":
            self._run_process_result = payload
        elif event_type == "fallback":
            try:
                self._fallback_gate.present(
                    FallbackOffer(
                        str(payload.get("operation_kind", "turning_point")),
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
                "error_code": str(payload.get("code", "turning_point_worker_failed")),
            }

    @Slot(bool)
    def _on_process_fallback_resolved(self, accepted: bool) -> None:
        process = self._run_process
        if process is None:
            return
        process.write(b"accept\n" if accepted else b"decline\n")

    @Slot(int, object)
    def _on_run_process_finished(
        self,
        exit_code: int,
        _exit_status: object,
    ) -> None:
        process = self._run_process
        if process is None:
            return
        self._on_run_process_output()
        if self._run_process_buffer.strip():
            self._consume_run_process_line(self._run_process_buffer.strip())
        raw = self._run_process_result or {}
        canceled = self._run_cancel_requested
        self._run_process = None
        self._run_process_buffer = b""
        self._run_process_result = None
        self._run_cancel_requested = False
        process.deleteLater()
        status_text = "CANCELED" if canceled else str(raw.get("status", "FAILED"))
        try:
            status = TurningPointRunStatus(status_text)
        except ValueError:
            status = TurningPointRunStatus.FAILED
        error_code = (
            None
            if canceled
            else str(raw.get("error_code") or "")
            or (None if exit_code == 0 else "turning_point_worker_failed")
        )
        run_id = str(raw.get("run_id") or "")
        try:
            history: list[object] = list(self._application.list_turning_point_history(limit=10))
        except Exception:  # noqa: BLE001 - completed result remains usable
            history = []
        self._finish_process_run(
            status,
            run_id,
            error_code,
            history,
            reliability_from_payload(raw.get("reliability")),
        )

    def _finish_process_run(
        self,
        status: TurningPointRunStatus,
        run_id: str,
        error_code: str | None,
        history: list[object],
        reliability: AnalysisReliability | None = None,
    ) -> None:
        self._progress_updates.cancel()
        self._fallback_gate.cancel()
        operation_status = (
            OperationStatus.CANCELED
            if status is TurningPointRunStatus.CANCELED
            else OperationStatus.SUCCEEDED
            if status
            in {
                TurningPointRunStatus.READY,
                TurningPointRunStatus.PARTIAL,
            }
            else OperationStatus.FAILED
        )
        if self._run_operation_id:
            self._application.registry.try_complete(
                self._run_operation_id,
                operation_status,
                {"status": status.value, "error_code": error_code},
            )
        self._run_operation_id = ""
        self._running = False
        self._last_status = status.value
        self._failure_state = finish_outcome(
            self._failure_state,
            status.value,
            reliability,
            error_code,
        )
        self._status_text = {
            "READY": "筛选完成",
            "PARTIAL": "筛选完成 · 部分周期失败",
            "FAILED": f"筛选失败 · {error_code or 'unknown'}",
            "CANCELED": "已取消",
        }[status.value]
        selected_record: dict[str, Any] | None = next(
            (
                cast(dict[str, Any], item)
                for item in history
                if isinstance(item, dict) and str(item.get("run_id", "")) == run_id
            ),
            None,
        )
        if selected_record is not None:
            self._progress = 1.0
            self._active_stage = len(_STAGES) - 1
            self._selected_run_id = run_id
            self._report_text = ""
            self._report_error = ""
            self._apply_projection(project_turning_point_history(selected_record["payload"]))
        self._apply_history(history)
        result = TurningPointRunResult(status, error_code=error_code)
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
        self._finish_process_run(
            TurningPointRunStatus.FAILED,
            "",
            "turning_point_worker_start_failed",
            [],
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
            if isinstance(raw, dict):
                self._apply_support(raw)
                self._support_loaded = True
            self.changed.emit()
            return
        if kind == "calendar":
            self._calendar_task = None
            if isinstance(raw, date):
                self._end_date = raw
                self.changed.emit()
            return
        if kind == "report":
            self._report_task = None
            completed_run_id = ""
            report: object = raw
            if isinstance(raw, tuple) and len(raw) == 2:
                completed_run_id = str(raw[0])
                report = raw[1]
            if completed_run_id == self._selected_run_id:
                if isinstance(report, TurningPointReport):
                    self._report_text = report.content
                    self._report_error = ""
                else:
                    self._report_error = present_ai_report_failure(report).message
            self.changed.emit()
            self.report_finished.emit(report)
            return
        if (
            not isinstance(raw, tuple)
            or len(raw) != 2
            or not isinstance(raw[0], TurningPointRunResult)
        ):
            return
        result, history = raw
        self._task = None
        self._running = False
        self._last_status = result.status.value
        self._failure_state = finish_outcome(
            self._failure_state,
            self._last_status,
            result.reliability,
            result.error_code,
        )
        self._status_text = {
            "READY": "筛选完成",
            "PARTIAL": "筛选完成 · 部分周期失败",
            "FAILED": f"筛选失败 · {result.error_code or 'unknown'}",
            "CANCELED": "已取消",
        }.get(self._last_status, self._last_status)
        if result.run is not None:
            self._progress = 1.0
            self._active_stage = len(_STAGES) - 1
            self._selected_run_id = result.run.run_id
            self._report_text = ""
            self._report_error = ""
            self._apply_projection(
                project_turning_point_history(
                    {
                        "request": asdict(result.run.request),
                        "results": [asdict(item) for item in result.run.results],
                    }
                )
            )
        if isinstance(history, (list, tuple)):
            self._apply_history(list(history))
        self.changed.emit()
        self.finished.emit(result)

    def _apply_projection(self, projected: dict[str, Any]) -> None:
        self._all_results = [
            _result_row(
                cast(dict[str, Any], item),
                self._display_timezone,
            )
            for item in projected["rows"]
        ]
        self._unmatched_results = [
            _unmatched_row(cast(dict[str, Any], item)) for item in projected.get("unmatched", [])
        ]
        self._failure_count = int(projected["failure_count"])
        self._result_intervals = tuple(projected["selected_intervals"])
        self._result_interval = "attention"
        self._trade_side = TurningPointTradeSide(str(projected["trade_side"]))
        self._results_available = True

    def _apply_support(self, raw: dict[str, object]) -> None:
        raw_watchlists = raw.get("watchlists", [])
        watchlists = raw_watchlists if isinstance(raw_watchlists, (list, tuple)) else ()
        self._watchlists = [
            {
                "id": item.id,
                "name": item.display_name,
                "memberCount": len(item.memberships),
            }
            for item in watchlists
            if hasattr(item, "memberships")
        ]
        if self._watchlist_id not in {str(item["id"]) for item in self._watchlists}:
            self._watchlist_id = ""
        history = raw.get("history", [])
        if isinstance(history, (list, tuple)):
            self._apply_history(list(history))
        self._ai_configured = bool(raw.get("ai_configured", False))

    def _apply_history(self, records: list[object]) -> None:
        rows: list[dict[str, object]] = []
        self._history_records = {}
        for raw_record in records:
            if not isinstance(raw_record, dict):
                continue
            record = cast(dict[str, Any], raw_record)
            run_id = str(record["run_id"])
            self._history_records[run_id] = record
            payload = cast(dict[str, Any], record["payload"])
            projected = project_turning_point_history(payload)
            reports = payload.get("ai_reports", [])
            rows.append(
                {
                    "runId": run_id,
                    "name": str(record["display_name"]),
                    "completedAt": display_datetime(
                        record["completed_at"],
                        self._display_timezone,
                    ),
                    "pinned": bool(record["pinned"]),
                    "matchedCount": projected["matched_count"],
                    "totalCount": projected["total_count"],
                    "failureCount": projected["failure_count"],
                    "intervals": projected["selected_intervals"],
                    "tradeSide": projected["trade_side"],
                    "tradeSideLabel": projected["trade_side_label"],
                    "provider": str(payload.get("provider_display_name", "未记录")),
                    "requestedDateWindow": _window_text(payload.get("requested_date_window")),
                    "actualDateWindow": _window_text(payload.get("actual_date_window")),
                    "reportCount": (len(reports) if isinstance(reports, list) else 0),
                }
            )
        self._history = rows


def _window_text(value: object) -> str:
    if not isinstance(value, list) or len(value) != 2:
        return ""
    return f"{value[0]} — {value[1]}"


def _safe_filename_component(value: str) -> str:
    sanitized = re.sub(r"[^\w\u3400-\u9fff -]+", "-", value)
    sanitized = re.sub(r"[- ]{2,}", "-", sanitized).strip(" .-_")
    return sanitized or "股票池"


def _result_row(
    item: dict[str, Any],
    timezone_name: str,
) -> dict[str, object]:
    raw_risk_flags = item.get("risk_flags", [])
    risk_flags = raw_risk_flags if isinstance(raw_risk_flags, (list, tuple)) else ()
    period_results = [
        {
            "interval": period["interval"],
            "intervalLabel": period["interval_label"],
            "decision": period["decision"],
            "reason": period["reason"],
            "signalLabel": period["signal_label"],
            "signalAt": display_datetime(
                period["signal_at"],
                timezone_name,
            ),
            "crossedAt": display_datetime(
                period["crossed_at"],
                timezone_name,
            ),
            "enhancedAt": display_datetime(
                period.get("enhanced_at"),
                timezone_name,
            ),
            "lastPrice": period["last_price"],
            "volumeRatio": period["volume_ratio"],
            "qualityScore": period["quality_score"],
        }
        for period in item["period_results"]
    ]
    matched_period_chips = [
        {
            "interval": str(period["interval"]),
            "label": str(period["intervalLabel"]),
            "tip": _matched_period_tip(period),
        }
        for period in period_results
        if period["decision"] == "MATCHED"
    ]
    return {
        "symbol": str(item["symbol"]).removesuffix(".US"),
        "canonicalSymbol": str(item["symbol"]),
        "companyName": str(item["company_name"]),
        "classificationName": str(item["classification_name"]),
        "matchedIntervals": list(item["matched_intervals"]),
        "matchedPeriodLabels": list(item["matched_period_labels"]),
        "matchedPeriodChips": matched_period_chips,
        "signalLabels": list(item["signal_labels"]),
        "attentionScore": int(item["attention_score"]),
        "attentionLevel": str(item["attention_level"]),
        "conclusion": str(item["conclusion"]),
        "status": str(item["status"]),
        "marketValueUsd": item.get("market_value_usd"),
        "riskLabels": [_RISK_LABELS[str(flag)] for flag in risk_flags if str(flag) in _RISK_LABELS],
        "periodResults": period_results,
    }


def _matched_period_tip(period: dict[str, object]) -> str:
    parts = [f"CD 命中：{period['signalAt']}"]
    if period.get("enhancedAt"):
        parts.append(f"增强确认：{period['enhancedAt']}")
    if period.get("crossedAt"):
        parts.append(f"均线确认：{period['crossedAt']}")
    return "；".join(parts)


def _unmatched_row(item: dict[str, Any]) -> dict[str, object]:
    return {
        "symbol": str(item["symbol"]).removesuffix(".US"),
        "canonicalSymbol": str(item["symbol"]),
        "companyName": str(item["company_name"]),
        "classificationName": str(item["classification_name"]),
        "status": str(item["status"]),
        "periodResults": [
            {
                "interval": period["interval"],
                "intervalLabel": period["interval_label"],
                "decision": period["decision"],
                "reason": period["reason"],
                "reasonLabel": period["reason_label"],
            }
            for period in item["period_results"]
        ],
    }


def _trade_side_label(trade_side: TurningPointTradeSide) -> str:
    return "左侧 · CD" if trade_side is TurningPointTradeSide.LEFT_CD else "右侧 · 均线确认"
