from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticStatus,
)
from stock_toolbox.infrastructure.diagnostics.jsonl import JsonlDiagnosticLogger

NOW = datetime(2026, 7, 30, 15, 30, tzinfo=UTC)


def _event(index: int, *, level: DiagnosticLevel = DiagnosticLevel.INFO) -> DiagnosticEvent:
    return DiagnosticEvent(
        level,
        "rs_strength",
        "fetch_daily",
        DiagnosticStatus.SUCCEEDED,
        task_id="run-1",
        ticker=f"T{index}.US",
        details={"index": index},
    )


def _lines(root: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for path in sorted(root.glob("diagnostics-*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_writer_persists_compact_sanitized_jsonl(tmp_path: Path) -> None:
    logger = JsonlDiagnosticLogger(
        tmp_path,
        app_version="0.9.6",
        clock=lambda: NOW,
    )

    logger.emit(_event(1))

    assert logger.flush()
    payload = _lines(tmp_path)[0]
    assert payload["timestamp"] == "2026-07-30T15:30:00+00:00"
    assert payload["app_version"] == "0.9.6"
    assert payload["session_id"]
    assert payload["ticker"] == "T1.US"
    assert payload["details"] == {"index": 1}
    assert logger.close()


def test_writer_rotates_without_deleting_active_file(tmp_path: Path) -> None:
    logger = JsonlDiagnosticLogger(
        tmp_path,
        app_version="0.9.6",
        clock=lambda: NOW,
        max_file_bytes=350,
        max_total_bytes=10_000,
    )

    for index in range(12):
        logger.emit(_event(index))

    assert logger.flush()
    paths = tuple(tmp_path.glob("diagnostics-*.jsonl"))
    assert len(paths) > 1
    assert logger.active_path in paths
    assert logger.active_path.exists()
    assert logger.close()


def test_writer_never_raises_when_sensitive_detail_reaches_boundary(
    tmp_path: Path,
) -> None:
    logger = JsonlDiagnosticLogger(
        tmp_path,
        app_version="0.9.6",
        clock=lambda: NOW,
    )
    event = DiagnosticEvent(
        DiagnosticLevel.ERROR,
        "settings",
        "save",
        DiagnosticStatus.FAILED,
        details={"api_key": "sk-12345678901234567890"},
    )

    logger.emit(event)

    assert logger.flush()
    assert _lines(tmp_path) == []
    assert logger.rejected_events == 1
    assert logger.close()


def test_full_queue_discards_debug_before_important_events(tmp_path: Path) -> None:
    logger = JsonlDiagnosticLogger(
        tmp_path,
        app_version="0.9.6",
        clock=lambda: NOW,
        queue_capacity=1,
        start_writer=False,
    )

    logger.emit(_event(1))
    logger.emit(_event(2, level=DiagnosticLevel.DEBUG))
    logger.emit(_event(3, level=DiagnosticLevel.ERROR))

    assert logger.dropped_debug_events == 1
    assert logger.important_backlog == 1
    assert logger.close(timeout_seconds=0.01) is False


def test_close_is_idempotent(tmp_path: Path) -> None:
    logger = JsonlDiagnosticLogger(
        tmp_path,
        app_version="0.9.6",
        clock=lambda: NOW,
    )

    assert logger.close()
    assert logger.close()


def test_clear_replaces_existing_files_with_a_clean_active_log(
    tmp_path: Path,
) -> None:
    logger = JsonlDiagnosticLogger(
        tmp_path,
        app_version="0.9.6",
        clock=lambda: NOW,
    )
    logger.emit(_event(1))
    assert logger.flush()
    old_active = logger.active_path

    assert logger.clear()

    assert not old_active.exists()
    assert logger.active_path.exists()
    assert logger.active_path != old_active
    assert _lines(tmp_path) == []
    assert logger.close()
