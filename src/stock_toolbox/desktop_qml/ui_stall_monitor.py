"""Low-cost evidence when the Qt event loop returns late."""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QThreadPool, QTimer

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticLogger,
    DiagnosticStatus,
)
from stock_toolbox.core.diagnostics.timing import sample_process_memory


def classify_stall(delay_ms: int) -> DiagnosticLevel | None:
    if delay_ms >= 3_000:
        return DiagnosticLevel.ERROR
    if delay_ms >= 1_000:
        return DiagnosticLevel.WARNING
    return None


class UiStallMonitor(QObject):
    def __init__(
        self,
        diagnostics: DiagnosticLogger,
        *,
        current_page: Callable[[], str],
        active_operations: Callable[[], int],
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        interval_ms: int = 250,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._diagnostics = diagnostics
        self._current_page = current_page
        self._active_operations = active_operations
        self._monotonic_ns = monotonic_ns
        self._interval_ms = interval_ms
        self._expected_ns = 0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.observe_heartbeat)

    def start(self) -> None:
        self.reset_clock()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def reset_clock(self) -> None:
        self._expected_ns = (
            self._monotonic_ns() + self._interval_ms * 1_000_000
        )

    def observe_heartbeat(self) -> None:
        now_ns = self._monotonic_ns()
        delay_ms = max(0, (now_ns - self._expected_ns) // 1_000_000)
        self._expected_ns = now_ns + self._interval_ms * 1_000_000
        level = classify_stall(delay_ms)
        if level is None:
            return
        memory = sample_process_memory()
        try:
            self._diagnostics.emit(
                DiagnosticEvent(
                    level,
                    "ui",
                    "ui_stall",
                    DiagnosticStatus.OBSERVED,
                    duration_ms=delay_ms,
                    memory_rss_mb=memory.rss_mb,
                    memory_peak_mb=memory.peak_mb,
                    details={
                        "page": self._current_page(),
                        "active_operations": self._active_operations(),
                        "background_tasks": (
                            QThreadPool.globalInstance().activeThreadCount()
                        ),
                    },
                )
            )
        except (OSError, TypeError, ValueError):
            return
