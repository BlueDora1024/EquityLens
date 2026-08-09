from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from stock_toolbox.core.diagnostics.models import DiagnosticEvent
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import (
    DatabaseBusyError,
    DatabaseCorruptError,
    PersistenceError,
    StorageUnavailableError,
)
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork


@dataclass
class _Logger:
    events: list[DiagnosticEvent] = field(default_factory=list)

    def emit(self, event: DiagnosticEvent) -> None:
        self.events.append(event)

    def flush(self, timeout_seconds: float = 1.0) -> bool:
        return True

    def close(self, timeout_seconds: float = 1.0) -> bool:
        return True


class Connection:
    def __init__(
        self,
        *,
        begin_error: sqlite3.Error | None = None,
        commit_error: sqlite3.Error | None = None,
    ) -> None:
        self.begin_error = begin_error
        self.commit_error = commit_error
        self.in_transaction = False
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql: str) -> None:
        assert sql == "BEGIN IMMEDIATE"
        if self.begin_error is not None:
            raise self.begin_error
        self.in_transaction = True

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error
        self.in_transaction = False

    def rollback(self) -> None:
        self.rollbacks += 1
        self.in_transaction = False

    def close(self) -> None:
        self.closed = True


class Factory:
    def __init__(self, *connections: Connection) -> None:
        self.connections = iter(connections)
        self.open_calls = 0

    def open_writer(self) -> Connection:
        self.open_calls += 1
        return next(self.connections)


def test_first_busy_begin_reopens_and_retries_exactly_once() -> None:
    first = Connection(
        begin_error=sqlite3.OperationalError("database is locked")
    )
    second = Connection()
    factory = Factory(first, second)

    with SQLiteUnitOfWork(factory):  # type: ignore[arg-type]
        pass

    assert factory.open_calls == 2
    assert first.closed is True
    assert second.closed is True
    assert second.rollbacks == 1


def test_second_busy_begin_fails_with_stable_database_busy() -> None:
    first = Connection(
        begin_error=sqlite3.OperationalError("database is busy")
    )
    second = Connection(
        begin_error=sqlite3.OperationalError("database is locked")
    )
    factory = Factory(first, second)

    with (
        pytest.raises(DatabaseBusyError) as caught,
        SQLiteUnitOfWork(factory),  # type: ignore[arg-type]
    ):
        pass

    assert caught.value.code == "database_busy"
    assert factory.open_calls == 2
    assert first.closed is True
    assert second.closed is True


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            sqlite3.DatabaseError("database disk image is malformed"),
            DatabaseCorruptError,
        ),
        (
            sqlite3.OperationalError("attempt to write a readonly database"),
            StorageUnavailableError,
        ),
        (
            sqlite3.OperationalError("disk is full"),
            StorageUnavailableError,
        ),
    ],
)
def test_non_busy_begin_failures_are_never_retried(
    error: sqlite3.Error,
    expected: type[PersistenceError],
) -> None:
    connection = Connection(begin_error=error)
    factory = Factory(connection)

    with (
        pytest.raises(expected),
        SQLiteUnitOfWork(factory),  # type: ignore[arg-type]
    ):
        pass

    assert factory.open_calls == 1
    assert connection.closed is True


def test_body_exception_is_rolled_back_without_retry() -> None:
    connection = Connection()
    factory = Factory(connection)

    with (
        pytest.raises(ValueError, match="body failed"),
        SQLiteUnitOfWork(factory) as _uow,  # type: ignore[arg-type]
    ):
        raise ValueError("body failed")

    assert factory.open_calls == 1
    assert connection.rollbacks == 1
    assert connection.closed is True


def test_body_sqlite_busy_is_not_writer_acquisition_retry() -> None:
    connection = Connection()
    factory = Factory(connection)

    with (
        pytest.raises(sqlite3.OperationalError, match="locked"),
        SQLiteUnitOfWork(factory) as _uow,  # type: ignore[arg-type]
    ):
        raise sqlite3.OperationalError("database is locked")

    assert factory.open_calls == 1
    assert connection.rollbacks == 1


def test_commit_failure_rolls_back_without_retry() -> None:
    connection = Connection(
        commit_error=sqlite3.OperationalError("disk I/O error")
    )
    factory = Factory(connection)

    with (
        pytest.raises(PersistenceError),
        SQLiteUnitOfWork(factory) as uow,  # type: ignore[arg-type]
    ):
        uow.commit()

    assert factory.open_calls == 1
    assert connection.commits == 1
    assert connection.rollbacks == 1
    assert connection.closed is True


def test_real_transaction_logs_commit_duration(tmp_path: Path) -> None:
    logger = _Logger()
    factory = SQLiteConnectionFactory(
        tmp_path / "transaction.sqlite3",
        diagnostics=logger,
    )

    with SQLiteUnitOfWork(factory) as uow:
        uow.connection.execute("CREATE TABLE evidence(value INTEGER)")
        uow.commit()

    terminal = [
        event
        for event in logger.events
        if event.module == "sqlite"
        and event.action == "transaction"
        and event.status.value != "started"
    ][-1]
    assert terminal.status.value == "succeeded"
    assert isinstance(terminal.duration_ms, int)


class ShortBusyTimeoutFactory(SQLiteConnectionFactory):
    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self.open_calls = 0

    def open_writer(self) -> sqlite3.Connection:
        self.open_calls += 1
        connection = super().open_writer()
        connection.execute("PRAGMA busy_timeout = 1")
        return connection


def test_real_two_connection_contention_retries_twice_then_recovers(
    tmp_path: Path,
) -> None:
    database = tmp_path / "busy.sqlite3"
    sqlite3.connect(database).close()
    holder = sqlite3.connect(database, isolation_level=None, timeout=0)
    holder.execute("BEGIN IMMEDIATE")
    factory = ShortBusyTimeoutFactory(database)

    try:
        with pytest.raises(DatabaseBusyError), SQLiteUnitOfWork(factory):
            pass
    finally:
        holder.rollback()
        holder.close()

    assert factory.open_calls == 2
    with SQLiteUnitOfWork(factory) as uow:
        uow.connection.execute(
            "CREATE TABLE recovered (value INTEGER NOT NULL)"
        )
        uow.commit()
    assert factory.open_calls == 3
