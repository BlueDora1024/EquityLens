from __future__ import annotations

import sqlite3
from collections import namedtuple
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stock_toolbox.core.operations.storage_guard import (
    CLEANUP_FREE_BYTES,
    CacheCleanupResult,
    StorageGuard,
    StorageState,
)
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import PersistenceError
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.recomputable_cache import (
    SQLiteRecomputableCacheCleaner,
)

NOW = "2026-07-30T00:00:00+00:00"
SECURITY_ID = "00000000-0000-4000-8000-000000000001"
CLASSIFICATION_ID = "00000000-0000-4000-8000-000000000002"
BINDING_ID = "00000000-0000-4000-8000-000000000003"
WATCHLIST_ID = "00000000-0000-4000-8000-000000000004"
MEMBERSHIP_ID = "00000000-0000-4000-8000-000000000005"


def migrated_database(tmp_path: Path) -> Path:
    database = tmp_path / "database.sqlite3"
    MigrationRunner(
        database,
        app_version="0.1.0",
        now=lambda: datetime(2026, 7, 30, tzinfo=UTC),
    ).bootstrap()
    return database


def seed_database(factory: SQLiteConnectionFactory) -> None:
    with factory.open_writer() as connection:
        connection.execute(
            "INSERT INTO global_securities("
            "id,canonical_symbol,market,display_name,asset_type,"
            "eligibility_source,profile_provider_id,created_at_utc,updated_at_utc"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                SECURITY_ID,
                "AAPL.US",
                "US",
                "Apple",
                "COMMON_STOCK",
                "PROVIDER",
                "virtual",
                NOW,
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO classifications("
            "id,display_name,normalized_name,origin,created_at_utc,updated_at_utc"
            ") VALUES (?,?,?,?,?,?)",
            (
                CLASSIFICATION_ID,
                "Technology",
                "technology",
                "HUMAN",
                NOW,
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO security_classifications("
            "id,security_id,classification_id,source,human_protected,"
            "created_at_utc,updated_at_utc"
            ") VALUES (?,?,?,?,?,?,?)",
            (
                BINDING_ID,
                SECURITY_ID,
                CLASSIFICATION_ID,
                "HUMAN",
                1,
                NOW,
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO calculation_watchlists("
            "id,display_name,normalized_name,created_at_utc,updated_at_utc"
            ") VALUES (?,?,?,?,?)",
            (WATCHLIST_ID, "Core", "core", NOW, NOW),
        )
        connection.execute(
            "INSERT INTO watchlist_memberships("
            "id,watchlist_id,security_id,participating_binding_id,"
            "created_at_utc,updated_at_utc"
            ") VALUES (?,?,?,?,?,?)",
            (
                MEMBERSHIP_ID,
                WATCHLIST_ID,
                SECURITY_ID,
                BINDING_ID,
                NOW,
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO settings(key,value_type,value_json,updated_at_utc) VALUES (?,?,?,?)",
            (
                "services.config",
                "JSON",
                '{"provider":"virtual","api_key":"keep-me"}',
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO analysis_payload_runs("
            "run_id,analysis_type,analysis_version,operation_id,status,"
            "provider_id,display_name,completed_at_utc,payload_json"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "completed-run",
                "turning_point",
                "2.0.0",
                "operation",
                "READY",
                "virtual",
                "Completed",
                NOW,
                '{"result":"keep-me"}',
            ),
        )
        connection.execute(
            "INSERT INTO market_candle_cache VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "virtual",
                "AAPL.US",
                "1d",
                NOW,
                "forward",
                1,
                "1",
                "2",
                "0.5",
                "1.5",
                100,
                NOW,
            ),
        )
        connection.execute(
            "INSERT INTO quant_result_cache VALUES (?,?,?,?,?,?,?,?)",
            (
                "virtual",
                "AAPL.US",
                "1d",
                NOW,
                NOW,
                "v1",
                '{"values":{}}',
                NOW,
            ),
        )


def protected_rows(factory: SQLiteConnectionFactory) -> dict[str, list[tuple]]:
    tables = (
        "global_securities",
        "classifications",
        "security_classifications",
        "calculation_watchlists",
        "watchlist_memberships",
        "settings",
        "analysis_payload_runs",
    )
    with factory.open_reader() as connection:
        return {
            table: [
                tuple(row)
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            ]
            for table in tables
        }


class TracingFactory(SQLiteConnectionFactory):
    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self.statements: list[str] = []

    def open_writer(self) -> sqlite3.Connection:
        connection = super().open_writer()
        connection.set_trace_callback(self.statements.append)
        return connection


class RecordingCleaner:
    def __init__(self, cleaner: SQLiteRecomputableCacheCleaner) -> None:
        self.cleaner = cleaner
        self.result: CacheCleanupResult | None = None

    def clear_recomputable(self) -> CacheCleanupResult:
        self.result = self.cleaner.clear_recomputable()
        return self.result


class CapacityDiskUsage:
    _Usage = namedtuple("usage", "total used free")

    def __init__(self, cleaner: RecordingCleaner) -> None:
        self.cleaner = cleaner
        self.calls = 0

    def __call__(self, _path: Path) -> object:
        self.calls += 1
        if self.calls == 1:
            return self._Usage(0, 0, CLEANUP_FREE_BYTES - 1)
        assert self.cleaner.result is not None
        return self._Usage(
            0,
            0,
            CLEANUP_FREE_BYTES - self.cleaner.result.reusable_bytes,
        )


def test_cleanup_deletes_only_both_recomputable_cache_tables(
    tmp_path: Path,
) -> None:
    factory = TracingFactory(migrated_database(tmp_path))
    seed_database(factory)
    before = protected_rows(factory)
    factory.statements.clear()

    result = SQLiteRecomputableCacheCleaner(factory).clear_recomputable()

    with factory.open_reader() as connection:
        assert connection.execute("SELECT count(*) FROM market_candle_cache").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM market_candle_coverage").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM market_daily_series_cache").fetchone()[0] == 0
        )
        assert connection.execute("SELECT count(*) FROM quant_result_cache").fetchone()[0] == 0
    assert protected_rows(factory) == before
    assert result.reusable_bytes >= 0
    destructive = tuple(
        statement.upper()
        for statement in factory.statements
        if statement.lstrip().upper().startswith(("DELETE", "DROP", "VACUUM"))
    )
    assert destructive == (
        "DELETE FROM MARKET_CANDLE_CACHE",
        "DELETE FROM MARKET_CANDLE_COVERAGE",
        "DELETE FROM MARKET_DAILY_SERIES_CACHE",
        "DELETE FROM QUANT_RESULT_CACHE",
    )


def test_real_cleanup_reports_new_reusable_pages_without_shrinking_database(
    tmp_path: Path,
) -> None:
    database = migrated_database(tmp_path)
    factory = SQLiteConnectionFactory(database)
    seed_database(factory)
    payload = '{"data":"' + ("x" * 4096) + '"}'
    with factory.open_writer() as connection:
        connection.executemany(
            "INSERT INTO quant_result_cache VALUES (?,?,?,?,?,?,?,?)",
            (
                (
                    "virtual",
                    f"CACHE{index}.US",
                    "1d",
                    NOW,
                    NOW,
                    "large-v1",
                    payload,
                    NOW,
                )
                for index in range(3000)
            ),
        )
    size_before = database.stat().st_size

    cleaner = RecordingCleaner(SQLiteRecomputableCacheCleaner(factory))
    check = StorageGuard(
        tmp_path,
        cleaner,
        disk_usage=CapacityDiskUsage(cleaner),
    ).prepare_run()

    assert cleaner.result is not None
    assert cleaner.result.reusable_bytes > 0
    assert check.state is StorageState.WARNING
    assert check.free_bytes < CLEANUP_FREE_BYTES
    assert check.reusable_bytes == cleaner.result.reusable_bytes
    assert check.effective_available_bytes == CLEANUP_FREE_BYTES
    assert database.stat().st_size == size_before
    with factory.open_reader() as connection:
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        freelist = connection.execute("PRAGMA freelist_count").fetchone()[0]
    assert cleaner.result.reusable_bytes <= page_size * freelist


def test_second_cache_delete_failure_rolls_back_both_deletions_and_user_data(
    tmp_path: Path,
) -> None:
    factory = SQLiteConnectionFactory(migrated_database(tmp_path))
    seed_database(factory)
    before = protected_rows(factory)
    with factory.open_writer() as connection:
        connection.execute(
            "CREATE TRIGGER reject_quant_cleanup "
            "BEFORE DELETE ON quant_result_cache "
            "BEGIN SELECT RAISE(ABORT, 'injected delete failure'); END"
        )

    with pytest.raises(PersistenceError):
        SQLiteRecomputableCacheCleaner(factory).clear_recomputable()

    with factory.open_reader() as connection:
        assert connection.execute("SELECT count(*) FROM market_candle_cache").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM quant_result_cache").fetchone()[0] == 1
    assert protected_rows(factory) == before
