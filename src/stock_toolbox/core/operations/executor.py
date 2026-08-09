"""Single begin/complete wrapper for every reserved application operation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from stock_toolbox.core.diagnostics.models import (
    DiagnosticStatus,
    DiagnosticValue,
)
from stock_toolbox.core.diagnostics.timing import DiagnosticSpan
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.core.operations.registry import (
    TERMINAL_STATUSES,
    OperationExecutionContext,
    OperationRegistry,
    OperationSnapshot,
    OperationStatus,
)


@dataclass(frozen=True, slots=True)
class OperationCandidate:
    terminal: OperationStatus
    summary: Mapping[str, object]
    payload: object | None = None

    def __post_init__(self) -> None:
        if self.terminal not in TERMINAL_STATUSES:
            raise ValueError("Operation candidate must be terminal")


@dataclass(frozen=True, slots=True)
class OperationExecutionResult:
    snapshot: OperationSnapshot
    payload: object | None
    handler_started: bool


class OperationAdmissionClosedError(RuntimeError):
    """A task reached execution after shutdown closed admission."""


class ExecuteReservedOperation:
    def __init__(self, registry: OperationRegistry) -> None:
        self._registry = registry

    def execute(
        self,
        operation_id: str,
        handler: Callable[[OperationExecutionContext], OperationCandidate],
    ) -> OperationExecutionResult:
        context = self._registry.begin_reserved(operation_id)
        if context is None:
            snapshot, admission_open = (
                self._registry.status_with_admission(operation_id)
            )
            if snapshot is None:
                if admission_open:
                    raise KeyError(operation_id)
                raise OperationAdmissionClosedError(
                    "operation admission closed before execution"
                )
            return OperationExecutionResult(snapshot, None, False)

        span = DiagnosticSpan(
            self._registry.diagnostics,
            module="operations",
            action=context.kind,
            task_id=context.operation_id,
        ).start()
        candidate = OperationCandidate(
            OperationStatus.FAILED,
            {"error_code": "APPLICATION_INTERNAL"},
        )
        try:
            candidate = handler(context)
        except MemoryError:
            candidate = OperationCandidate(
                OperationStatus.FAILED,
                {"error_code": FailureCode.MEMORY_EXHAUSTED.value},
            )
        except Exception:  # noqa: BLE001 - terminal boundary sanitizes handlers
            candidate = OperationCandidate(
                OperationStatus.FAILED,
                {"error_code": "APPLICATION_INTERNAL"},
            )
        finally:
            winner = self._registry.try_complete(
                operation_id,
                candidate.terminal,
                candidate.summary,
            )
            span.finish(
                _diagnostic_status(winner.status),
                error_code=str(winner.summary.get("error_code", "")),
                details=_diagnostic_summary(winner.summary),
            )
        payload = (
            candidate.payload
            if winner.status is candidate.terminal
            and winner.summary == candidate.summary
            else None
        )
        return OperationExecutionResult(winner, payload, True)


def _diagnostic_status(status: OperationStatus) -> DiagnosticStatus:
    return {
        OperationStatus.SUCCEEDED: DiagnosticStatus.SUCCEEDED,
        OperationStatus.FAILED: DiagnosticStatus.FAILED,
        OperationStatus.CANCELED: DiagnosticStatus.CANCELLED,
    }.get(status, DiagnosticStatus.OBSERVED)


def _diagnostic_summary(
    summary: Mapping[str, object],
) -> dict[str, DiagnosticValue]:
    allowed = {
        "code",
        "symbol",
        "updated",
        "failed",
        "skipped",
        "success",
        "total",
    }
    result: dict[str, DiagnosticValue] = {}
    for key in allowed:
        value = summary.get(key)
        if value is None or isinstance(value, (str, int, float, bool)):
            result[key] = value
    return result
