from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from stock_toolbox.infrastructure.persistence.backup import create_online_backup
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.records import SettingRecord
from stock_toolbox.infrastructure.persistence.settings_repository import (
    SettingsRepository,
)
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork


def test_online_backup_captures_committed_wal_data_and_is_restorable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "Backups" / "before-v0002.sqlite3"
    MigrationRunner(
        source,
        app_version="0.1.0",
        now=lambda: datetime(2026, 7, 25, tzinfo=UTC),
    ).bootstrap()
    factory = SQLiteConnectionFactory(source)
    with SQLiteUnitOfWork(factory) as uow:
        SettingsRepository(uow.connection).upsert_setting(
            SettingRecord(
                "provider.default_id",
                "TEXT",
                "longbridge",
                1,
                datetime(2026, 7, 25, tzinfo=UTC),
            )
        )
        uow.commit()

    report = create_online_backup(source, destination)

    assert report.destination == destination
    assert report.quick_check == "ok"
    assert destination.exists()
    with sqlite3.connect(destination) as restored:
        assert restored.execute(
            "SELECT value_json FROM settings WHERE key='provider.default_id'"
        ).fetchone()[0] == '"longbridge"'
