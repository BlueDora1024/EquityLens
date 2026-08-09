from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from stock_toolbox.core.diagnostics.models import DiagnosticEvent
from stock_toolbox.core.operations.executor import (
    ExecuteReservedOperation,
    OperationAdmissionClosedError,
    OperationCandidate,
)
from stock_toolbox.core.operations.registry import (
    OperationExecutionContext,
    OperationRegistry,
    OperationStatus,
)

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


@dataclass
class _Logger:
    events: list[DiagnosticEvent] = field(default_factory=list)

    def emit(self, event: DiagnosticEvent) -> None:
        self.events.append(event)

    def flush(self, timeout_seconds: float = 1.0) -> bool:
        return True

    def close(self, timeout_seconds: float = 1.0) -> bool:
        return True


def setup() -> tuple[OperationRegistry, ExecuteReservedOperation]:
    registry = OperationRegistry(clock=lambda: NOW)
    registry.reserve("op-1", "key", "run")
    return registry, ExecuteReservedOperation(registry)


def test_queued_cancellation_skips_handler_and_all_handler_io() -> None:
    registry, executor = setup()
    calls = 0

    def handler(_context: OperationExecutionContext) -> OperationCandidate:
        nonlocal calls
        calls += 1
        return OperationCandidate(OperationStatus.SUCCEEDED, {}, "payload")

    registry.cancel("op-1")
    result = executor.execute("op-1", handler)

    assert calls == 0
    assert not result.handler_started
    assert result.snapshot.status is OperationStatus.CANCELED
    assert result.payload is None


def test_successful_handler_is_started_once_and_completed_once() -> None:
    _registry, executor = setup()
    seen_contexts: list[OperationExecutionContext] = []

    def handler(context: OperationExecutionContext) -> OperationCandidate:
        seen_contexts.append(context)
        return OperationCandidate(
            OperationStatus.SUCCEEDED,
            {"run_status": "READY"},
            "result",
        )

    result = executor.execute("op-1", handler)
    second = executor.execute("op-1", handler)

    assert len(seen_contexts) == 1
    assert result.handler_started
    assert result.snapshot.status is OperationStatus.SUCCEEDED
    assert result.payload == "result"
    assert not second.handler_started
    assert second.snapshot == result.snapshot


def test_exception_becomes_sanitized_failed_terminal() -> None:
    _registry, executor = setup()

    def handler(_context: OperationExecutionContext) -> OperationCandidate:
        raise RuntimeError("secret backend detail")

    result = executor.execute("op-1", handler)

    assert result.snapshot.status is OperationStatus.FAILED
    assert result.snapshot.summary == {"error_code": "APPLICATION_INTERNAL"}
    assert "secret backend detail" not in repr(result.snapshot.summary)


def test_memory_error_becomes_stable_memory_exhausted_terminal() -> None:
    _registry, executor = setup()

    def handler(_context: OperationExecutionContext) -> OperationCandidate:
        raise MemoryError("allocator detail")

    result = executor.execute("op-1", handler)

    assert result.snapshot.status is OperationStatus.FAILED
    assert result.snapshot.summary == {"error_code": "memory_exhausted"}
    assert result.payload is None


def test_executor_logs_sanitized_terminal_event() -> None:
    logger = _Logger()
    registry = OperationRegistry(clock=lambda: NOW, diagnostics=logger)
    registry.reserve("op-1", "key", "rs_run")
    executor = ExecuteReservedOperation(registry)

    def handler(_context: OperationExecutionContext) -> OperationCandidate:
        raise RuntimeError("secret backend detail")

    result = executor.execute("op-1", handler)

    operation_events = [
        event
        for event in logger.events
        if event.module == "operations" and event.action == "rs_run"
    ]
    assert result.snapshot.status is OperationStatus.FAILED
    assert operation_events[-1].error_code == "APPLICATION_INTERNAL"
    assert "secret backend detail" not in repr(operation_events)


def test_cancel_winner_suppresses_late_success_payload() -> None:
    registry, executor = setup()

    def handler(_context: OperationExecutionContext) -> OperationCandidate:
        registry.cancel("op-1")
        return OperationCandidate(
            OperationStatus.SUCCEEDED,
            {"run_status": "READY"},
            "late",
        )

    result = executor.execute("op-1", handler)

    assert result.snapshot.status is OperationStatus.CANCELED
    assert result.payload is None


def test_missing_reservation_after_shutdown_is_controlled() -> None:
    registry = OperationRegistry(clock=lambda: NOW)
    registry.close_admission()
    executor = ExecuteReservedOperation(registry)

    with pytest.raises(
        OperationAdmissionClosedError,
        match="admission closed",
    ):
        executor.execute(
            "late-task",
            lambda _context: OperationCandidate(
                OperationStatus.SUCCEEDED,
                {},
            ),
        )


def test_missing_reservation_while_admission_is_open_is_programmer_error() -> None:
    registry = OperationRegistry(clock=lambda: NOW)
    executor = ExecuteReservedOperation(registry)

    with pytest.raises(KeyError, match="missing"):
        executor.execute(
            "missing",
            lambda _context: OperationCandidate(
                OperationStatus.SUCCEEDED,
                {},
            ),
        )
