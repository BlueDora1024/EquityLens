from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from stock_toolbox.core.diagnostics.models import DiagnosticEvent
from stock_toolbox.core.operations.registry import (
    CancelResult,
    OperationExecutionContext,
    OperationRegistry,
    OperationStatus,
    ReserveResult,
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


def registry() -> OperationRegistry:
    return OperationRegistry(clock=lambda: NOW)


def cancel_after_barrier(
    barrier: threading.Barrier,
    results: list[object],
    operations: OperationRegistry,
    operation_id: str,
) -> None:
    barrier.wait()
    results.append(operations.cancel(operation_id))


def commit_after_barrier(
    barrier: threading.Barrier,
    results: list[object],
    context: OperationExecutionContext,
) -> None:
    barrier.wait()
    results.append(context.operation_control.try_enter_committing())


def run_and_capture(
    action: Callable[[], object],
    errors: list[Exception],
) -> None:
    try:
        action()
    except (AssertionError, RuntimeError) as error:
        errors.append(error)


def assert_serialized_notification_iteration(number: int) -> None:
    operations = registry()
    first_edge_started = threading.Event()
    release_first_edge = threading.Event()
    received: list[bool] = []
    errors: list[Exception] = []

    def listener(active: bool) -> None:
        if active:
            first_edge_started.set()
            assert release_first_edge.wait(timeout=2)
        received.append(active)

    operations.subscribe(listener)
    operation_id = f"ordered-{number}"
    reserve_thread = threading.Thread(
        target=run_and_capture,
        args=(
            lambda: operations.reserve(
                operation_id,
                f"ordered-key-{number}",
                "analysis",
            ),
            errors,
        ),
    )
    reserve_thread.start()
    assert first_edge_started.wait(timeout=2)

    cancel_thread = threading.Thread(
        target=run_and_capture,
        args=(lambda: operations.cancel(operation_id), errors),
    )
    cancel_thread.start()
    cancel_thread.join(timeout=2)
    assert not cancel_thread.is_alive()

    release_first_edge.set()
    reserve_thread.join(timeout=2)
    assert not reserve_thread.is_alive()
    assert errors == []
    assert received == [True, False]
    assert operations.has_active_operations() is False


def test_reserve_rejects_duplicate_operation_and_kind_key() -> None:
    operations = registry()

    first = operations.reserve("op-1", "same", "run")
    duplicate_id = operations.reserve("op-1", "other", "run")
    duplicate_key = operations.reserve("op-2", "same", "run")
    other_kind = operations.reserve("op-3", "same", "import")

    assert first.result is ReserveResult.RESERVED
    assert first.snapshot.status is OperationStatus.QUEUED
    assert first.snapshot.requested_at == NOW
    assert duplicate_id.result is ReserveResult.DUPLICATE_OPERATION_ID
    assert duplicate_key.result is ReserveResult.DUPLICATE_IDEMPOTENCY_KEY
    assert duplicate_key.existing_operation_id == "op-1"
    assert other_kind.result is ReserveResult.RESERVED


def test_reserve_and_cancel_emit_correlated_lifecycle_events() -> None:
    logger = _Logger()
    operations = OperationRegistry(clock=lambda: NOW, diagnostics=logger)

    operations.reserve("op-1", "same", "security_import")
    operations.cancel("op-1")

    assert [(event.action, event.task_id, event.status.value) for event in logger.events] == [
        ("reserved", "op-1", "observed"),
        ("cancelled", "op-1", "cancelled"),
    ]


def test_queued_cancel_wins_and_begin_returns_no_context() -> None:
    operations = registry()
    operations.reserve("op-1", "key", "run")

    assert operations.cancel("op-1") is CancelResult.ACCEPTED
    assert operations.begin_reserved("op-1") is None
    assert operations.status("op-1").status is OperationStatus.CANCELED  # type: ignore[union-attr]
    assert operations.cancel("missing") is CancelResult.NOT_FOUND
    assert operations.cancel("op-1") is CancelResult.TOO_LATE


def test_running_cancel_sets_the_same_control_token() -> None:
    operations = registry()
    operations.reserve("op-1", "key", "run")
    context = operations.begin_reserved("op-1")
    assert context is not None

    assert not context.operation_control.cancellation_requested()
    assert operations.cancel("op-1") is CancelResult.ACCEPTED
    assert context.operation_control.cancellation_requested()
    assert not context.operation_control.try_enter_committing()


def test_commit_gate_wins_and_blocks_late_cancel() -> None:
    operations = registry()
    operations.reserve("op-1", "key", "run")
    context = operations.begin_reserved("op-1")
    assert context is not None

    assert context.operation_control.try_enter_committing()
    assert operations.status("op-1").status is OperationStatus.COMMITTING  # type: ignore[union-attr]
    assert operations.cancel("op-1") is CancelResult.TOO_LATE
    winner = operations.try_complete(
        "op-1",
        OperationStatus.SUCCEEDED,
        {"run_status": "READY"},
    )

    assert winner.status is OperationStatus.SUCCEEDED
    assert winner.summary == {"run_status": "READY"}


def test_terminal_winner_is_never_overwritten() -> None:
    operations = registry()
    operations.reserve("op-1", "key", "run")
    assert operations.begin_reserved("op-1") is not None

    first = operations.try_complete(
        "op-1",
        OperationStatus.FAILED,
        {"error_code": "PROVIDER_TIMEOUT"},
    )
    second = operations.try_complete(
        "op-1",
        OperationStatus.SUCCEEDED,
        {"run_status": "READY"},
    )

    assert first == second
    assert second.status is OperationStatus.FAILED


def test_cancel_and_commit_gate_have_one_linearizable_winner() -> None:
    for number in range(100):
        operations = registry()
        operation_id = f"op-{number}"
        operations.reserve(operation_id, "key", "run")
        context = operations.begin_reserved(operation_id)
        assert context is not None
        barrier = threading.Barrier(3)
        results: list[object] = []

        threads = (
            threading.Thread(
                target=cancel_after_barrier,
                args=(barrier, results, operations, operation_id),
            ),
            threading.Thread(
                target=commit_after_barrier,
                args=(barrier, results, context),
            ),
        )
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        assert set(results) in (
            {CancelResult.ACCEPTED, False},
            {CancelResult.TOO_LATE, True},
        )


def test_notification_edges_are_serialized_in_mutation_order() -> None:
    for number in range(50):
        assert_serialized_notification_iteration(number)


def test_unsubscribed_snapshotted_listener_is_skipped_before_call() -> None:
    operations = registry()
    first_listener_started = threading.Event()
    release_first_listener = threading.Event()
    stale_calls: list[bool] = []
    live_calls: list[bool] = []
    errors: list[Exception] = []

    def blocking_listener(active: bool) -> None:
        first_listener_started.set()
        assert release_first_listener.wait(timeout=2)

    def stale_listener(active: bool) -> None:
        stale_calls.append(active)
        raise RuntimeError("deleted QObject")

    unsubscribe_blocking = operations.subscribe(blocking_listener)
    unsubscribe_stale = operations.subscribe(stale_listener)
    unsubscribe_live = operations.subscribe(live_calls.append)
    reserve_thread = threading.Thread(
        target=run_and_capture,
        args=(
            lambda: operations.reserve("stale", "stale-key", "analysis"),
            errors,
        ),
    )
    reserve_thread.start()
    assert first_listener_started.wait(timeout=2)

    unsubscribe_stale()
    release_first_listener.set()
    reserve_thread.join(timeout=2)

    assert not reserve_thread.is_alive()
    assert errors == []
    assert stale_calls == []
    assert live_calls == [True]

    unsubscribe_blocking()
    unsubscribe_live()
    assert not operations._listeners


def test_runtime_error_from_listener_does_not_block_live_subscribers() -> None:
    operations = registry()
    live_calls: list[bool] = []

    def deleted_qobject_listener(_active: bool) -> None:
        raise RuntimeError("Internal C++ object already deleted")

    operations.subscribe(deleted_qobject_listener)
    operations.subscribe(live_calls.append)

    operations.reserve("runtime-error", "runtime-error-key", "analysis")

    assert live_calls == [True]


def test_subscribe_with_snapshot_registers_and_reads_one_state() -> None:
    operations = registry()
    received: list[bool] = []

    unsubscribe, active = operations.subscribe_with_snapshot(received.append)
    operations.reserve("atomic-subscribe", "atomic-subscribe-key", "analysis")

    assert active is False
    assert received == [True]

    unsubscribe()
    assert not operations._listeners


def test_value_error_listener_is_quarantined_without_blocking_live_edge() -> None:
    operations = registry()
    live_calls: list[bool] = []

    def invalid_listener(_active: bool) -> None:
        raise ValueError("observer payload is invalid")

    operations.subscribe(invalid_listener)
    operations.subscribe(live_calls.append)

    operations.reserve("value-error", "value-error-key", "analysis")

    assert live_calls == [True]
    assert len(operations._listeners) == 1


class _ObserverAbort(BaseException):
    pass


def test_observer_base_exception_cannot_strand_queued_opposite_edge() -> None:
    operations = registry()
    listener_started = threading.Event()
    release_listener = threading.Event()
    live_calls: list[bool] = []
    errors: list[Exception] = []

    def aborting_listener(active: bool) -> None:
        if active:
            listener_started.set()
            assert release_listener.wait(timeout=2)
            raise _ObserverAbort()

    operations.subscribe(aborting_listener)
    operations.subscribe(live_calls.append)
    reserve_thread = threading.Thread(
        target=run_and_capture,
        args=(
            lambda: operations.reserve(
                "base-exception",
                "base-exception-key",
                "analysis",
            ),
            errors,
        ),
    )
    reserve_thread.start()
    assert listener_started.wait(timeout=2)

    cancel_thread = threading.Thread(
        target=run_and_capture,
        args=(lambda: operations.cancel("base-exception"), errors),
    )
    cancel_thread.start()
    cancel_thread.join(timeout=2)
    assert not cancel_thread.is_alive()
    release_listener.set()
    reserve_thread.join(timeout=2)

    assert not reserve_thread.is_alive()
    assert errors == []
    assert live_calls == [True, False]
    assert operations.has_active_operations() is False
    assert not operations._notification_queue
    assert operations._dispatching_notifications is False


def test_listener_can_unsubscribe_itself_reentrantly() -> None:
    operations = registry()
    calls: list[bool] = []
    unsubscribe: Callable[[], None]

    def listener(active: bool) -> None:
        calls.append(active)
        unsubscribe()

    unsubscribe = operations.subscribe(listener)
    operations.reserve("self-unsubscribe", "self-unsubscribe-key", "analysis")
    operations.cancel("self-unsubscribe")

    assert calls == [True]
    assert not operations._listeners


def test_closed_operation_admission_rejects_reserve_until_explicit_reset() -> None:
    operations = registry()

    assert operations.close_admission() is True
    rejected = operations.reserve("rejected", "rejected-key", "analysis")

    assert rejected.result is ReserveResult.ADMISSION_CLOSED
    assert rejected.snapshot is None
    assert operations.status("rejected") is None
    assert operations.close_admission() is False

    operations.reset_admission()
    assert (
        operations.reserve("accepted", "accepted-key", "analysis").result
        is ReserveResult.RESERVED
    )


def test_shutdown_closes_admission_and_captures_activity_atomically() -> None:
    operations = registry()

    assert operations.close_admission_and_has_active_operations() is False
    assert (
        operations.reserve("after-close", "after-close-key", "analysis").result
        is ReserveResult.ADMISSION_CLOSED
    )

    operations.reset_admission()
    operations.reserve("active", "active-key", "analysis")

    assert operations.close_admission_and_has_active_operations() is True
    assert (
        operations.reserve(
            "after-active-close",
            "after-active-close-key",
            "analysis",
        ).result
        is ReserveResult.ADMISSION_CLOSED
    )
