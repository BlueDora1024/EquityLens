from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stock_toolbox.infrastructure.persistence.errors import MigrationIncompatibleError
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner

EXPECTED_TABLES = {
    "schema_migrations",
    "global_securities",
    "classifications",
    "ai_application_receipts",
    "security_classifications",
    "calculation_watchlists",
    "watchlist_memberships",
    "settings",
    "run_snapshots",
    "run_ranges",
    "run_members",
    "run_stock_results",
    "run_classification_period_results",
    "run_classification_results",
    "run_failures",
    "analysis_runs",
    "analysis_payload_runs",
    "market_candle_cache",
    "market_candle_coverage",
    "market_daily_series_cache",
    "quant_result_cache",
}


def runner(database: Path, migration_dir: Path | None = None) -> MigrationRunner:
    return MigrationRunner(
        database,
        app_version="0.1.0",
        now=lambda: datetime(2026, 7, 25, 12, tzinfo=UTC),
        migration_dir=migration_dir,
    )


def table_names(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }


def test_empty_database_migrates_to_exact_table_schema(
    tmp_path: Path,
) -> None:
    database = tmp_path / "RSRadar.integration.sqlite3"

    report = runner(database).bootstrap()

    assert report.schema_version == 13
    assert report.applied_versions == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)
    assert report.journal_mode == "wal"
    assert table_names(database) == EXPECTED_TABLES
    with sqlite3.connect(database) as connection:
        receipts = connection.execute(
            "SELECT version,name,length(checksum_sha256),applied_at_utc,app_version "
            "FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert receipts == [
            (
                1,
                "initial",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                2,
                "remove_keychain_credentials",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                3,
                "analysis_runs",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                4,
                "analysis_payload_runs",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                5,
                "market_candle_cache",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                6,
                "query_plan_indexes",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                7,
                "quant_result_cache",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                8,
                "rs_short_ranges",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                9,
                "retire_turning_risk_cache",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                10,
                "retire_invalid_turning_intraday_quant",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                11,
                "market_candle_coverage",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                12,
                "daily_series_cache",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
            (
                13,
                "candle_request_coverage",
                64,
                "2026-07-25T12:00:00.000000Z",
                "0.1.0",
            ),
        ]
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_bootstrap_is_idempotent_and_does_not_reapply_migration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    first = runner(database).bootstrap()
    second = runner(database).bootstrap()

    assert first.applied_versions == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)
    assert second.applied_versions == ()
    assert second.schema_version == 13


def test_invalid_two_and_four_hour_turning_quant_cache_is_deleted(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    default_runner = runner(database)
    old_migrations = tmp_path / "old-migrations"
    old_migrations.mkdir()
    for source in sorted(default_runner.migration_dir.glob("000[1-9]_*.sql")):
        shutil.copy(source, old_migrations / source.name)
    runner(database, old_migrations).bootstrap()
    with sqlite3.connect(database) as connection:
        for interval in ("120m", "240m", "1d"):
            connection.execute(
                "INSERT INTO quant_result_cache VALUES (?,?,?,?,?,?,?,?)",
                (
                    "longbridge",
                    "IREN.US",
                    interval,
                    "2025-01-01T00:00:00Z",
                    "2026-08-01T00:00:00Z",
                    "turning-point-quant-v3",
                    "{}",
                    "2026-08-02T00:00:00Z",
                ),
            )

    report = default_runner.bootstrap()

    assert report.applied_versions == (10, 11, 12, 13)
    with sqlite3.connect(database) as connection:
        remaining = connection.execute(
            "SELECT interval FROM quant_result_cache ORDER BY interval"
        ).fetchall()
    assert remaining == [("1d",)]


def test_retired_turning_risk_quant_cache_is_deleted(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite3"
    default_runner = runner(database)
    old_migrations = tmp_path / "old-migrations"
    old_migrations.mkdir()
    for source in sorted(default_runner.migration_dir.glob("000[1-8]_*.sql")):
        shutil.copy(source, old_migrations / source.name)
    runner(database, old_migrations).bootstrap()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO quant_result_cache VALUES (?,?,?,?,?,?,?,?)",
            (
                "longbridge",
                "IREN.US",
                "1d",
                "2025-01-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                "turning-risk-250d-v1",
                "{}",
                "2026-08-02T00:00:00Z",
            ),
        )

    report = default_runner.bootstrap()

    assert report.applied_versions == (9, 10, 11, 12, 13)
    with sqlite3.connect(database) as connection:
        remaining = connection.execute("SELECT count(*) FROM quant_result_cache").fetchone()[0]
    assert remaining == 0


def test_modified_applied_migration_checksum_is_rejected(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    original_runner = runner(database)
    original_runner.bootstrap()
    copied = tmp_path / "migrations"
    copied.mkdir()
    source = original_runner.migration_dir / "0001_initial.sql"
    target = copied / source.name
    shutil.copy(source, target)
    target.write_text(target.read_text() + "\n-- tampered\n")

    with pytest.raises(MigrationIncompatibleError):
        runner(database, copied).bootstrap()


def test_database_version_newer_than_application_is_rejected(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    runner(database).bootstrap()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO schema_migrations VALUES (14,'future',"
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
            "'2026-07-25T12:00:00.000000Z','9.0.0')"
        )

    with pytest.raises(MigrationIncompatibleError):
        runner(database).bootstrap()


def test_failed_initial_migration_rolls_back_every_created_table(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    copied = tmp_path / "migrations"
    copied.mkdir()
    default_runner = runner(database)
    source = default_runner.migration_dir / "0001_initial.sql"
    target = copied / source.name
    target.write_text(
        source.read_text()
        + "\nCREATE TABLE invalid_duplicate(id TEXT);\n"
        + "CREATE TABLE invalid_duplicate(id TEXT);\n"
    )

    with pytest.raises(MigrationIncompatibleError):
        runner(database, copied).bootstrap()

    assert table_names(database) == set()
