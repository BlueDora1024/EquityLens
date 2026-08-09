from __future__ import annotations

import json
from pathlib import Path

from stock_toolbox.infrastructure.diagnostics.query import (
    DiagnosticFilter,
    diagnostic_status,
    recent_events,
)


def _write(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(event, ensure_ascii=False) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )


def test_recent_events_filters_and_skips_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "diagnostics-2026-07-30-a-001.jsonl"
    _write(
        path,
        [
            {
                "timestamp": "2026-07-30T10:00:00+08:00",
                "level": "info",
                "module": "operations",
                "action": "rs_run",
                "status": "succeeded",
                "task_id": "run-1",
                "ticker": "IREN.US",
            },
            {
                "timestamp": "2026-07-30T10:01:00+08:00",
                "level": "warning",
                "module": "sqlite",
                "action": "slow_query",
                "status": "succeeded",
                "duration_ms": 431,
            },
        ],
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")

    events = recent_events(
        tmp_path,
        filters=DiagnosticFilter(query="IREN"),
    )

    assert len(events) == 1
    assert events[0]["ticker"] == "IREN.US"
    assert "app_version" not in events[0]


def test_status_uses_file_metadata_and_recent_important_counts(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "diagnostics-2026-07-30-a-001.jsonl",
        [
            {
                "timestamp": "2026-07-30T10:01:00+08:00",
                "level": "warning",
                "module": "ui",
                "action": "ui_stall",
                "status": "observed",
            },
            {
                "timestamp": "2026-07-30T10:02:00+08:00",
                "level": "warning",
                "module": "sqlite",
                "action": "slow_query",
                "status": "succeeded",
            },
        ],
    )

    status = diagnostic_status(tmp_path)

    assert status.file_count == 1
    assert status.total_bytes > 0
    assert status.stall_count == 1
    assert status.slow_query_count == 1
    assert status.health == "normal"
