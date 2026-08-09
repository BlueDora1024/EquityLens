"""Forward-only SQLite migration and bootstrap runner."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stock_toolbox.infrastructure.persistence.errors import (
    DatabaseCorruptError,
    MigrationIncompatibleError,
)
from stock_toolbox.infrastructure.persistence.types import canonical_instant

MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum_sha256: str


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    schema_version: int
    applied_versions: tuple[int, ...]
    journal_mode: str


class MigrationRunner:
    """Verify and apply immutable migrations to one physical database."""

    def __init__(
        self,
        database_path: Path,
        *,
        app_version: str,
        now: Callable[[], datetime],
        migration_dir: Path | None = None,
    ) -> None:
        self.database_path = database_path
        self.app_version = app_version
        self.now = now
        self.migration_dir = migration_dir or Path(__file__).with_name("sql")

    def discover(self) -> tuple[Migration, ...]:
        migrations = []
        for path in sorted(self.migration_dir.glob("*.sql")):
            match = MIGRATION_PATTERN.fullmatch(path.name)
            if match is None:
                raise MigrationIncompatibleError(
                    "Migration filename is incompatible"
                )
            content = path.read_bytes()
            migrations.append(
                Migration(
                    version=int(match.group("version")),
                    name=match.group("name"),
                    path=path,
                    checksum_sha256=hashlib.sha256(content).hexdigest(),
                )
            )
        versions = [migration.version for migration in migrations]
        if not migrations or versions != list(range(1, len(migrations) + 1)):
            raise MigrationIncompatibleError("Migration sequence is incomplete")
        return tuple(migrations)

    def bootstrap(self) -> BootstrapReport:
        migrations = self.discover()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.database_path,
            isolation_level=None,
        )
        try:
            self._verify_quick_check(connection)
            applied = self._read_applied(connection)
            latest_supported = migrations[-1].version
            if applied and max(applied) > latest_supported:
                raise MigrationIncompatibleError(
                    "Database schema is newer than this application"
                )
            migration_by_version = {
                migration.version: migration for migration in migrations
            }
            for version, (name, checksum) in applied.items():
                known = migration_by_version.get(version)
                if (
                    known is None
                    or known.name != name
                    or known.checksum_sha256 != checksum
                ):
                    raise MigrationIncompatibleError(
                        "Applied migration receipt is incompatible"
                    )
            newly_applied = []
            for migration in migrations:
                if migration.version in applied:
                    continue
                self._apply(connection, migration)
                newly_applied.append(migration.version)
            journal_mode = str(
                connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if journal_mode != "wal":
                raise MigrationIncompatibleError(
                    "SQLite did not enable WAL journal mode"
                )
            self._verify_quick_check(connection)
            return BootstrapReport(
                schema_version=migrations[-1].version,
                applied_versions=tuple(newly_applied),
                journal_mode=journal_mode,
            )
        finally:
            connection.close()

    @staticmethod
    def _verify_quick_check(connection: sqlite3.Connection) -> None:
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as error:
            raise DatabaseCorruptError("Database quick check failed") from error
        if result is None or result[0] != "ok":
            raise DatabaseCorruptError("Database quick check failed")

    @staticmethod
    def _read_applied(
        connection: sqlite3.Connection,
    ) -> dict[int, tuple[str, str]]:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if table is None:
            other = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone()
            if other is not None:
                raise MigrationIncompatibleError(
                    "Unversioned database schema is incompatible"
                )
            return {}
        try:
            rows = connection.execute(
                "SELECT version,name,checksum_sha256 "
                "FROM schema_migrations ORDER BY version"
            ).fetchall()
        except sqlite3.DatabaseError as error:
            raise MigrationIncompatibleError(
                "Migration receipts cannot be read"
            ) from error
        return {int(row[0]): (str(row[1]), str(row[2])) for row in rows}

    def _apply(
        self,
        connection: sqlite3.Connection,
        migration: Migration,
    ) -> None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in _sql_statements(
                migration.path.read_text(encoding="utf-8")
            ):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations("
                "version,name,checksum_sha256,applied_at_utc,app_version"
                ") VALUES (?,?,?,?,?)",
                (
                    migration.version,
                    migration.name,
                    migration.checksum_sha256,
                    canonical_instant(self.now()),
                    self.app_version,
                ),
            )
            connection.commit()
        except (OSError, sqlite3.DatabaseError) as error:
            if connection.in_transaction:
                connection.rollback()
            raise MigrationIncompatibleError("Migration failed") from error


def _sql_statements(content: str) -> Iterator[str]:
    buffer = ""
    for line in content.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if statement:
                yield statement
    if buffer.strip():
        raise MigrationIncompatibleError("Migration contains incomplete SQL")
