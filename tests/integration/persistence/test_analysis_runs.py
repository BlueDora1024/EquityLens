from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.history_repository import HistoryRepository
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork
from tests.integration.persistence.test_history_repository import partial_snapshot


def _runner(database: Path, migration_dir: Path | None = None) -> MigrationRunner:
    return MigrationRunner(
        database,
        app_version="0.2.0",
        now=lambda: datetime(2026, 7, 26, 12, tzinfo=UTC),
        migration_dir=migration_dir,
    )


def test_schema_v2_history_is_backfilled_as_rs_strength(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    default = _runner(database)
    default.bootstrap()
    with sqlite3.connect(database) as connection:
        HistoryRepository(connection).insert_snapshot(partial_snapshot(30))
        connection.execute("DROP TABLE analysis_payload_runs")
        connection.execute("DROP TABLE analysis_runs")
        connection.execute("DELETE FROM schema_migrations WHERE version=4")
        connection.execute("DELETE FROM schema_migrations WHERE version=3")
        connection.commit()

    report = default.bootstrap()

    assert report.applied_versions == (3, 4)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT analysis_type,analysis_version,result_schema_version "
            "FROM analysis_runs"
        ).fetchone()
    assert row == ("rs_strength", "1.0.0", 1)


def test_new_rs_save_writes_generic_header_in_same_transaction(
    tmp_path: Path,
) -> None:
    database = tmp_path / "current.sqlite3"
    _runner(database).bootstrap()

    with SQLiteUnitOfWork(SQLiteConnectionFactory(database)) as uow:
        HistoryRepository(uow.connection).insert_snapshot(partial_snapshot(31))
        uow.commit()

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT analysis_type,status,provider_id FROM analysis_runs"
        ).fetchone()
    assert row == ("rs_strength", "PARTIAL", "longbridge")
