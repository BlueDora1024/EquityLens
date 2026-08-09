from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner


def _uuid() -> str:
    return str(uuid4())


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "query-plans.sqlite3"
    MigrationRunner(
        database,
        app_version="test",
        now=lambda: datetime(2026, 7, 29, tzinfo=UTC),
    ).bootstrap()
    return database


def _details(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...] = (),
) -> tuple[str, ...]:
    return tuple(
        str(row[3])
        for row in connection.execute(
            f"EXPLAIN QUERY PLAN {sql}",
            parameters,
        )
    )


def test_ordered_hot_paths_use_covering_order_indexes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    watchlist_id = _uuid()
    classification_ids = tuple(_uuid() for _ in range(10))
    security_ids = tuple(_uuid() for _ in range(600))
    binding_ids = tuple(_uuid() for _ in security_ids)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO calculation_watchlists VALUES (?,?,?,?,?,0)",
            (
                watchlist_id,
                "大样本池",
                "大样本池",
                "2026-07-29T00:00:00Z",
                "2026-07-29T00:00:00Z",
            ),
        )
        connection.executemany(
            "INSERT INTO classifications VALUES (?,?,?,?,?,?,?,0)",
            (
                (
                    classification_id,
                    f"分类{index}",
                    f"class-{index}",
                    "[]",
                    "HUMAN",
                    "2026-07-29T00:00:00Z",
                    "2026-07-29T00:00:00Z",
                )
                for index, classification_id in enumerate(classification_ids)
            ),
        )
        connection.executemany(
            "INSERT INTO global_securities("
            "id,canonical_symbol,market,display_name,asset_type,"
            "eligibility_source,profile_provider_id,created_at_utc,updated_at_utc"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                (
                    security_id,
                    f"S{index}.US",
                    "US",
                    f"证券{index}",
                    "COMMON_STOCK",
                    "PROVIDER",
                    "virtual",
                    f"2026-07-29T00:{index % 60:02d}:00Z",
                    "2026-07-29T00:00:00Z",
                )
                for index, security_id in enumerate(security_ids)
            ),
        )
        connection.executemany(
            "INSERT INTO security_classifications("
            "id,security_id,classification_id,source,human_protected,"
            "created_at_utc,updated_at_utc"
            ") VALUES (?,?,?,'HUMAN',1,?,?)",
            (
                (
                    binding_ids[index],
                    security_id,
                    classification_ids[index % len(classification_ids)],
                    f"2026-07-29T00:{index % 60:02d}:00Z",
                    "2026-07-29T00:00:00Z",
                )
                for index, security_id in enumerate(security_ids)
            ),
        )
        connection.executemany(
            "INSERT INTO watchlist_memberships VALUES (?,?,?,?,?,?)",
            (
                (
                    _uuid(),
                    watchlist_id,
                    security_id,
                    binding_ids[index],
                    f"2026-07-29T00:{index % 60:02d}:00Z",
                    "2026-07-29T00:00:00Z",
                )
                for index, security_id in enumerate(security_ids)
            ),
        )
        connection.executemany(
            "INSERT INTO run_snapshots("
            "run_id,run_identifier,operation_id,source,status,pinned,"
            "display_name,original_run_name,started_at_utc,completed_at_utc,"
            "created_at_utc,provider_id,provider_display_name,"
            "provider_contract_version,benchmark_symbol,watchlist_name,"
            "requested_end_date,actual_end_date,member_count,valid_member_count,"
            "failed_member_count,algorithm_version,snapshot_format_version"
            ") VALUES (?,?,?,'AUTO','READY',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    _uuid(),
                    f"run-{index}",
                    f"operation-{index}",
                    index % 7 == 0,
                    f"历史 {index}",
                    f"历史 {index}",
                    "2026-07-29T00:00:00Z",
                    "2026-07-29T00:01:00Z",
                    f"2026-07-{(index % 28) + 1:02d}T00:00:00Z",
                    "virtual",
                    "Virtual",
                    "1",
                    "SPY.US",
                    "大样本池",
                    "2026-07-28",
                    "2026-07-28",
                    1,
                    1,
                    0,
                    "rs-algorithm-v1",
                    "1",
                )
                for index in range(1000)
            ),
        )
        connection.execute("ANALYZE")

        plans = (
            _details(
                connection,
                "SELECT * FROM watchlist_memberships "
                "WHERE watchlist_id=? ORDER BY created_at_utc,id",
                (watchlist_id,),
            ),
            _details(
                connection,
                "SELECT * FROM security_classifications "
                "WHERE security_id=? ORDER BY created_at_utc,id",
                (security_ids[0],),
            ),
            _details(
                connection,
                "SELECT run_id FROM run_snapshots "
                "ORDER BY pinned DESC,created_at_utc DESC,run_id DESC",
            ),
        )

    flattened = tuple(detail for plan in plans for detail in plan)
    assert not any("USE TEMP B-TREE FOR ORDER BY" in detail for detail in flattened)
    assert any("idx_memberships_watchlist_created" in detail for detail in plans[0])
    assert any(
        "idx_security_classifications_security_created" in detail
        for detail in plans[1]
    )
    assert any("idx_run_snapshots_history" in detail for detail in plans[2])
