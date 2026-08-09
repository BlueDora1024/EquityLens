"""Linearizable process-local lifecycle for cancellable operations."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticLogger,
    DiagnosticStatus,
    NullDiagnosticLogger,
)


class OperationStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMMITTING = "COMMITTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


TERMINAL_STATUSES = frozenset(
    {
        OperationStatus.SUCCEEDED,
        OperationStatus.FAILED,
        OperationStatus.CANCELED,
    }
)


class ReserveResult(StrEnum):
    RESERVED = "RESERVED"
    DUPLICATE_OPERATION_ID = "DUPLICATE_OPERATION_ID"
    DUPLICATE_IDEMPOTENCY_KEY = "DUPLICATE_IDEMPOTENCY_KEY"
    ADMISSION_CLOSED = "ADMISSION_CLOSED"


class CancelResult(StrEnum):
    ACCEPTED = "ACCEPTED"
    TOO_LATE = "TOO_LATE"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    operation_id: str
    idempotency_key: str
    kind: str
    requested_at: datetime
    status: OperationStatus
    summary: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ReserveDecision:
    result: ReserveResult
    snapshot: OperationSnapshot | None
    existing_operation_id: str | None = None


@dataclass(slots=True)
class _OperationEntry:
    operation_id: str
    idempotency_key: str
    kind: str
    requested_at: datetime
    status: OperationStatus = OperationStatus.QUEUED
    summary: dict[str, object] = field(default_factory=dict)
    canceled: threading.Event = field(default_factory=threading.Event)
    execution_active: bool = False


@dataclass(slots=True)
class _ListenerSubscription:
    listener: Callable[[bool], None]
    active: bool = True
    dispatch_lock: threading.RLock = field(default_factory=threading.RLock)


class OperationControl:
    def __init__(
        self,
        registry: OperationRegistry,
        operation_id: str,
        canceled: threading.Event,
    ) -> None:
        self._registry = registry
        self._operation_id = operation_id
        self._canceled = canceled

    def cancellation_requested(self) -> bool:
        return self._canceled.is_set()

    def wait_for_cancellation(self, timeout: float) -> bool:
        """Wait for cancellation without blocking past the requested timeout."""
        return self._canceled.wait(timeout)

    def try_enter_committing(self) -> bool:
        return self._registry._try_enter_committing(self._operation_id)


@dataclass(frozen=True, slots=True)
class OperationExecutionContext:
    operation_id: str
    idempotency_key: str
    kind: str
    requested_at: datetime
    operation_control: OperationControl


class OperationRegistry:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        diagnostics: DiagnosticLogger | None = None,
    ) -> None:
        self._clock = clock
        self._diagnostics = diagnostics or NullDiagnosticLogger()
        self._lock = threading.RLock()
        self._entries: dict[str, _OperationEntry] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._listeners: dict[int, _ListenerSubscription] = {}
        self._next_listener_token = 0
        self._notification_queue: deque[bool] = deque()
        self._dispatching_notifications = False
        self._last_enqueued_active = False
        self._admission_open = True

    @property
    def diagnostics(self) -> DiagnosticLogger:
        return self._diagnostics

    def subscribe(
        self,
        listener: Callable[[bool], None],
    ) -> Callable[[], None]:
        """Notify a shell observer after lifecycle state changes."""
        unsubscribe, _active = self.subscribe_with_snapshot(listener)
        return unsubscribe

    def subscribe_with_snapshot(
        self,
        listener: Callable[[bool], None],
    ) -> tuple[Callable[[], None], bool]:
        """Register an observer and capture current activity atomically."""
        with self._lock:
            token = self._next_listener_token
            self._next_listener_token += 1
            subscription = _ListenerSubscription(listener)
            self._listeners[token] = subscription
            active = self._has_active_operations_locked()

        def unsubscribe() -> None:
            with self._lock:
                removed = self._listeners.pop(token, None)
            if removed is None:
                return
            with subscription.dispatch_lock:
                subscription.active = False

        return unsubscribe, active

    def reserve(
        self,
        operation_id: str,
        idempotency_key: str,
        kind: str,
    ) -> ReserveDecision:
        if not operation_id or not idempotency_key or not kind:
            raise ValueError("Operation reservation fields must be non-empty")
        with self._lock:
            if not self._admission_open:
                return ReserveDecision(ReserveResult.ADMISSION_CLOSED, None)
            by_id = self._entries.get(operation_id)
            if by_id is not None:
                return ReserveDecision(
                    ReserveResult.DUPLICATE_OPERATION_ID,
                    self._snapshot(by_id),
                    operation_id,
                )
            identity = (kind, idempotency_key)
            existing_id = self._idempotency.get(identity)
            if existing_id is not None:
                existing = self._entries[existing_id]
                return ReserveDecision(
                    ReserveResult.DUPLICATE_IDEMPOTENCY_KEY,
                    self._snapshot(existing),
                    existing_id,
                )
            entry = _OperationEntry(
                operation_id,
                idempotency_key,
                kind,
                self._clock(),
            )
            self._entries[operation_id] = entry
            self._idempotency[identity] = operation_id
            decision = ReserveDecision(
                ReserveResult.RESERVED,
                self._snapshot(entry),
            )
            should_drain = self._enqueue_notification_locked()
        if should_drain:
            self._drain_notifications()
        self._emit(
            DiagnosticEvent(
                DiagnosticLevel.INFO,
                "operations",
                "reserved",
                DiagnosticStatus.OBSERVED,
                task_id=operation_id,
                details={"kind": kind},
            )
        )
        return decision

    def close_admission(self) -> bool:
        """Atomically reject new operation reservations during shutdown."""
        with self._lock:
            changed = self._admission_open
            self._admission_open = False
            return changed

    def close_admission_and_has_active_operations(self) -> bool:
        """Start shutdown and capture activity under the admission lock."""
        with self._lock:
            self._admission_open = False
            return self._has_active_operations_locked()

    def reset_admission(self) -> None:
        """Explicitly reopen admission for a reused test/application lifecycle."""
        with self._lock:
            self._admission_open = True

    def begin_reserved(
        self,
        operation_id: str,
    ) -> OperationExecutionContext | None:
        with self._lock:
            entry = self._entries.get(operation_id)
            if entry is None or entry.status is not OperationStatus.QUEUED:
                return None
            entry.status = OperationStatus.RUNNING
            entry.execution_active = True
            context = OperationExecutionContext(
                operation_id=entry.operation_id,
                idempotency_key=entry.idempotency_key,
                kind=entry.kind,
                requested_at=entry.requested_at,
                operation_control=OperationControl(
                    self,
                    entry.operation_id,
                    entry.canceled,
                ),
            )
            should_drain = self._enqueue_notification_locked()
        if should_drain:
            self._drain_notifications()
        return context

    def cancel(self, operation_id: str) -> CancelResult:
        with self._lock:
            entry = self._entries.get(operation_id)
            if entry is None:
                return CancelResult.NOT_FOUND
            if entry.status not in {
                OperationStatus.QUEUED,
                OperationStatus.RUNNING,
            }:
                return CancelResult.TOO_LATE
            entry.canceled.set()
            entry.status = OperationStatus.CANCELED
            entry.summary = {}
            should_drain = self._enqueue_notification_locked()
        if should_drain:
            self._drain_notifications()
        self._emit(
            DiagnosticEvent(
                DiagnosticLevel.INFO,
                "operations",
                "cancelled",
                DiagnosticStatus.CANCELLED,
                task_id=operation_id,
                details={"kind": entry.kind},
            )
        )
        return CancelResult.ACCEPTED

    def status(self, operation_id: str) -> OperationSnapshot | None:
        with self._lock:
            entry = self._entries.get(operation_id)
            return None if entry is None else self._snapshot(entry)

    def status_with_admission(
        self,
        operation_id: str,
    ) -> tuple[OperationSnapshot | None, bool]:
        """Capture reservation presence and admission state atomically."""
        with self._lock:
            entry = self._entries.get(operation_id)
            snapshot = None if entry is None else self._snapshot(entry)
            return snapshot, self._admission_open

    def non_terminal_snapshots(self) -> tuple[OperationSnapshot, ...]:
        with self._lock:
            return tuple(
                self._snapshot(entry)
                for entry in sorted(
                    self._entries.values(),
                    key=lambda item: item.operation_id,
                )
                if entry.status not in TERMINAL_STATUSES
            )

    def active_snapshots(self) -> tuple[OperationSnapshot, ...]:
        """Include a canceled worker until its execution boundary returns."""
        with self._lock:
            return tuple(
                self._snapshot(entry)
                for entry in sorted(
                    self._entries.values(),
                    key=lambda item: item.operation_id,
                )
                if (
                    entry.status not in TERMINAL_STATUSES
                    or entry.execution_active
                )
            )

    def has_active_operations(self) -> bool:
        with self._lock:
            return self._has_active_operations_locked()

    def try_complete(
        self,
        operation_id: str,
        proposed_terminal: OperationStatus,
        summary: Mapping[str, object],
    ) -> OperationSnapshot:
        if proposed_terminal not in TERMINAL_STATUSES:
            raise ValueError("Completion status must be terminal")
        with self._lock:
            entry = self._entries.get(operation_id)
            if entry is None:
                raise KeyError(operation_id)
            if entry.status in TERMINAL_STATUSES:
                changed = entry.execution_active
                entry.execution_active = False
                snapshot = self._snapshot(entry)
            elif (
                entry.status is OperationStatus.COMMITTING
                and proposed_terminal is OperationStatus.CANCELED
            ):
                raise ValueError("Committing operation cannot be canceled")
            else:
                changed = True
                entry.status = proposed_terminal
                entry.summary = dict(summary)
                entry.execution_active = False
                if proposed_terminal is OperationStatus.CANCELED:
                    entry.canceled.set()
                snapshot = self._snapshot(entry)
            should_drain = (
                self._enqueue_notification_locked() if changed else False
            )
        if should_drain:
            self._drain_notifications()
        return snapshot

    def _try_enter_committing(self, operation_id: str) -> bool:
        with self._lock:
            entry = self._entries.get(operation_id)
            if entry is None or entry.status is not OperationStatus.RUNNING:
                return False
            entry.status = OperationStatus.COMMITTING
            should_drain = self._enqueue_notification_locked()
        if should_drain:
            self._drain_notifications()
        return True

    def _has_active_operations_locked(self) -> bool:
        return any(
            entry.status not in TERMINAL_STATUSES or entry.execution_active
            for entry in self._entries.values()
        )

    def _enqueue_notification_locked(self) -> bool:
        active = self._has_active_operations_locked()
        if active != self._last_enqueued_active:
            self._notification_queue.append(active)
            self._last_enqueued_active = active
        if self._dispatching_notifications or not self._notification_queue:
            return False
        self._dispatching_notifications = True
        return True

    def _drain_notifications(self) -> None:
        """Deliver immutable state edges in their mutation order."""
        while True:
            with self._lock:
                if not self._notification_queue:
                    self._dispatching_notifications = False
                    return
                active = self._notification_queue.popleft()
                listeners = tuple(self._listeners.items())
            for token, subscription in listeners:
                failed = False
                with subscription.dispatch_lock:
                    if not subscription.active:
                        continue
                    try:
                        subscription.listener(active)
                    except BaseException:  # noqa: BLE001
                        # Observers are non-control-plane callbacks. Quarantine
                        # every failure so no exception can strand this drainer
                        # or prevent live observers receiving the same edge.
                        subscription.active = False
                        failed = True
                if failed:
                    with self._lock:
                        if self._listeners.get(token) is subscription:
                            self._listeners.pop(token)

    @staticmethod
    def _snapshot(entry: _OperationEntry) -> OperationSnapshot:
        return OperationSnapshot(
            operation_id=entry.operation_id,
            idempotency_key=entry.idempotency_key,
            kind=entry.kind,
            requested_at=entry.requested_at,
            status=entry.status,
            summary=MappingProxyType(dict(entry.summary)),
        )

    def _emit(self, event: DiagnosticEvent) -> None:
        try:
            self._diagnostics.emit(event)
        except (OSError, TypeError, ValueError):
            return
