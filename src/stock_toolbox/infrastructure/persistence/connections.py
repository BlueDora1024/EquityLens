"""Thread-owned SQLite connection configuration."""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, cast

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticLogger,
    DiagnosticStatus,
    NullDiagnosticLogger,
)
from stock_toolbox.infrastructure.persistence.errors import PersistenceError

_SQL_OPERATION = re.compile(r"^\s*([A-Za-z]+)")
_SQL_TABLES = (
    re.compile(r"^\s*INSERT(?:\s+OR\s+\w+)?\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE),
    re.compile(r"^\s*UPDATE\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE),
    re.compile(r"^\s*DELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE),
    re.compile(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE),
    re.compile(
        r"^\s*CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)",
        re.IGNORECASE,
    ),
)


def sql_level(duration_ms: int) -> DiagnosticLevel:
    return (
        DiagnosticLevel.WARNING
        if duration_ms >= 300
        else DiagnosticLevel.DEBUG
    )


def sql_action(duration_ms: int) -> str:
    if duration_ms >= 1_000:
        return "very_slow_query"
    if duration_ms >= 300:
        return "slow_query"
    return "query"


def _sql_identity(sql: str) -> tuple[str, str]:
    operation_match = _SQL_OPERATION.search(sql)
    operation = (
        operation_match.group(1).casefold()
        if operation_match is not None
        else "unknown"
    )
    table = ""
    for pattern in _SQL_TABLES:
        match = pattern.search(sql)
        if match is not None:
            table = match.group(1).casefold()
            break
    return operation, table


class _DiagnosticConnection(sqlite3.Connection):
    _diagnostics: DiagnosticLogger
    _role: str
    _monotonic_ns: Callable[[], int]

    def configure_diagnostics(
        self,
        diagnostics: DiagnosticLogger,
        role: str,
        monotonic_ns: Callable[[], int],
    ) -> None:
        self._diagnostics = diagnostics
        self._role = role
        self._monotonic_ns = monotonic_ns

    def execute(
        self,
        sql: str,
        parameters: object = (),
        /,
    ) -> sqlite3.Cursor:
        started = self._monotonic_ns()
        try:
            cursor = super().execute(sql, cast(Any, parameters))
        except sqlite3.Error:
            self._emit_sql(sql, started, DiagnosticStatus.FAILED)
            raise
        self._emit_sql(
            sql,
            started,
            DiagnosticStatus.SUCCEEDED,
            row_count=max(0, cursor.rowcount),
        )
        return cursor

    def executemany(
        self,
        sql: str,
        seq_of_parameters: Iterable[object],
        /,
    ) -> sqlite3.Cursor:
        started = self._monotonic_ns()
        try:
            cursor = super().executemany(
                sql,
                cast(Any, seq_of_parameters),
            )
        except sqlite3.Error:
            self._emit_sql(sql, started, DiagnosticStatus.FAILED)
            raise
        self._emit_sql(
            sql,
            started,
            DiagnosticStatus.SUCCEEDED,
            row_count=max(0, cursor.rowcount),
        )
        return cursor

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        started = self._monotonic_ns()
        try:
            cursor = super().executescript(sql_script)
        except sqlite3.Error:
            self._emit_sql(sql_script, started, DiagnosticStatus.FAILED)
            raise
        self._emit_sql(sql_script, started, DiagnosticStatus.SUCCEEDED)
        return cursor

    def _emit_sql(
        self,
        sql: str,
        started_ns: int,
        status: DiagnosticStatus,
        *,
        row_count: int = 0,
    ) -> None:
        duration_ms = max(
            0,
            (self._monotonic_ns() - started_ns) // 1_000_000,
        )
        operation, table = _sql_identity(sql)
        details: dict[str, str | int] = {
            "operation": operation,
            "role": self._role,
            "row_count": row_count,
        }
        if table:
            details["table"] = table
        try:
            self._diagnostics.emit(
                DiagnosticEvent(
                    DiagnosticLevel.ERROR
                    if status is DiagnosticStatus.FAILED
                    else sql_level(duration_ms),
                    "sqlite",
                    sql_action(duration_ms),
                    status,
                    duration_ms=duration_ms,
                    error_code=(
                        "sqlite_error"
                        if status is DiagnosticStatus.FAILED
                        else ""
                    ),
                    details=details,
                )
            )
        except (OSError, TypeError, ValueError):
            return


class SQLiteConnectionFactory:
    """Open independently configured reader and writer connections."""

    def __init__(
        self,
        database_path: Path,
        *,
        diagnostics: DiagnosticLogger | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.database_path = database_path
        self.diagnostics = diagnostics or NullDiagnosticLogger()
        self._monotonic_ns = monotonic_ns

    def open_writer(self) -> sqlite3.Connection:
        try:
            connection = self._open(
                self.database_path,
                role="writer",
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA busy_timeout = 5000")
            self._verify(connection, "foreign_keys", 1)
            self._verify(connection, "busy_timeout", 5000)
            return connection
        except sqlite3.Error as error:
            raise PersistenceError() from error

    def open_reader(self) -> sqlite3.Connection:
        uri = f"{self.database_path.resolve().as_uri()}?mode=ro"
        try:
            connection = self._open(
                uri,
                role="reader",
                uri=True,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA query_only = ON")
            self._verify(connection, "foreign_keys", 1)
            self._verify(connection, "busy_timeout", 5000)
            self._verify(connection, "query_only", 1)
            return connection
        except sqlite3.Error as error:
            raise PersistenceError() from error

    def _open(
        self,
        database: str | Path,
        *,
        role: str,
        uri: bool = False,
    ) -> _DiagnosticConnection:
        connection = sqlite3.connect(
            database,
            uri=uri,
            isolation_level=None,
            timeout=5,
            factory=_DiagnosticConnection,
        )
        connection.configure_diagnostics(
            self.diagnostics,
            role,
            self._monotonic_ns,
        )
        return connection

    @staticmethod
    def _verify(
        connection: sqlite3.Connection,
        pragma: str,
        expected: int,
    ) -> None:
        # Pragma names are internal constants, never user input.
        result = connection.execute(f"PRAGMA {pragma}").fetchone()
        if result is None or result[0] != expected:
            connection.close()
            raise PersistenceError("SQLite connection configuration failed")
