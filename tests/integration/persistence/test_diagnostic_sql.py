from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
)
from stock_toolbox.infrastructure.persistence.connections import (
    SQLiteConnectionFactory,
    sql_action,
    sql_level,
)


@dataclass
class _Logger:
    events: list[DiagnosticEvent] = field(default_factory=list)

    def emit(self, event: DiagnosticEvent) -> None:
        self.events.append(event)

    def flush(self, timeout_seconds: float = 1.0) -> bool:
        return True

    def close(self, timeout_seconds: float = 1.0) -> bool:
        return True


def test_connection_logs_operation_table_and_duration_without_parameters(
    tmp_path: Path,
) -> None:
    logger = _Logger()
    factory = SQLiteConnectionFactory(
        tmp_path / "diagnostics.sqlite3",
        diagnostics=logger,
    )
    connection = factory.open_writer()
    connection.execute(
        "CREATE TABLE settings("
        "key TEXT PRIMARY KEY, value_json TEXT NOT NULL"
        ")"
    )

    connection.execute(
        "INSERT INTO settings(key, value_json) VALUES (?, ?)",
        ("ai_api_key", '"secret-value"'),
    )

    event = [
        item
        for item in logger.events
        if item.details.get("operation") == "insert"
    ][-1]
    assert event.details["table"] == "settings"
    assert isinstance(event.duration_ms, int)
    assert event.duration_ms >= 0
    assert "secret-value" not in repr(logger.events)
    assert "ai_api_key" not in repr(logger.events)
    connection.close()


def test_sql_slow_thresholds_are_stable() -> None:
    assert sql_level(299) is DiagnosticLevel.DEBUG
    assert sql_level(300) is DiagnosticLevel.WARNING
    assert sql_action(300) == "slow_query"
    assert sql_action(999) == "slow_query"
    assert sql_action(1_000) == "very_slow_query"


def test_reader_queries_are_identified_without_result_values(
    tmp_path: Path,
) -> None:
    logger = _Logger()
    database = tmp_path / "reader.sqlite3"
    writer = SQLiteConnectionFactory(database).open_writer()
    writer.execute("CREATE TABLE securities(symbol TEXT NOT NULL)")
    writer.execute("INSERT INTO securities(symbol) VALUES ('IREN.US')")
    writer.close()
    reader = SQLiteConnectionFactory(database, diagnostics=logger).open_reader()

    assert reader.execute("SELECT symbol FROM securities").fetchone()[0] == "IREN.US"

    event = [
        item
        for item in logger.events
        if item.details.get("operation") == "select"
    ][-1]
    assert event.details["table"] == "securities"
    assert "IREN.US" not in repr(event)
    reader.close()
