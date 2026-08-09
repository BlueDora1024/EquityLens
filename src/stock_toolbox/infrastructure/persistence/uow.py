"""Explicit short SQLite Unit of Work."""

from __future__ import annotations

import sqlite3
from types import TracebackType
from typing import Literal, Self

from stock_toolbox.core.diagnostics.models import (
    DiagnosticLogger,
    DiagnosticStatus,
    NullDiagnosticLogger,
)
from stock_toolbox.core.diagnostics.timing import DiagnosticSpan
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import (
    ConcurrentModificationError,
    DatabaseBusyError,
    DatabaseCorruptError,
    PersistenceConflictError,
    PersistenceError,
    PersistenceValidationError,
    StorageUnavailableError,
)


def map_sqlite_error(error: sqlite3.Error) -> PersistenceError:
    """Map SQLite failures without preserving SQL text or bound values."""

    message = str(error).lower()
    if isinstance(error, sqlite3.IntegrityError):
        if "check constraint" in message:
            return PersistenceValidationError()
        return PersistenceConflictError()
    if "locked" in message or "busy" in message:
        return DatabaseBusyError()
    if any(
        fragment in message
        for fragment in (
            "readonly",
            "read-only",
            "disk is full",
            "unable to open",
            "permission",
        )
    ):
        return StorageUnavailableError()
    if "malformed" in message or "corrupt" in message:
        return DatabaseCorruptError()
    return PersistenceError()


def require_revision_update(row_count: int) -> None:
    if row_count != 1:
        raise ConcurrentModificationError()


class SQLiteUnitOfWork:
    """Own one writer connection and one explicit immediate transaction."""

    def __init__(self, factory: SQLiteConnectionFactory) -> None:
        self._factory = factory
        self._diagnostics: DiagnosticLogger = getattr(
            factory,
            "diagnostics",
            NullDiagnosticLogger(),
        )
        self._connection: sqlite3.Connection | None = None
        self._committed = False
        self._span: DiagnosticSpan | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Unit of Work is not active")
        return self._connection

    def __enter__(self) -> Self:
        if self._connection is not None:
            raise RuntimeError("Unit of Work cannot be entered twice")
        self._span = DiagnosticSpan(
            self._diagnostics,
            module="sqlite",
            action="transaction",
        ).start()
        for attempt in range(2):
            self._connection = self._factory.open_writer()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                return self
            except sqlite3.Error as error:
                self._connection.close()
                self._connection = None
                mapped = map_sqlite_error(error)
                if isinstance(mapped, DatabaseBusyError) and attempt == 0:
                    continue
                self._span.finish(
                    DiagnosticStatus.FAILED,
                    error_code=mapped.code,
                )
                raise mapped from error
        raise AssertionError("unreachable")

    def commit(self) -> None:
        try:
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            mapped = map_sqlite_error(error)
            if self._span is not None:
                self._span.finish(
                    DiagnosticStatus.FAILED,
                    error_code=mapped.code,
                )
            raise mapped from error
        self._committed = True
        if self._span is not None:
            self._span.finish(DiagnosticStatus.SUCCEEDED)

    def rollback(self) -> None:
        if self._connection is not None and self._connection.in_transaction:
            self._connection.rollback()

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if not self._committed:
            self.rollback()
            if self._span is not None:
                self._span.finish(
                    DiagnosticStatus.CANCELLED
                    if exception_type is None
                    else DiagnosticStatus.FAILED,
                    error_code=(
                        ""
                        if exception_type is None
                        else "transaction_body_failed"
                    ),
                )
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        del exception, traceback
        return False
