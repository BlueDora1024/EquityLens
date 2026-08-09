from __future__ import annotations

from dataclasses import dataclass, field

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
)
from stock_toolbox.desktop_qml.ui_stall_monitor import (
    UiStallMonitor,
    classify_stall,
)


@dataclass
class _Logger:
    events: list[DiagnosticEvent] = field(default_factory=list)

    def emit(self, event: DiagnosticEvent) -> None:
        self.events.append(event)

    def flush(self, timeout_seconds: float = 1.0) -> bool:
        return True

    def close(self, timeout_seconds: float = 1.0) -> bool:
        return True


def test_stall_thresholds_are_stable() -> None:
    assert classify_stall(999) is None
    assert classify_stall(1_000) is DiagnosticLevel.WARNING
    assert classify_stall(2_999) is DiagnosticLevel.WARNING
    assert classify_stall(3_000) is DiagnosticLevel.ERROR


def test_delayed_heartbeat_emits_page_operation_and_memory_evidence() -> None:
    logger = _Logger()
    ticks = iter((1_000_000_000, 2_450_000_000))
    monitor = UiStallMonitor(
        logger,
        current_page=lambda: "rs_strength.run",
        active_operations=lambda: 1,
        monotonic_ns=lambda: next(ticks),
        interval_ms=250,
    )
    monitor.reset_clock()

    monitor.observe_heartbeat()

    event = logger.events[-1]
    assert event.level is DiagnosticLevel.WARNING
    assert event.action == "ui_stall"
    assert event.duration_ms == 1_200
    assert event.details["page"] == "rs_strength.run"
    assert event.details["active_operations"] == 1
