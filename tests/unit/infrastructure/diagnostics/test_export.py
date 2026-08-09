from __future__ import annotations

import json
import zipfile
from pathlib import Path

from stock_toolbox.infrastructure.diagnostics.export import export_diagnostics


def test_export_contains_only_sanitized_whitelisted_entries(
    tmp_path: Path,
) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    (root / "diagnostics-2026-07-30-a-001.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-07-30T10:00:00+08:00",
                "app_version": "0.9.6",
                "session_id": "session",
                "level": "error",
                "module": "ai",
                "action": "quality",
                "status": "failed",
                "ticker": "IREN.US",
                "details": {
                    "model": "flash",
                    "message": "Bearer abcdefghijklmnop",
                },
                "api_key": "sk-12345678901234567890",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    target = tmp_path / "diagnostics.zip"

    export_diagnostics(
        root,
        target,
        environment={"app_version": "0.9.6", "environment": "integration"},
    )

    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {
            "README.txt",
            "environment.json",
            "summary.json",
            "logs/diagnostics.jsonl",
        }
        content = b"".join(archive.read(name) for name in archive.namelist())
    assert b"sk-12345678901234567890" not in content
    assert b"abcdefghijklmnop" not in content
    assert b"IREN.US" in content
