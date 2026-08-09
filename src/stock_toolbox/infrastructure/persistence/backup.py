"""SQLite online backup with immediate restore verification."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from stock_toolbox.infrastructure.persistence.errors import StorageUnavailableError


@dataclass(frozen=True, slots=True)
class BackupReport:
    destination: Path
    quick_check: str


def create_online_backup(
    source: Path,
    destination: Path,
) -> BackupReport:
    if destination.exists():
        raise StorageUnavailableError("Backup destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    source_connection: sqlite3.Connection | None = None
    destination_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(source_uri, uri=True)
        destination_connection = sqlite3.connect(destination)
        source_connection.backup(destination_connection)
        destination_connection.close()
        destination_connection = sqlite3.connect(
            f"{destination.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        quick_check = str(
            destination_connection.execute("PRAGMA quick_check").fetchone()[0]
        )
        if quick_check != "ok":
            raise StorageUnavailableError("Backup verification failed")
        return BackupReport(destination, quick_check)
    except (OSError, sqlite3.Error) as error:
        if destination.exists():
            destination.unlink(missing_ok=True)
        raise StorageUnavailableError("SQLite backup failed") from error
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()
