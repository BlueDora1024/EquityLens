"""Frozen RS results and the latest ten history records for QML."""

from __future__ import annotations

import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QObject,
    QRunnable,
    QThreadPool,
    QUrl,
    Signal,
    Slot,
)

from stock_toolbox.analyses.rs_strength.application.report import (
    RSStrengthReport,
    normalize_report_text,
)
from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.desktop_qml.failure_presentation import (
    present_ai_report_failure,
)
from stock_toolbox.desktop_qml.report_operation import (
    execute_report_operation,
    reserve_report_operation,
)
from stock_toolbox.desktop_qml.time_display import display_datetime
from stock_toolbox.infrastructure.persistence.errors import PersistenceError
from stock_toolbox.infrastructure.persistence.history_records import (
    HistorySnapshotRecord,
)
from stock_toolbox.runtime.environment import RuntimeEnvironment

_CLASSIFICATION_STATUS_LABELS = {
    "SUSTAINED_STRONG": "持续强势",
    "SUSTAINED_WEAK": "持续弱势",
    "RECENTLY_STRENGTHENING": "近期转强",
    "RECENTLY_WEAKENING": "近期转弱",
    "DIVERGENT": "周期分歧",
    "DIVERGENT_TIED_SPAN": "周期分歧",
    "INSUFFICIENT_DATA": "数据不足",
    "NOT_APPLICABLE": "暂不可评",
}


class RsHistoryBridge(QObject):
    changed = Signal()
    report_finished = Signal(object)

    def __init__(
        self,
        application: StockToolboxApplication,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._selected: HistorySnapshotRecord | None = None
        self._selected_range_id = ""
        self._stock_sort_descending = True
        self._report_task: _RSReportTask | None = None
        self._report_text = ""
        self._report_error = ""

    @Property(bool, notify=changed)
    def ai_configured(self) -> bool:
        return (
            self._application.paths.environment
            in {
                RuntimeEnvironment.SCENARIO,
                RuntimeEnvironment.INTEGRATION,
            }
            or self._application.settings().ai_configured
        )

    @Property(bool, notify=changed)
    def report_running(self) -> bool:
        return self._report_task is not None

    @Property(str, notify=changed)
    def report_text(self) -> str:
        return self._report_text

    @Property(str, notify=changed)
    def report_error(self) -> str:
        return self._report_error

    @Property(str, notify=changed)
    def export_default_name(self) -> str:
        return self._export_default_name()

    def _export_default_name(self) -> str:
        if self._selected is None:
            return "RS统计.zip"
        header = self._selected.header
        watchlist = _safe_filename_component(header.watchlist_name)
        completed = display_datetime(
            header.completed_at,
            self._application.settings().display_timezone,
        ).replace("-", "").replace(":", "").replace(" ", "-")
        return f"RS统计_{watchlist}_{completed}.zip"

    @Property(str, notify=changed)
    def export_default_url(self) -> str:
        target = Path.home() / "Documents" / self._export_default_name()
        return QUrl.fromLocalFile(str(target)).toString()

    @Property(list, notify=changed)
    def history(self) -> list[dict[str, object]]:
        return [
            {
                "runId": item.header.run_id,
                "name": _display_history_name(
                    item,
                    self._application.settings().display_timezone,
                ),
                "watchlist": item.header.watchlist_name,
                "completedAt": display_datetime(
                    item.header.completed_at,
                    self._application.settings().display_timezone,
                ),
                "status": item.header.status,
                "pinned": item.header.pinned,
                "memberCount": item.header.member_count,
            }
            for item in self._application.list_history(limit=10)
        ]

    @Property(dict, notify=changed)
    def selected_summary(self) -> dict[str, object]:
        if self._selected is None:
            return {}
        header = self._selected.header
        requested_window = header.snapshot_extensions.get(
            "requested_date_window"
        )
        actual_window = header.snapshot_extensions.get("actual_date_window")
        return {
            "runId": header.run_id,
            "name": _display_history_name(
                self._selected,
                self._application.settings().display_timezone,
            ),
            "watchlist": header.watchlist_name,
            "benchmark": header.benchmark_symbol.removesuffix(".US"),
            "status": header.status,
            "memberCount": header.member_count,
            "validCount": header.valid_member_count,
            "failedCount": header.failed_member_count,
            "note": header.note,
            "pinned": header.pinned,
            "provider": header.provider_display_name,
            "requestedDateWindow": _window_text(requested_window),
            "actualDateWindow": _window_text(actual_window),
        }

    @Property(list, notify=changed)
    def ranges(self) -> list[dict[str, object]]:
        if self._selected is None:
            return []
        return [
            {
                "id": item.run_range_id,
                "key": item.range_key,
                "label": item.label,
                "displayLabel": (
                    f"{item.label} · "
                    f"{item.actual_start_date.isoformat()}—"
                    f"{item.actual_end_date.isoformat()}"
                    if item.kind == "CUSTOM"
                    else item.label
                ),
                "kind": item.kind,
                "actualStartDate": item.actual_start_date.isoformat(),
                "actualEndDate": item.actual_end_date.isoformat(),
                "selected": item.run_range_id == self._selected_range_id,
            }
            for item in self._selected.ranges
        ]

    @Property(str, notify=changed)
    def selected_range_id(self) -> str:
        return self._selected_range_id

    @Property(bool, notify=changed)
    def stock_sort_descending(self) -> bool:
        return self._stock_sort_descending

    @Property(dict, notify=changed)
    def selected_range_summary(self) -> dict[str, object]:
        if self._selected is None:
            return {}
        selected = next(
            (
                item
                for item in self._selected.ranges
                if item.run_range_id == self._selected_range_id
            ),
            None,
        )
        if selected is None:
            return {}
        benchmark_return = (
            selected.benchmark_end_close / selected.benchmark_start_close
            - Decimal(1)
            if selected.benchmark_start_close
            else None
        )
        return {
            "id": selected.run_range_id,
            "label": selected.label,
            "benchmark": self._selected.header.benchmark_symbol.removesuffix(
                ".US"
            ),
            "benchmarkReturn": (
                float(benchmark_return)
                if benchmark_return is not None
                else None
            ),
        }

    @Property(list, notify=changed)
    def stock_results(self) -> list[dict[str, object]]:
        if self._selected is None:
            return []
        members = {item.id: item for item in self._selected.members}
        ranges = {item.run_range_id: item for item in self._selected.ranges}
        selected_results = [
            item
            for item in self._selected.stock_results
            if item.run_range_id == self._selected_range_id
        ]
        selected_results.sort(
            key=lambda item: (
                (
                    -item.rs_percentage_points
                    if self._stock_sort_descending
                    else item.rs_percentage_points
                ),
                members[item.run_member_id].canonical_symbol,
            )
        )
        return [
            {
                "symbol": members[
                    item.run_member_id
                ].canonical_symbol.removesuffix(".US"),
                "canonicalSymbol": members[
                    item.run_member_id
                ].canonical_symbol,
                "companyName": members[item.run_member_id].company_name,
                "classification": (
                    members[item.run_member_id].participating_classification_name
                ),
                "rangeId": item.run_range_id,
                "range": ranges[item.run_range_id].label,
                "rs": float(item.rs_percentage_points),
                "stockReturn": float(item.stock_return),
                "benchmarkReturn": float(item.benchmark_return),
            }
            for item in selected_results
        ]

    @Property(list, notify=changed)
    def classification_results(self) -> list[dict[str, object]]:
        if self._selected is None:
            return []
        return [
            {
                "name": item.classification_name,
                "score": (
                    float(item.composite_score)
                    if item.composite_score is not None
                    else None
                ),
                "scoreText": _display_score(item.composite_score),
                "status": item.multi_period_status,
                "statusLabel": _classification_status_label(
                    self._selected,
                    item.classification_snapshot_key,
                    item.multi_period_status,
                    item.composite_score,
                ),
                "statusHelpVisible": item.composite_score is not None,
                "statusExplanation": _status_explanation(
                    self._selected,
                    item.classification_snapshot_key,
                    item.multi_period_status,
                ),
                "reason": item.reason or "",
            }
            for item in self._selected.classification_results
        ]

    @Slot()
    def refresh(self) -> None:
        self.changed.emit()

    @Slot(str, result=bool)
    def select_run(self, run_id: str) -> bool:
        try:
            self._selected = self._application.get_history(run_id)
        except (KeyError, PersistenceError):
            return False
        self._selected_range_id = (
            self._selected.ranges[0].run_range_id
            if self._selected.ranges
            else ""
        )
        self._stock_sort_descending = True
        self._load_latest_report()
        self._report_error = ""
        self.changed.emit()
        return True

    @Slot(result=bool)
    def toggle_stock_sort(self) -> bool:
        if self._selected is None:
            return False
        self._stock_sort_descending = not self._stock_sort_descending
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def select_range(self, run_range_id: str) -> bool:
        if self._selected is None or not any(
            item.run_range_id == run_range_id
            for item in self._selected.ranges
        ):
            return False
        self._selected_range_id = run_range_id
        self.changed.emit()
        return True

    @Slot(result=bool)
    def generate_report(self) -> bool:
        if (
            self._selected is None
            or not self.ai_configured
            or self._report_task is not None
        ):
            return False
        task = _RSReportTask(
            self._application,
            self._selected.header.run_id,
        )
        if not reserve_report_operation(
            self._application,
            task.operation_id,
        ):
            return False
        self._report_task = task
        self._report_error = ""
        task.signals.finished.connect(self._on_report_finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(str, str, str, bool, result=bool)
    def update_history(
        self,
        run_id: str,
        display_name: str,
        note: str,
        pinned: bool,
    ) -> bool:
        try:
            self._application.update_history(
                run_id,
                display_name=display_name,
                note=note,
                pinned=pinned,
            )
        except (KeyError, RuntimeError, ValueError):
            return False
        self.select_run(run_id)
        return True

    @Slot(str, result=bool)
    def delete_history(self, run_id: str) -> bool:
        try:
            self._application.delete_history(run_id)
        except (KeyError, RuntimeError, ValueError):
            return False
        if self._selected is not None and self._selected.header.run_id == run_id:
            self._selected = None
            self._selected_range_id = ""
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
        suffix = {
            "csv": ".zip",
            "json": ".json",
            "markdown": ".md",
        }.get(format_name.strip().lower())
        if suffix is not None and not local_target.lower().endswith(suffix):
            local_target = f"{local_target}{suffix}"
        try:
            self._application.export_history(
                run_id,
                format_name,
                Path(local_target),
            )
        except (KeyError, OSError, RuntimeError, ValueError):
            return False
        return True

    @Slot(str, object)
    def _on_report_finished(
        self,
        completed_run_id: str,
        raw: object,
    ) -> None:
        self._report_task = None
        selected_run_id = (
            self._selected.header.run_id
            if self._selected is not None
            else ""
        )
        if completed_run_id == selected_run_id:
            if isinstance(raw, RSStrengthReport):
                try:
                    self._selected = self._application.get_history(
                        completed_run_id
                    )
                except (KeyError, PersistenceError):
                    self._report_error = "历史记录已不存在，报告未显示。"
                else:
                    self._load_latest_report()
                    self._report_error = ""
            else:
                self._report_error = present_ai_report_failure(raw).message
        self.changed.emit()
        self.report_finished.emit(raw)

    def _load_latest_report(self) -> None:
        self._report_text = ""
        if self._selected is None:
            return
        reports = self._selected.header.snapshot_extensions.get(
            "ai_reports",
            [],
        )
        if not isinstance(reports, list):
            return
        for report in reversed(reports):
            if isinstance(report, dict):
                content = report.get("content")
                if isinstance(content, str):
                    self._report_text = normalize_report_text(content)
                    return


def _display_score(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}"


def _safe_filename_component(value: str) -> str:
    sanitized = re.sub(r"[^\w\u3400-\u9fff -]+", "-", value)
    sanitized = re.sub(r"[- ]{2,}", "-", sanitized).strip(" .-_")
    return sanitized or "股票池"


def _display_rs(value: Decimal | None) -> str:
    if value is None:
        return "数据不足"
    return f"{value:+.2f}"


def _classification_status_label(
    snapshot: HistorySnapshotRecord,
    classification_key: str,
    status: str,
    composite_score: Decimal | None,
) -> str:
    if composite_score is not None:
        return _CLASSIFICATION_STATUS_LABELS[status]
    valid_counts = [
        item.valid_member_count
        for item in snapshot.classification_period_results
        if item.classification_snapshot_key == classification_key
    ]
    minimum_valid = min(valid_counts, default=0)
    if 0 < minimum_valid < 3:
        return f"样本不足 {minimum_valid}/3"
    return "样本不足"


def _status_explanation(
    snapshot: HistorySnapshotRecord,
    classification_key: str,
    status: str,
) -> str:
    periods = {
        item.run_range_id: item
        for item in snapshot.classification_period_results
        if item.classification_snapshot_key == classification_key
    }
    details = "、".join(
        f"{range_record.label} 中位 RS "
        f"{_display_rs(periods[range_record.run_range_id].median_rs)}"
        if range_record.run_range_id in periods
        else f"{range_record.label} 数据不足"
        for range_record in sorted(snapshot.ranges, key=lambda item: item.ordinal)
    )
    suffix = f"当前各周期：{details}。" if details else "当前没有周期数据。"
    explanations = {
        "SUSTAINED_STRONG": (
            "所有已选周期的分类中位 RS 都大于 0，说明多数周期均跑赢基准，"
            "因此判为持续强势。"
        ),
        "SUSTAINED_WEAK": (
            "所有已选周期的分类中位 RS 都小于 0，说明多数周期均跑输基准，"
            "因此判为持续弱势。"
        ),
        "RECENTLY_STRENGTHENING": (
            "最短周期的分类中位 RS 已转为正值，而最长周期仍为负值，"
            "因此判为近期转强。"
        ),
        "RECENTLY_WEAKENING": (
            "最短周期的分类中位 RS 已转为负值，而最长周期仍为正值，"
            "因此判为近期转弱。"
        ),
        "DIVERGENT": (
            "不同周期的分类中位 RS 方向不一致，且不满足单向转强或转弱条件，"
            "因此判为周期分歧。"
        ),
        "DIVERGENT_TIED_SPAN": (
            "存在跨度相同的最短或最长区间，无法唯一判断转强或转弱，"
            "因此归为周期分歧。"
        ),
        "INSUFFICIENT_DATA": (
            "至少一个周期缺少足够的有效个股结果，无法可靠判断跨周期状态。"
        ),
        "NOT_APPLICABLE": (
            "本次只选择了一个周期，无法进行跨周期状态判断；"
            "综合分仍可用于分类之间的横向比较。"
        ),
    }
    return f"{explanations.get(status, '当前状态依据各周期分类中位 RS 判定。')}{suffix}"


def _window_text(value: object) -> str:
    if not isinstance(value, list) or len(value) != 2:
        return ""
    return f"{value[0]} — {value[1]}"


def _display_history_name(
    snapshot: HistorySnapshotRecord,
    timezone_name: str,
) -> str:
    header = snapshot.header
    generated_name = (
        f"{header.original_run_name} "
        f"{header.completed_at:%Y-%m-%d %H:%M}"
    )
    if header.display_name != generated_name:
        return header.display_name
    return (
        f"{header.original_run_name} "
        f"{display_datetime(header.completed_at, timezone_name)}"
    )


class _RSReportTaskSignals(QObject):
    finished = Signal(str, object)


class _RSReportTask(QRunnable):
    def __init__(
        self,
        application: StockToolboxApplication,
        run_id: str,
    ) -> None:
        super().__init__()
        self.application = application
        self.run_id = run_id
        self.operation_id = str(uuid.uuid4())
        self.signals = _RSReportTaskSignals()

    @Slot()
    def run(self) -> None:
        result = execute_report_operation(
            self.application,
            self.operation_id,
            lambda control: self.application.generate_rs_strength_report(
                self.run_id,
                operation_control=control,
            ),
        )
        self.signals.finished.emit(self.run_id, result)
