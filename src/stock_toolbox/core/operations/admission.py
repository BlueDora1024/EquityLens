"""Atomic admission and quiescence tracking for application shutdown."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from stock_toolbox.core.operations.registry import (
    OperationRegistry,
    OperationSnapshot,
    ReserveDecision,
    ReserveResult,
)

ReadIdentity = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdmissionReserveDecision:
    result: ReserveResult
    decision: ReserveDecision | None = None


@dataclass(frozen=True, slots=True)
class ClosingSnapshot:
    generation: int
    quiescent: bool
    operations: tuple[OperationSnapshot, ...]
    reads: tuple[ReadIdentity, ...]
    short_mutations: tuple[str, ...]


class ApplicationAdmission:
    def __init__(self, registry: OperationRegistry) -> None:
        self.registry = registry
        self._lock = threading.RLock()
        self._closed = False
        self._generation = 0
        self._reads: set[ReadIdentity] = set()
        self._short_mutations: set[str] = set()

    def reserve_operation(
        self,
        operation_id: str,
        idempotency_key: str,
        kind: str,
    ) -> AdmissionReserveDecision:
        with self._lock:
            if self._closed:
                return AdmissionReserveDecision(ReserveResult.ADMISSION_CLOSED)
            decision = self.registry.reserve(
                operation_id,
                idempotency_key,
                kind,
            )
            return AdmissionReserveDecision(decision.result, decision)

    def try_begin_read(self, identity: ReadIdentity) -> bool:
        with self._lock:
            if self._closed or identity in self._reads:
                return False
            self._reads.add(identity)
            return True

    def finish_read(self, identity: ReadIdentity) -> None:
        with self._lock:
            self._reads.discard(identity)

    def try_begin_short_mutation(self, mutation_id: str) -> bool:
        with self._lock:
            if self._closed or mutation_id in self._short_mutations:
                return False
            self._short_mutations.add(mutation_id)
            return True

    def finish_short_mutation(self, mutation_id: str) -> None:
        with self._lock:
            self._short_mutations.discard(mutation_id)

    def begin_closing(self) -> ClosingSnapshot:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._generation += 1
            return self._snapshot()

    def confirm_quiescent(self, generation: int) -> ClosingSnapshot:
        with self._lock:
            if not self._closed or generation != self._generation:
                return self._snapshot(force_not_quiescent=True)
            return self._snapshot()

    def resume(self, generation: int) -> bool:
        with self._lock:
            if not self._closed or generation != self._generation:
                return False
            self._closed = False
            return True

    def _snapshot(
        self,
        *,
        force_not_quiescent: bool = False,
    ) -> ClosingSnapshot:
        operations = self.registry.non_terminal_snapshots()
        reads = tuple(sorted(self._reads))
        mutations = tuple(sorted(self._short_mutations))
        quiescent = not force_not_quiescent and not (
            operations or reads or mutations
        )
        return ClosingSnapshot(
            self._generation,
            quiescent,
            operations,
            reads,
            mutations,
        )
