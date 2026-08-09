"""Navigation state shared by the QML shell and every tool page."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot

from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.core.operations.registry import CancelResult, OperationStatus

_GLOBALS = (
    ("securities", "全局证券", "#"),
    ("classifications", "全局标签", "◇"),
    ("watchlists", "股票池", "▱"),
)
_TOOL_GLYPHS = {
    "rs_strength": "↗",
    "turning_point": "⌁",
    "extreme_deviation": "◎",
}
_TOOL_HELP = {
    "rs_strength": (
        "RS 是个股同期收益减去 SPY 或 QQQ 基准收益；"
        "大于 0 表示跑赢基准，小于 0 表示跑输。"
    ),
    "turning_point": (
        "左侧 CD 关注底背离首次成立，右侧等待均线确认；"
        "多周期同时命中时，潜在反转证据更可靠。"
    ),
    "extreme_deviation": (
        "负分偏买入观察、正分偏卖出观察；"
        "绝对值越大，当前价格偏离程度越明显。"
    ),
}
_TOOL_ORDER = ("rs_strength", "turning_point", "extreme_deviation")


class ShellBridge(QObject):
    changed = Signal()
    settings_requested = Signal()
    active_operation_changed = Signal(bool, arguments=["active"])
    registry_state_changed = Signal(bool, arguments=["active"])

    def __init__(
        self,
        application: StockToolboxApplication,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._navigation = self._build_navigation()
        self._known_pages = {
            str(item["pageId"])
            for item in self._navigation
            if item["kind"] in {"item", "tool", "subitem"}
        }
        self._current_page = "securities"
        self._product_tour_dismissed = (
            application.settings().product_tour_dismissed
        )
        self.registry_state_changed.connect(
            self._refresh_active_operation,
            Qt.ConnectionType.QueuedConnection,
        )
        unsubscribe, active = application.registry.subscribe_with_snapshot(
            self.registry_state_changed.emit,
        )
        self._has_active_operation = active
        self._unsubscribe_registry: Callable[[], None] | None = unsubscribe
        self.destroyed.connect(lambda *_args: unsubscribe())

    @Property(list, notify=changed)
    def navigation(self) -> list[dict[str, object]]:
        return [
            {
                **item,
                "selected": self._selected(item),
                "visible": self._visible(item),
            }
            for item in self._navigation
        ]

    @Property(str, notify=changed)
    def current_page(self) -> str:
        return self._current_page

    @Property(str, notify=changed)
    def page_title(self) -> str:
        for item in self._navigation:
            if item.get("pageId") == self._current_page:
                return str(item["label"])
        return ""

    @Property(bool, notify=active_operation_changed)
    def has_active_operation(self) -> bool:
        return self._application.registry.has_active_operations()

    @Property(bool, notify=changed)
    def product_tour_dismissed(self) -> bool:
        return self._product_tour_dismissed

    @Slot(result=bool)
    def dismiss_product_tour(self) -> bool:
        if self._product_tour_dismissed:
            return True
        dismissed = self._application.dismiss_product_tour()
        self._product_tour_dismissed = dismissed.product_tour_dismissed
        self.changed.emit()
        return self._product_tour_dismissed

    @Slot(str, result=bool)
    def navigate(self, page_id: str) -> bool:
        if page_id not in self._known_pages or page_id == self._current_page:
            return page_id == self._current_page
        self._current_page = page_id
        self.changed.emit()
        return True

    @Slot()
    def open_settings(self) -> None:
        self.settings_requested.emit()

    @Slot()
    def close(self) -> None:
        unsubscribe = self._unsubscribe_registry
        self._unsubscribe_registry = None
        if unsubscribe is not None:
            unsubscribe()

    @Slot()
    def close_operation_admission(self) -> None:
        self._application.registry.close_admission()

    @Slot(result=bool)
    def begin_operation_shutdown(self) -> bool:
        return (
            self._application.registry
            .close_admission_and_has_active_operations()
        )

    @Slot()
    def reset_operation_admission(self) -> None:
        self._application.registry.reset_admission()

    @Slot(result=bool)
    def reconcile_active_operation(self) -> bool:
        active = self._application.registry.has_active_operations()
        if active != self._has_active_operation:
            self._has_active_operation = active
            self.active_operation_changed.emit(active)
        return active

    @Slot(result=bool)
    def cancel_active_operation(self) -> bool:
        accepted = False
        for snapshot in self._application.registry.active_snapshots():
            if snapshot.status not in {
                OperationStatus.QUEUED,
                OperationStatus.RUNNING,
            }:
                continue
            accepted = (
                self._application.cancel_operation(snapshot.operation_id)
                is CancelResult.ACCEPTED
            ) or accepted
        return accepted

    @Slot(bool)
    def _refresh_active_operation(self, active: bool) -> None:
        if active == self._has_active_operation:
            return
        self._has_active_operation = active
        self.active_operation_changed.emit(active)

    def _selected(self, item: dict[str, object]) -> bool:
        page_id = str(item.get("pageId", ""))
        analysis_id = str(item.get("analysisId", ""))
        return (item["kind"] == "item" and page_id == self._current_page) or (
            item["kind"] == "tool"
            and self._current_page.startswith(f"{analysis_id}.")
        )

    def _visible(self, item: dict[str, object]) -> bool:
        return item["kind"] != "subitem" or self._current_page.startswith(
            f"{item.get('analysisId', '')}."
        )

    def _build_navigation(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = [
            {"kind": "heading", "label": "全局数据", "pageId": "", "glyph": ""}
        ]
        rows.extend(
            {
                "kind": "item",
                "label": label,
                "pageId": page_id,
                "glyph": glyph,
            }
            for page_id, label, glyph in _GLOBALS
        )
        rows.append(
            {"kind": "heading", "label": "分析工具", "pageId": "", "glyph": ""}
        )
        modules = sorted(
            self._application.analyses.list(),
            key=lambda module: (
                _tool_rank(module.descriptor.analysis_id),
                module.descriptor.display_name,
            ),
        )
        for module in modules:
            descriptor = module.descriptor
            rows.append(
                {
                    "kind": "tool",
                    "label": descriptor.display_name,
                    "pageId": f"{descriptor.analysis_id}.run",
                    "analysisId": descriptor.analysis_id,
                    "glyph": _TOOL_GLYPHS.get(descriptor.analysis_id, "·"),
                    "helpText": _TOOL_HELP.get(descriptor.analysis_id, ""),
                }
            )
            pages = (
                (("run", "运行"), ("results", "结果"))
                if descriptor.analysis_id == "extreme_deviation"
                else (("run", "运行"), ("history", "历史记录"))
            )
            for page, label in pages:
                rows.append(
                    {
                        "kind": "subitem",
                        "label": label,
                        "pageId": f"{descriptor.analysis_id}.{page}",
                        "analysisId": descriptor.analysis_id,
                        "glyph": "",
                    }
                )
        return rows


def _tool_rank(analysis_id: str) -> int:
    try:
        return _TOOL_ORDER.index(analysis_id)
    except ValueError:
        return len(_TOOL_ORDER)
