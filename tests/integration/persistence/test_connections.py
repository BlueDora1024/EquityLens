from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.uow import (
    SQLiteUnitOfWork,
    map_sqlite_error,
    require_revision_update,
)


def migrated_database(tmp_path: Path) -> Path:
    database = tmp_path / "db.sqlite3"
    MigrationRunner(
        database,
        app_version="0.1.0",
        now=lambda: datetime(2026, 7, 25, tzinfo=UTC),
    ).bootstrap()
    return database


def test_writer_and_reader_have_frozen_connection_pragmas(tmp_path: Path) -> None:
    factory = SQLiteConnectionFactory(migrated_database(tmp_path))

    with factory.open_writer() as writer:
        assert writer.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert writer.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert writer.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert writer.execute("PRAGMA query_only").fetchone()[0] == 0

    with factory.open_reader() as reader:
        assert reader.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert reader.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert reader.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("DELETE FROM settings")


def test_connection_cannot_cross_threads(tmp_path: Path) -> None:
    factory = SQLiteConnectionFactory(migrated_database(tmp_path))
    connection = factory.open_writer()
    errors: list[sqlite3.ProgrammingError] = []

    def use_from_another_thread() -> None:
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError as error:
            errors.append(error)

    worker = threading.Thread(target=use_from_another_thread)
    worker.start()
    worker.join()
    connection.close()

    assert len(errors) == 1
    assert isinstance(errors[0], sqlite3.ProgrammingError)


def test_uow_rolls_back_uncommitted_work_and_persists_committed_work(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(migrated_database(tmp_path))
    with SQLiteUnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO settings(key,value_type,value_json,updated_at_utc) "
            "VALUES (?,?,?,?)",
            ("test.rollback", "JSON", "{}", "2026-07-25T00:00:00.000000Z"),
        )

    with factory.open_reader() as reader:
        assert (
            reader.execute(
                "SELECT count(*) FROM settings WHERE key='test.rollback'"
            ).fetchone()[0]
            == 0
        )

    with SQLiteUnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO settings(key,value_type,value_json,updated_at_utc) "
            "VALUES (?,?,?,?)",
            ("test.commit", "JSON", "{}", "2026-07-25T00:00:00.000000Z"),
        )
        uow.commit()

    with factory.open_reader() as reader:
        assert (
            reader.execute(
                "SELECT count(*) FROM settings WHERE key='test.commit'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            sqlite3.IntegrityError("UNIQUE constraint failed: settings.key"),
            PersistenceConflictError,
        ),
        (
            sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
            PersistenceConflictError,
        ),
        (
            sqlite3.IntegrityError("CHECK constraint failed: value"),
            PersistenceValidationError,
        ),
        (
            sqlite3.OperationalError("database is locked"),
            DatabaseBusyError,
        ),
        (
            sqlite3.OperationalError("attempt to write a readonly database"),
            StorageUnavailableError,
        ),
        (
            sqlite3.DatabaseError("database disk image is malformed"),
            DatabaseCorruptError,
        ),
        (sqlite3.DatabaseError("unexpected engine failure"), PersistenceError),
    ],
)
def test_sqlite_errors_map_to_one_stable_sanitized_category(
    error: sqlite3.Error,
    expected: type[PersistenceError],
) -> None:
    mapped = map_sqlite_error(error)

    assert type(mapped) is expected
    assert "settings.key" not in str(mapped)
    assert "engine failure" not in str(mapped)


def test_zero_row_revision_update_is_concurrent_modification() -> None:
    with pytest.raises(ConcurrentModificationError):
        require_revision_update(0)
    require_revision_update(1)
