from __future__ import annotations

from dataclasses import dataclass, field

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticStatus,
)
from stock_toolbox.core.diagnostics.timing import (
    DiagnosticSpan,
    MemorySnapshot,
    sample_process_memory,
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


def test_span_uses_monotonic_duration_and_memory_snapshot() -> None:
    logger = _Logger()
    ticks = iter((1_000_000_000, 1_425_000_000))

    span = DiagnosticSpan(
        logger,
        module="operations",
        action="rs_run",
        task_id="run-1",
        monotonic_ns=lambda: next(ticks),
        memory=lambda: MemorySnapshot(312.5, 400.0),
    )
    span.start()
    span.finish(DiagnosticStatus.SUCCEEDED)

    assert [event.status for event in logger.events] == [
        DiagnosticStatus.STARTED,
        DiagnosticStatus.SUCCEEDED,
    ]
    assert logger.events[-1].duration_ms == 425
    assert logger.events[-1].memory_rss_mb == 312.5
    assert logger.events[-1].memory_peak_mb == 400.0


def test_span_finishes_only_once() -> None:
    logger = _Logger()
    ticks = iter((0, 10_000_000))
    span = DiagnosticSpan(
        logger,
        module="operations",
        action="run",
        monotonic_ns=lambda: next(ticks),
        memory=lambda: MemorySnapshot(None, None),
    )

    span.start()
    span.finish(DiagnosticStatus.FAILED, error_code="failed")
    span.finish(DiagnosticStatus.SUCCEEDED)

    assert len(logger.events) == 2
    assert logger.events[-1].status is DiagnosticStatus.FAILED


def test_process_memory_sampling_is_best_effort_and_non_negative() -> None:
    snapshot = sample_process_memory()

    assert snapshot.rss_mb is None or snapshot.rss_mb >= 0
    assert snapshot.peak_mb is None or snapshot.peak_mb >= 0
