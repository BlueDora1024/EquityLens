from __future__ import annotations

from dataclasses import dataclass, field

from stock_toolbox.core.diagnostics.models import DiagnosticEvent
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback
from stock_toolbox.desktop_qml.progress_diagnostics import emit_progress


@dataclass
class _Logger:
    events: list[DiagnosticEvent] = field(default_factory=list)

    def emit(self, event: DiagnosticEvent) -> None:
        self.events.append(event)

    def flush(self, timeout_seconds: float = 1.0) -> bool:
        return True

    def close(self, timeout_seconds: float = 1.0) -> bool:
        return True


def test_progress_event_keeps_stage_count_and_ticker() -> None:
    logger = _Logger()

    emit_progress(
        logger,
        module="turning_point",
        task_id="run-1",
        stage="FETCH_CANDLES",
        completed=12,
        total=30,
        ticker="IREN.US",
    )

    event = logger.events[0]
    assert event.stage == "FETCH_CANDLES"
    assert event.ticker == "IREN.US"
    assert event.details == {"completed": 12, "total": 30}


def test_progress_event_records_sanitized_provider_throttling_feedback() -> None:
    logger = _Logger()

    emit_progress(
        logger,
        module="rs_strength",
        task_id="run-2",
        stage="FETCHING",
        completed=3,
        total=40,
        ticker="NVDA.US",
        feedback=RunFeedback(
            FeedbackKind.THROTTLED,
            FailureCode.RATE_LIMITED,
            "NVDA.US",
            "1d",
            attempt=1,
            max_attempts=2,
            wait_seconds=1.5,
            active_concurrency=1,
        ),
    )

    assert logger.events[0].details == {
        "completed": 3,
        "total": 40,
        "feedback_kind": "throttled",
        "failure_code": "rate_limited",
        "attempt": 1,
        "max_attempts": 2,
        "wait_seconds": 1.5,
        "active_concurrency": 1,
    }
