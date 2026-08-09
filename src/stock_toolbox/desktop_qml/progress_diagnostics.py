"""One shared progress event for long-running desktop workflows."""

from dataclasses import dataclass, field

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticLogger,
    DiagnosticStatus,
)
from stock_toolbox.core.operations.run_feedback import RunFeedback


@dataclass(slots=True)
class ProgressEventSampler:
    """Keep actionable progress evidence without logging every work item."""

    max_updates_per_stage: int = 20
    _buckets: dict[tuple[str, int], int] = field(default_factory=dict)

    def accept(
        self,
        stage: str,
        completed: int,
        total: int,
        *,
        has_feedback: bool = False,
    ) -> bool:
        safe_total = max(0, total)
        safe_completed = max(0, completed)
        key = (stage, safe_total)
        if has_feedback or safe_total == 0:
            return True
        step = max(1, (safe_total + self.max_updates_per_stage - 1) // self.max_updates_per_stage)
        bucket = safe_completed // step
        if safe_completed in {0, safe_total}:
            self._buckets[key] = bucket
            return True
        if bucket <= self._buckets.get(key, -1):
            return False
        self._buckets[key] = bucket
        return True

    def reset(self) -> None:
        self._buckets.clear()


def emit_progress(
    diagnostics: DiagnosticLogger,
    *,
    module: str,
    task_id: str,
    stage: str,
    completed: int,
    total: int,
    ticker: str = "",
    feedback: RunFeedback | None = None,
) -> None:
    details: dict[str, int | float | str] = {
        "completed": max(0, completed),
        "total": max(0, total),
    }
    if feedback is not None:
        details.update(
            {
                "feedback_kind": feedback.kind.value,
                "failure_code": (
                    feedback.failure_code.value if feedback.failure_code is not None else ""
                ),
                "attempt": max(0, feedback.attempt),
                "max_attempts": max(0, feedback.max_attempts),
                "wait_seconds": max(0.0, feedback.wait_seconds),
                "active_concurrency": max(1, feedback.active_concurrency),
            }
        )
    try:
        diagnostics.emit(
            DiagnosticEvent(
                DiagnosticLevel.INFO,
                module,
                "progress",
                DiagnosticStatus.OBSERVED,
                task_id=task_id,
                stage=stage,
                ticker=ticker,
                details=details,
            )
        )
    except (OSError, TypeError, ValueError):
        return
