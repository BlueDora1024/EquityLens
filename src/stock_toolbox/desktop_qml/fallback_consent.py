"""One worker-safe consent gate shared by all desktop analysis tools."""

from __future__ import annotations

from threading import Condition

from PySide6.QtCore import Property, QObject, Signal, Slot

from stock_toolbox.core.market_data.fallback import FallbackOffer

_OPERATION_LABELS = {
    "rs": "RS 强度",
    "turning_point": "拐点筛选",
    "extreme_deviation": "极值偏离",
}
_FAILURE_LABELS = {
    "timeout": "请求超时",
    "network_error": "网络异常",
    "service_unavailable": "服务暂不可用",
    "rate_limited": "请求频率受限",
    "quota_exhausted": "供应商额度耗尽",
}


class FallbackConsentGate(QObject):
    """Pause a worker, never the UI thread, until one decision is made."""

    changed = Signal()
    resolved = Signal(bool)
    settings_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._condition = Condition()
        self._offer: FallbackOffer | None = None
        self._decision: bool | None = None
        self._pending = False

    def request(self, offer: FallbackOffer) -> bool:
        with self._condition:
            if self._decision is not None:
                return self._decision
            self._offer = offer
            self._pending = True
        self.changed.emit()
        with self._condition:
            while self._decision is None:
                self._condition.wait()
            decision = self._decision
            self._pending = False
        self.changed.emit()
        return bool(decision)

    def present(self, offer: FallbackOffer) -> None:
        """Present an offer whose worker waits in another process."""
        with self._condition:
            if self._decision is not None:
                self.resolved.emit(bool(self._decision))
                return
            self._offer = offer
            self._pending = True
        self.changed.emit()

    @Slot()
    def accept(self) -> None:
        self._resolve(True)

    @Slot()
    def decline(self) -> None:
        self._resolve(False)

    @Slot()
    def open_network_settings(self) -> None:
        with self._condition:
            if self._decision is not None:
                return
        self.settings_requested.emit()
        self._resolve(False)

    def cancel(self) -> None:
        self._resolve(False)

    def _resolve(self, decision: bool) -> None:
        with self._condition:
            if self._decision is not None:
                return
            self._decision = decision
            self._pending = False
            self._condition.notify_all()
        self.changed.emit()
        self.resolved.emit(decision)

    @Property(bool, notify=changed)
    def pending(self) -> bool:
        with self._condition:
            return self._pending

    @Property(str, notify=changed)
    def operation_label(self) -> str:
        with self._condition:
            offer = self._offer
        return (
            _OPERATION_LABELS.get(offer.operation_kind, "分析任务")
            if offer is not None
            else "分析任务"
        )

    @Property(int, notify=changed)
    def failed_count(self) -> int:
        with self._condition:
            return len(self._offer.failed_symbols) if self._offer else 0

    @Property(int, notify=changed)
    def completed_count(self) -> int:
        with self._condition:
            return self._offer.completed if self._offer else 0

    @Property(int, notify=changed)
    def total_count(self) -> int:
        with self._condition:
            return self._offer.total if self._offer else 0

    @Property(str, notify=changed)
    def interval_text(self) -> str:
        with self._condition:
            intervals = self._offer.intervals if self._offer else ()
        return "、".join(intervals) if intervals else "日线"

    @Property(str, notify=changed)
    def failure_text(self) -> str:
        with self._condition:
            codes = self._offer.failure_codes if self._offer else ()
        labels = tuple(dict.fromkeys(_FAILURE_LABELS.get(code.value, code.value) for code in codes))
        return "、".join(labels) if labels else "行情服务异常"
