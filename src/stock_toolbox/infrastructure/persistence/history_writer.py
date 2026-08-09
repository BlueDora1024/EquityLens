"""Commit-gated completed-run history writer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import PersistenceError
from stock_toolbox.infrastructure.persistence.history_records import HistorySnapshotRecord
from stock_toolbox.infrastructure.persistence.history_repository import HistoryRepository
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork


class CommitGate(Protocol):
    def try_enter_committing(self) -> bool: ...


class CompletedRunSaveStatus(StrEnum):
    SAVED = "SAVED"
    CANCELED_BEFORE_COMMIT = "CANCELED_BEFORE_COMMIT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class CompletedRunSaveResult:
    status: CompletedRunSaveStatus
    evicted_run_ids: tuple[str, ...] = ()
    error_code: str | None = None


class SaveCompletedRun:
    """Insert snapshot and retention rows before the sole commit gate."""

    def __init__(self, factory: SQLiteConnectionFactory) -> None:
        self._factory = factory

    def save(
        self,
        snapshot: HistorySnapshotRecord,
        operation_control: CommitGate,
    ) -> CompletedRunSaveResult:
        try:
            with SQLiteUnitOfWork(self._factory) as uow:
                repository = HistoryRepository(uow.connection)
                repository.insert_snapshot(snapshot)
                evicted = repository.evict_excess_unpinned_auto(keep=10)
                if not operation_control.try_enter_committing():
                    return CompletedRunSaveResult(
                        CompletedRunSaveStatus.CANCELED_BEFORE_COMMIT
                    )
                uow.commit()
            return CompletedRunSaveResult(
                CompletedRunSaveStatus.SAVED,
                evicted_run_ids=evicted,
            )
        except PersistenceError as error:
            return CompletedRunSaveResult(
                CompletedRunSaveStatus.FAILED,
                error_code=error.code,
            )
