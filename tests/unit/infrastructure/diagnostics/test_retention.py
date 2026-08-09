from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from stock_toolbox.infrastructure.diagnostics.jsonl import enforce_retention

NOW = datetime(2026, 7, 30, 15, 30, tzinfo=UTC)


def _file(
    path: Path,
    size: int,
    *,
    modified: datetime,
    accessed: datetime | None = None,
) -> Path:
    path.write_bytes(b"x" * size)
    os.utime(
        path,
        (
            (accessed or modified).timestamp(),
            modified.timestamp(),
        ),
    )
    return path


def test_retention_removes_expired_files_before_capacity_lru(
    tmp_path: Path,
) -> None:
    expired = _file(
        tmp_path / "diagnostics-expired.jsonl",
        300,
        modified=NOW - timedelta(days=8),
    )
    least_recent = _file(
        tmp_path / "diagnostics-old.jsonl",
        300,
        modified=NOW - timedelta(days=2),
        accessed=NOW - timedelta(days=2),
    )
    recent = _file(
        tmp_path / "diagnostics-recent.jsonl",
        300,
        modified=NOW - timedelta(days=1),
        accessed=NOW - timedelta(hours=1),
    )
    active = _file(
        tmp_path / "diagnostics-active.jsonl",
        300,
        modified=NOW,
    )

    report = enforce_retention(
        tmp_path,
        active_path=active,
        now=NOW,
        retention_days=7,
        max_total_bytes=650,
    )

    assert expired in report.removed_expired
    assert least_recent in report.removed_lru
    assert recent.exists()
    assert active.exists()
    assert report.total_bytes == 600


def test_retention_never_deletes_active_file_above_limit(tmp_path: Path) -> None:
    active = _file(
        tmp_path / "diagnostics-active.jsonl",
        700,
        modified=NOW,
    )

    report = enforce_retention(
        tmp_path,
        active_path=active,
        now=NOW,
        retention_days=7,
        max_total_bytes=100,
    )

    assert active.exists()
    assert report.total_bytes == 700
