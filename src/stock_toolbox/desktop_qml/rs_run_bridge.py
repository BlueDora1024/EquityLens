"""RS run state exposed to QML without presentation styling."""

from __future__ import annotations

import json
import uuid
from calendar import monthrange
from datetime import date
from pathlib import Path
from time import monotonic

from PySide6.QtCore import (
    Property,
    QCoreApplication,
    QObject,
    QProcess,
    QRunnable,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)

from stock_toolbox.analyses.resource_budget import AnalysisBudgetSnapshot
from stock_toolbox.analyses.rs_strength.application.models import (
    CustomRange,
    RunProgress,
    RunRequest,
    RunResult,
    RunStatus,
)
from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.core.market_data.date_policy import (
    display_today,
    maximum_historical_date,
    parse_iso_date,
    validate_historical_date,
)
from stock_toolbox.core.market_data.fallback import FallbackOffer
from stock_toolbox.core.master_data.models import WatchlistDTO
from stock_toolbox.core.operations.executor import OperationAdmissionClosedError
from stock_toolbox.core.operations.failure_policy import (
    FailureCode,
)
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
)
from stock_toolbox.desktop_qml.fallback_consent import FallbackConsentGate
from stock_toolbox.desktop_qml.progress_diagnostics import emit_progress
from stock_toolbox.desktop_qml.progress_state import monotonic_stage_progress
from stock_toolbox.runtime.environment import RuntimeEnvironment

_RANGES = (
    ("1W", "近 1 周"),
    ("2W", "近 2 周"),
    ("1M", "近 1 个月"),
    ("3M", "近 3 个月"),
    ("6M", "近 6 个月"),
    ("1Y", "近 1 年"),
)
_BENCHMARKS = {"SPY.US", "QQQ.US"}
_STAGES = ("PREFLIGHT", "FETCHING", "VALIDATING", "CALCULATING", "AGGREGATING", "SAVING")
_STAGE_PRESENTATION_INTERVAL_MS = 250
_STAGE_PRESENTATION = {
    "PREFLIGHT": ("运行预检", "正在确认股票池、范围和数据源"),
    "FETCHING": ("获取收盘结果", "正在按当前供应商能力并发获取行情"),
    "VALIDATING": ("数据校验", "正在对齐交易日并检查数据完整性"),
    "CALCULATING": ("个股 RS", "正在计算股票相对强度"),
    "AGGREGATING": ("分类聚合", "正在汇总板块强度与覆盖率"),
    "SAVING": ("保存结果", "正在冻结本次结果与历史快照"),
}
_ERROR_PRESENTATION = {
    "BENCHMARK_FETCH_FAILED": "基准行情获取失败，请检查授权或稍后重试",
    "PREFLIGHT_FAILED": "运行条件发生变化，请重新检查配置",
    "NO_VALID_RESULTS": "没有可用结果，请检查股票行情完整性",
    "HISTORY_SAVE_FAILED": "结果保存失败，本次运行未写入历史",
    "HISTORICAL_DATE_REQUIRED": "结束日期必须早于今天",
}


class _RunSignals(QObject):
    progress = Signal(object)
    finished = Signal(object)


class _SupportSignals(QObject):
    finished = Signal(object)


class _WatchlistTask(QRunnable):
    def __init__(self, application: StockToolboxApplication) -> None:
        super().__init__()
        self.application = application
        self.signals = _SupportSignals()

    @Slot()
    def run(self) -> None:
        try:
            result: object = self.application.master_data.list_watchlists()
        except RuntimeError as error:
            result = error
        self.signals.finished.emit(result)


class _CalendarTask(QRunnable):
    def __init__(self, application: StockToolboxApplication) -> None:
        super().__init__()
        self.application = application
        self.signals = _SupportSignals()

    @Slot()
    def run(self) -> None:
        try:
            result: object = self.application.latest_completed_trading_day()
        except RuntimeError as error:
            result = error
        self.signals.finished.emit(result)


class _RunTask(QRunnable):
    def __init__(
        self,
        application: StockToolboxApplication,
        request: RunRequest,
        fallback_gate: FallbackConsentGate | None = None,
        force_yahoo: bool = False,
    ) -> None:
        super().__init__()
        self.application = application
        self.request = request
        self.fallback_gate = fallback_gate
        self.force_yahoo = force_yahoo
        self.operation_id = str(uuid.uuid4())
        self.signals = _RunSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self.fallback_gate is None:
                result: object = self.application.run(
                    self.request,
                    operation_id=self.operation_id,
                    progress=self.signals.progress.emit,
                    force_yahoo=self.force_yahoo,
                )
            else:
                result = self.application.run(
                    self.request,
                    operation_id=self.operation_id,
                    progress=self.signals.progress.emit,
                    fallback_consent=self.fallback_gate.request,
                    force_yahoo=self.force_yahoo,
                )
        except OperationAdmissionClosedError as error:
            result = error
        self.signals.finished.emit(result)


class RsRunBridge(QObject):
    changed = Signal()
    finished = Signal(object)
    watchlists_finished = Signal()
    calendar_finished = Signal()

    def __init__(
        self,
        application: StockToolboxApplication,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._watchlist_id = ""
        self._watchlist_cache: dict[str, WatchlistDTO] = {}
        self._watchlists_loaded = False
        self._watchlist_task: _WatchlistTask | None = None
        self._benchmark = "SPY.US"
        self._end_date: date | None = None
        self._calendar_task: _CalendarTask | None = None
        self._selected_ranges = {key for key, _label in _RANGES}
        self._custom_enabled = False
        self._custom_start: date | None = None
        self._custom_end: date | None = None
        self._budget_task: AnalysisBudgetTask | None = None
        self._budget_request: RunRequest | None = None
        self._budget_snapshot: AnalysisBudgetSnapshot | None = None
        self._task: _RunTask | None = None
        self._run_process: QProcess | None = None
        self._run_process_buffer = b""
        self._run_process_result: dict[str, object] | None = None
        self._run_operation_id = ""
        self._run_cancel_requested = False
        self._running = False
        self._progress = 0.0
        self._active_stage = -1
        self._status_text = ""
        self._last_status = ""
        self._stage_label = "等待开始"
        self._stage_detail = "完成运行前检查后即可开始"
        self._current_symbol = ""
        self._completed_count = 0
        self._total_count = 0
        self._succeeded_count = 0
        self._failed_count = 0
        self._started_monotonic: float | None = None
        self._elapsed_seconds = 0
        self._canceling = False
        self._terminal_detail = ""
        self._terminal_failure_code = ""
        self._failure_state = FailureState()
        self._pending_progress: list[RunProgress] = []
        self._pending_result: RunResult | None = None
        self._fallback_gate = FallbackConsentGate(self)
        self._fallback_gate.changed.connect(self._on_fallback_changed)
        self._fallback_gate.settings_requested.connect(self.cancel)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(250)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._presentation_timer = QTimer(self)
        self._presentation_timer.setSingleShot(True)
        self._presentation_timer.timeout.connect(self._advance_stage_presentation)

    @Property(list, notify=changed)
    def watchlists(self) -> list[dict[str, object]]:
        return [
            {
                "id": item.id,
                "name": item.display_name,
                "memberCount": len(item.memberships),
            }
            for item in sorted(
                self._watchlist_cache.values(),
                key=lambda row: row.display_name.casefold(),
            )
        ]

    @Property(QObject, notify=changed)
    def fallback_gate(self) -> QObject:
        return self._fallback_gate

    @Property(str, notify=changed)
    def provider_status(self) -> str:
        identity = self._application.provider_identity()
        state = "已连接" if identity.configured else "待配置"
        return f"{identity.display_name} · {state}"

    @Slot()
    def refresh_provider_status(self) -> None:
        self.changed.emit()

    @Property(bool, notify=changed)
    def watchlists_loading(self) -> bool:
        return self._watchlist_task is not None

    @Property(bool, notify=changed)
    def watchlists_loaded(self) -> bool:
        return self._watchlists_loaded

    @Property(str, notify=changed)
    def selected_watchlist_id(self) -> str:
        return self._watchlist_id

    @Property(str, notify=changed)
    def watchlist_name(self) -> str:
        watchlist = self._watchlist()
        return watchlist.display_name if watchlist is not None else "请选择股票池"

    @Property(int, notify=changed)
    def member_count(self) -> int:
        return self._member_count()

    @Property(str, notify=changed)
    def benchmark(self) -> str:
        return self._benchmark

    @Property(str, notify=changed)
    def benchmark_label(self) -> str:
        return {
            "SPY.US": "SPY · S&P 500",
            "QQQ.US": "QQQ · Nasdaq 100",
        }.get(self._benchmark, self._benchmark)

    @Property(str, notify=changed)
    def end_date_text(self) -> str:
        if self._end_date is None:
            return "请选择结束日期"
        return f"{self._end_date.year} 年 {self._end_date.month} 月 {self._end_date.day} 日"

    @Property(str, notify=changed)
    def end_date(self) -> str:
        return self._end_date.isoformat() if self._end_date is not None else ""

    @Property(str, notify=changed)
    def maximum_historical_date(self) -> str:
        return maximum_historical_date(self._application.settings().display_timezone).isoformat()

    @Property(bool, notify=changed)
    def calendar_loading(self) -> bool:
        return self._calendar_task is not None

    @Property(list, notify=changed)
    def ranges(self) -> list[dict[str, object]]:
        return [
            {
                "key": key,
                "label": label,
                "selected": key in self._selected_ranges,
            }
            for key, label in _RANGES
        ]

    @Property(int, notify=changed)
    def range_count(self) -> int:
        return self._range_count()

    @Property(bool, notify=changed)
    def custom_enabled(self) -> bool:
        return self._custom_enabled

    @Property(str, notify=changed)
    def custom_start(self) -> str:
        return self._custom_start.isoformat() if self._custom_start is not None else ""

    @Property(str, notify=changed)
    def custom_end(self) -> str:
        return self._custom_end.isoformat() if self._custom_end is not None else ""

    @Property(int, notify=changed)
    def preflight_passed(self) -> int:
        return self._passed_count()

    @Property(bool, notify=changed)
    def preflight_ready(self) -> bool:
        return self._passed_count() == 6

    @Property(bool, notify=changed)
    def can_start(self) -> bool:
        return self._passed_count() == 6 and not self._running and self._budget_task is None

    @Property(str, notify=changed)
    def preflight_text(self) -> str:
        return (
            f"运行前检查 {self._passed_count()}/6 · "
            f"{self._member_count()} 位成员 · {self._range_count()} 个范围"
        )

    @Property(bool, notify=changed)
    def running(self) -> bool:
        return self._running or self._budget_task is not None

    @Property(bool, notify=changed)
    def budget_loading(self) -> bool:
        return self._budget_task is not None

    @Property(int, notify=changed)
    def estimated_total(self) -> int:
        return self._budget_snapshot.total_tasks if self._budget_snapshot is not None else 0

    @Property(int, notify=changed)
    def estimated_cache_hits(self) -> int:
        return self._budget_snapshot.cache_hits if self._budget_snapshot is not None else 0

    @Property(int, notify=changed)
    def estimated_cold_requests(self) -> int:
        return self._budget_snapshot.cold_requests if self._budget_snapshot is not None else 0

    @Property(str, notify=changed)
    def data_path(self) -> str:
        return (
            self._budget_snapshot.data_path if self._budget_snapshot is not None else "等待资源预检"
        )

    @Property(str, notify=changed)
    def quota_notice(self) -> str:
        return self._budget_snapshot.quota_notice if self._budget_snapshot is not None else ""

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
        groups = group_failures(self._failure_state.failures)
        if groups or not self._terminal_failure_code or self._failed_count <= 0:
            return groups
        return [
            {
                "code": self._terminal_failure_code,
                "count": self._failed_count,
                "symbols": [],
                "intervals": [],
            }
        ]

    @Property(str, notify=changed)
    def stage_label(self) -> str:
        return self._stage_label

    @Property(str, notify=changed)
    def stage_detail(self) -> str:
        return self._stage_detail

    @Property(str, notify=changed)
    def current_symbol(self) -> str:
        return self._current_symbol

    @Property(int, notify=changed)
    def completed_count(self) -> int:
        return self._completed_count

    @Property(int, notify=changed)
    def total_count(self) -> int:
        return self._total_count

    @Property(int, notify=changed)
    def succeeded_count(self) -> int:
        return self._succeeded_count

    @Property(int, notify=changed)
    def failed_count(self) -> int:
        return self._failed_count

    @Property(str, notify=changed)
    def elapsed_text(self) -> str:
        minutes, seconds = divmod(self._elapsed_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    @Property(bool, notify=changed)
    def canceling(self) -> bool:
        return self._canceling

    @Property(bool, notify=changed)
    def cancel_available(self) -> bool:
        return self._running and (
            self._task is not None or self._run_process is not None
        )

    @Property(bool, notify=changed)
    def terminal_visible(self) -> bool:
        return self._last_status in {"FAILED", "CANCELED"}

    @Property(str, notify=changed)
    def terminal_kind(self) -> str:
        return self._last_status if self.terminal_visible else ""

    @Property(str, notify=changed)
    def terminal_detail(self) -> str:
        return self._terminal_detail

    @Slot(str)
    def select_watchlist(self, watchlist_id: str) -> None:
        self._watchlist_id = watchlist_id
        if watchlist_id and watchlist_id not in self._watchlist_cache:
            try:
                watchlist = self._application.master_data.get_watchlist(watchlist_id)
            except (KeyError, RuntimeError, ValueError):
                self._watchlist_id = ""
            else:
                self._watchlist_cache[watchlist.id] = watchlist
        self.changed.emit()

    @Slot(result=bool)
    def load_watchlists(self) -> bool:
        if self._watchlist_task is not None:
            return False
        task = _WatchlistTask(self._application)
        self._watchlist_task = task
        task.signals.finished.connect(self._on_watchlists_finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(str)
    def set_benchmark(self, symbol: str) -> None:
        self._benchmark = symbol
        self.changed.emit()

    @Slot(str)
    def set_end_date(self, raw: str) -> None:
        candidate = parse_iso_date(raw)
        today = display_today(self._application.settings().display_timezone)
        self._end_date = (
            candidate
            if candidate is not None and validate_historical_date(candidate, today)
            else None
        )
        if self._custom_enabled and self._end_date is not None:
            if self._custom_end is None:
                self._custom_end = self._end_date
            if self._custom_start is None:
                self._custom_start = _months_before(self._end_date, 3)
        self.changed.emit()

    @Slot(result=bool)
    def refresh_latest_trading_day(self) -> bool:
        if self._calendar_task is not None:
            return False
        task = _CalendarTask(self._application)
        self._calendar_task = task
        task.signals.finished.connect(self._on_calendar_finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(str, bool)
    def toggle_range(self, key: str, selected: bool) -> None:
        if selected:
            self._selected_ranges.add(key)
        else:
            self._selected_ranges.discard(key)
        self.changed.emit()

    @Slot(bool, str, str)
    def set_custom_range(
        self,
        enabled: bool,
        start_raw: str,
        end_raw: str,
    ) -> None:
        self._custom_enabled = enabled
        self.set_custom_dates(start_raw, end_raw)

    @Slot(bool)
    def set_custom_enabled(self, enabled: bool) -> None:
        self._custom_enabled = enabled
        if enabled and self._end_date is not None:
            self._custom_end = self._custom_end or self._end_date
            self._custom_start = self._custom_start or _months_before(
                self._end_date,
                3,
            )
        self.changed.emit()

    @Slot(str, str)
    def set_custom_dates(self, start_raw: str, end_raw: str) -> None:
        today = display_today(self._application.settings().display_timezone)
        start = parse_iso_date(start_raw)
        end = parse_iso_date(end_raw)
        self._custom_start = (
            start if start is not None and validate_historical_date(start, today) else None
        )
        self._custom_end = end if end is not None and validate_historical_date(end, today) else None
        self.changed.emit()

    @Slot(result=bool)
    def start(self) -> bool:
        request = self.build_request()
        if request is None or self._running or self._budget_task is not None:
            return False
        self._budget_request = request
        self._budget_snapshot = None
        self._terminal_failure_code = ""
        self._failure_state = FailureState()
        self._last_status = ""
        self._progress = 0.0
        self._active_stage = -1
        self._current_symbol = ""
        self._completed_count = 0
        self._total_count = 0
        self._succeeded_count = 0
        self._failed_count = 0
        self._terminal_detail = ""
        task = AnalysisBudgetTask(self._application, request)
        self._budget_task = task
        self._status_text = "正在检查资源预算"
        self._stage_label = "资源预检"
        self._stage_detail = "只读取本机缓存，不请求行情"
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
        self._status_text = "已取消本次运行"
        self._stage_label = "等待开始"
        self._stage_detail = "可调整股票池或范围后重新运行"
        self.changed.emit()

    def _launch_run(self, request: RunRequest, *, force_yahoo: bool = False) -> None:
        self._clear_stage_presentation()
        self._fallback_gate = FallbackConsentGate(self)
        self._fallback_gate.changed.connect(self._on_fallback_changed)
        self._fallback_gate.settings_requested.connect(self.cancel)
        self._fallback_gate.resolved.connect(self._on_process_fallback_resolved)
        self._running = True
        self._progress = 0.0
        self._active_stage = 0
        self._status_text = "准备运行"
        self._last_status = ""
        self._stage_label = "运行预检"
        self._stage_detail = (
            "已选择 Yahoo 备用行情 · 从第一步完整计算"
            if force_yahoo
            else "正在确认股票池、范围和数据源"
        )
        self._current_symbol = ""
        self._completed_count = 0
        self._total_count = 1
        self._succeeded_count = 0
        self._failed_count = 0
        self._started_monotonic = monotonic()
        self._elapsed_seconds = 0
        self._canceling = False
        self._terminal_detail = ""
        self._terminal_failure_code = ""
        self._failure_state = FailureState()
        self._elapsed_timer.start()
        self.changed.emit()
        program = self._worker_program()
        if program is None:
            task = _RunTask(
                self._application,
                request,
                (None if force_yahoo else self._fallback_gate),
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
            "rs_strength_process",
        )
        self._application.registry.begin_reserved(self._run_operation_id)
        process.start(
            str(program),
            self._worker_arguments(request, force_yahoo=force_yahoo),
        )

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
        request: RunRequest,
        *,
        force_yahoo: bool = False,
    ) -> list[str]:
        environment = self._application.paths.environment
        environment_name = (
            "production"
            if environment is RuntimeEnvironment.PRODUCTION
            else "dev"
        )
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
            "rs-strength",
            "run-worker",
            "--watchlist-id",
            request.watchlist_id,
            "--benchmark",
            request.benchmark_symbol,
            "--end-date",
            request.requested_end_date.isoformat(),
        ]
        for preset_range in request.preset_ranges:
            arguments.extend(("--range", preset_range))
        if request.custom_range is not None:
            arguments.extend(
                (
                    "--custom-start",
                    request.custom_range.start_date.isoformat(),
                    "--custom-end",
                    request.custom_range.end_date.isoformat(),
                )
            )
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
        if not isinstance(request, RunRequest) or request != self._budget_request:
            self.changed.emit()
            return
        if not isinstance(raw, AnalysisBudgetSnapshot):
            self._budget_request = None
            self._budget_snapshot = None
            self._last_status = "FAILED"
            self._status_text = "资源预检失败"
            self._stage_label = "资源预检失败"
            self._stage_detail = "无法读取本机缓存，请稍后重试"
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
            self._stage_label = "资源预检失败"
            self._stage_detail = code
            self._failure_state = finish_outcome(
                FailureState(),
                "FAILED",
                None,
                code,
            )
            self.changed.emit()
            return
        if raw.requires_confirmation:
            self._status_text = "本次任务较大 · 等待确认"
            self._stage_label = "资源预算确认"
            self._stage_detail = (
                f"预计 {raw.cold_requests} 个外部请求，"
                f"当前数据源完整命中 {raw.cache_hits} 个"
            )
            self.changed.emit()
            return
        self._launch_run(request)

    @Slot(result=bool)
    def cancel(self) -> bool:
        if self._run_process is not None:
            self._fallback_gate.cancel()
            self._run_cancel_requested = True
            self._run_process.terminate()
            self._status_text = "正在取消 · 等待独立行情进程退出"
            self._stage_label = "正在取消"
            self._stage_detail = "正在停止当前行情请求，本次运行不会保存半成品"
            self._canceling = True
            self.changed.emit()
            return True
        if self._task is None:
            return False
        self._fallback_gate.cancel()
        accepted = (
            self._application.cancel_operation(self._task.operation_id) == CancelResult.ACCEPTED
        )
        if accepted:
            self._status_text = "正在取消 · 等待当前安全检查点"
            self._stage_label = "正在取消"
            self._stage_detail = "等待当前请求或计算块到达安全检查点"
            self._canceling = True
            self.changed.emit()
        return accepted

    @Slot()
    def _on_fallback_changed(self) -> None:
        if self._fallback_gate.pending:
            provider = self._application.provider_identity().display_name
            self._status_text = f"{provider} 暂不可用 · 等待备用数据确认"
            self._stage_label = "等待处理"
            self._stage_detail = "若改用 Yahoo，将丢弃临时结果并从第一步重新计算"
        self.changed.emit()

    def build_request(self) -> RunRequest | None:
        if self._passed_count() != 6 or self._end_date is None:
            return None
        custom_range = None
        if self._custom_enabled:
            if self._custom_start is None or self._custom_end is None:
                return None
            custom_range = CustomRange(self._custom_start, self._custom_end)
        return RunRequest(
            self._watchlist_id,
            self._benchmark,
            self._end_date,
            tuple(key for key, _label in _RANGES if key in self._selected_ranges),
            custom_range,
        )

    @Slot(object)
    def _on_progress(self, raw: object) -> None:
        if not isinstance(raw, RunProgress) or raw.stage not in _STAGES:
            return
        operation_id = (
            self._task.operation_id
            if self._task is not None
            else self._run_operation_id
        )
        if operation_id:
            emit_progress(
                self._application.diagnostics,
                module="rs_strength",
                task_id=operation_id,
                stage=raw.stage,
                completed=raw.completed,
                total=raw.total,
                ticker=raw.current or "",
                feedback=raw.feedback,
            )
        if not self._running:
            self._apply_progress(raw)
            return
        stage_index = _STAGES.index(raw.stage)
        if self._active_stage < 0:
            self._apply_progress(raw)
            self._presentation_timer.start(_STAGE_PRESENTATION_INTERVAL_MS)
            return
        if stage_index == self._active_stage and not self._pending_progress:
            self._apply_progress(raw)
            return
        for index, pending in enumerate(self._pending_progress):
            if pending.stage == raw.stage:
                self._pending_progress[index] = raw
                break
        else:
            self._pending_progress.append(raw)
        if not self._presentation_timer.isActive():
            self._advance_stage_presentation()

    def _apply_progress(self, raw: RunProgress) -> None:
        self._active_stage = _STAGES.index(raw.stage)
        self._progress = monotonic_stage_progress(
            self._progress,
            stage_index=self._active_stage,
            stage_count=len(_STAGES),
            completed=raw.completed,
            total=raw.total,
        )
        self._stage_label, self._stage_detail = _STAGE_PRESENTATION[raw.stage]
        self._completed_count = raw.completed
        self._total_count = raw.total
        self._current_symbol = raw.current.removesuffix(".US") if raw.current else ""
        if raw.succeeded is not None:
            self._succeeded_count = raw.succeeded
        if raw.failed is not None:
            self._failed_count = raw.failed
        if raw.feedback is not None:
            self._failure_state = advance_feedback(
                self._failure_state,
                raw.feedback,
            )
        else:
            self._failure_state = advance_running(self._failure_state)
        current = f" · {self._current_symbol}" if self._current_symbol else ""
        self._status_text = f"{self._stage_label} · {raw.completed}/{raw.total}{current}"
        self.changed.emit()

    @Slot()
    def _on_run_process_output(self) -> None:
        process = self._run_process
        if process is None:
            return
        self._run_process_buffer += process.readAllStandardOutput().data()
        while b"\n" in self._run_process_buffer:
            raw_line, self._run_process_buffer = self._run_process_buffer.split(
                b"\n", 1
            )
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
            self._on_progress(_process_progress(payload))
        elif event_type == "result":
            self._run_process_result = payload
        elif event_type == "fallback":
            try:
                self._fallback_gate.present(
                    FallbackOffer(
                        str(payload.get("operation_kind", "rs_strength")),
                        tuple(
                            str(item)
                            for item in payload.get("failed_symbols", [])
                        ),
                        tuple(str(item) for item in payload.get("intervals", [])),
                        tuple(
                            FailureCode(str(item))
                            for item in payload.get("failure_codes", [])
                        ),
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
                "error_code": str(
                    payload.get("code", "rs_strength_worker_failed")
                ),
            }

    @Slot(bool)
    def _on_process_fallback_resolved(self, accepted: bool) -> None:
        process = self._run_process
        if process is not None:
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
        payload = self._run_process_result or {}
        canceled = self._run_cancel_requested
        self._run_process = None
        self._run_process_buffer = b""
        self._run_process_result = None
        self._run_cancel_requested = False
        process.deleteLater()
        status_text = "CANCELED" if canceled else str(
            payload.get("status", "FAILED")
        )
        try:
            status = RunStatus(status_text)
        except ValueError:
            status = RunStatus.FAILED
        error_code = (
            None
            if canceled
            else str(payload.get("error_code") or "")
            or (None if exit_code == 0 else "rs_strength_worker_failed")
        )
        reliability = reliability_from_payload(payload.get("reliability"))
        operation_status = (
            OperationStatus.CANCELED
            if status is RunStatus.CANCELED
            else OperationStatus.SUCCEEDED
            if status in {RunStatus.READY, RunStatus.PARTIAL}
            else OperationStatus.FAILED
        )
        if self._run_operation_id:
            self._application.registry.try_complete(
                self._run_operation_id,
                operation_status,
                {"status": status.value, "error_code": error_code},
            )
        self._run_operation_id = ""
        self._fallback_gate.cancel()
        self._on_finished(
            RunResult(
                status,
                run_id=str(payload.get("run_id") or "") or None,
                error_code=error_code,
                reliability=reliability,
            )
        )

    @Slot(object)
    def _on_run_process_error(self, _error: object) -> None:
        process = self._run_process
        if (
            process is None
            or process.state() is not QProcess.ProcessState.NotRunning
        ):
            return
        self._run_process = None
        process.deleteLater()
        if self._run_operation_id:
            self._application.registry.try_complete(
                self._run_operation_id,
                OperationStatus.FAILED,
                {"error_code": "rs_strength_worker_start_failed"},
            )
        self._run_operation_id = ""
        self._on_finished(
            RunResult(
                RunStatus.FAILED,
                error_code="rs_strength_worker_start_failed",
            )
        )

    @Slot(object)
    def _on_finished(self, raw: object) -> None:
        if isinstance(raw, OperationAdmissionClosedError):
            self._clear_stage_presentation()
            self._task = None
            self._running = False
            self._canceling = False
            self._elapsed_timer.stop()
            self.changed.emit()
            return
        if not isinstance(raw, RunResult):
            return
        if (
            raw.status in {RunStatus.READY, RunStatus.PARTIAL}
            and self._running
            and (self._presentation_timer.isActive() or bool(self._pending_progress))
        ):
            self._pending_result = raw
            self._task = None
            self._elapsed_timer.stop()
            self._update_elapsed()
            self.changed.emit()
            return
        self._clear_stage_presentation()
        self._finalize_finished(raw)

    def _advance_stage_presentation(self) -> None:
        if self._pending_progress:
            self._apply_progress(self._pending_progress.pop(0))
            self._presentation_timer.start(_STAGE_PRESENTATION_INTERVAL_MS)
            return
        if self._pending_result is not None:
            result = self._pending_result
            self._pending_result = None
            self._finalize_finished(result)

    def _clear_stage_presentation(self) -> None:
        self._presentation_timer.stop()
        self._pending_progress.clear()
        self._pending_result = None

    def _finalize_finished(self, raw: RunResult) -> None:
        self._running = False
        self._elapsed_timer.stop()
        self._update_elapsed()
        self._last_status = raw.status.value
        self._terminal_failure_code = _stable_terminal_failure_code(raw)
        self._failure_state = finish_outcome(
            self._failure_state,
            self._last_status,
            raw.reliability,
            raw.error_code,
        )
        if self._last_status in {"READY", "PARTIAL"}:
            self._progress = 1.0
            self._active_stage = len(_STAGES) - 1
        self._status_text = {
            "READY": "运行完成",
            "PARTIAL": "运行完成 · 部分数据缺失",
            "FAILED": "运行失败",
            "CANCELED": "已取消",
        }.get(self._last_status, self._last_status)
        self._stage_label = self._status_text
        self._stage_detail = (
            "结果已经保存到历史记录"
            if self._last_status in {"READY", "PARTIAL"}
            else "本次运行没有生成新的历史记录"
        )
        self._terminal_detail = _ERROR_PRESENTATION.get(
            raw.error_code or "",
            "本次运行已停止，可以检查配置后重新运行"
            if self._last_status == "FAILED"
            else "已在安全检查点停止，本次运行未保存",
        )
        self._canceling = False
        self._task = None
        self.changed.emit()
        self.finished.emit(raw)

    @Slot()
    def _update_elapsed(self) -> None:
        if self._started_monotonic is None:
            return
        elapsed = max(0, int(monotonic() - self._started_monotonic))
        if elapsed != self._elapsed_seconds:
            self._elapsed_seconds = elapsed
            self.changed.emit()

    @Slot(object)
    def _on_watchlists_finished(self, raw: object) -> None:
        self._watchlist_task = None
        if isinstance(raw, tuple) and all(isinstance(item, WatchlistDTO) for item in raw):
            self._watchlist_cache = {item.id: item for item in raw}
            self._watchlists_loaded = True
            if self._watchlist_id and self._watchlist_id not in self._watchlist_cache:
                self._watchlist_id = ""
        self.changed.emit()
        self.watchlists_finished.emit()

    @Slot(object)
    def _on_calendar_finished(self, raw: object) -> None:
        self._calendar_task = None
        today = display_today(self._application.settings().display_timezone)
        if isinstance(raw, date) and validate_historical_date(raw, today):
            self._end_date = raw
            if self._custom_enabled:
                self._custom_end = self._custom_end or raw
                self._custom_start = self._custom_start or _months_before(
                    raw,
                    3,
                )
        self.changed.emit()
        self.calendar_finished.emit()

    def _watchlist(self) -> WatchlistDTO | None:
        if not self._watchlist_id:
            return None
        cached = self._watchlist_cache.get(self._watchlist_id)
        if cached is not None:
            return cached
        try:
            watchlist = self._application.master_data.get_watchlist(self._watchlist_id)
        except (KeyError, RuntimeError, ValueError):
            return None
        self._watchlist_cache[watchlist.id] = watchlist
        return watchlist

    def _member_count(self) -> int:
        watchlist = self._watchlist()
        return len(watchlist.memberships) if watchlist is not None else 0

    def _range_count(self) -> int:
        return len(self._selected_ranges) + int(self._custom_enabled)

    def _passed_count(self) -> int:
        return sum(self._checks())

    def _checks(self) -> tuple[bool, ...]:
        watchlist = self._watchlist()
        memberships = watchlist.memberships if watchlist is not None else ()
        classifications_valid = bool(memberships) and all(
            member.participating_classification_id and member.participating_classification_name
            for member in memberships
        )
        custom_dates_valid = not self._custom_enabled or (
            self._custom_start is not None
            and self._custom_end is not None
            and self._custom_start <= self._custom_end
        )
        settings = self._application.settings()
        return (
            settings.provider_mode == "virtual" or settings.provider_configured,
            watchlist is not None,
            1 <= len(memberships) <= 600,
            classifications_valid,
            self._benchmark in _BENCHMARKS,
            self._range_count() > 0 and self._end_date is not None and custom_dates_valid,
        )


def _months_before(value: date, months: int) -> date:
    ordinal = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(ordinal, 12)
    month = month_index + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _process_progress(payload: dict[str, object]) -> RunProgress:
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
    return RunProgress(
        str(payload.get("stage", "")),
        _payload_int(payload.get("completed")),
        _payload_int(payload.get("total")),
        str(payload.get("current", "")) or None,
        (
            _payload_int(payload["succeeded"])
            if payload.get("succeeded") is not None
            else None
        ),
        (
            _payload_int(payload["failed"])
            if payload.get("failed") is not None
            else None
        ),
        feedback,
    )


def _stable_terminal_failure_code(raw: RunResult) -> str:
    candidates = (
        raw.error_code,
        raw.reliability.primary_failure_code if raw.reliability is not None else None,
    )
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return FailureCode(candidate.strip().lower()).value
        except ValueError:
            continue
    return FailureCode.INTERNAL.value if raw.status is RunStatus.FAILED else ""


def _payload_int(raw: object) -> int:
    return int(str(raw)) if raw is not None else 0
