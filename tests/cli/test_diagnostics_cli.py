from __future__ import annotations

import json
from pathlib import Path

from stock_toolbox.cli import main
from stock_toolbox.runtime.environment import RuntimeEnvironment
from stock_toolbox.runtime.paths import RuntimePaths


def _seed(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths.resolve(RuntimeEnvironment.INTEGRATION, home=tmp_path)
    paths.log_root.mkdir(parents=True)
    (paths.log_root / "diagnostics-2026-07-30-a-001.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-07-30T10:00:00+08:00",
                "level": "warning",
                "module": "ui",
                "action": "ui_stall",
                "status": "observed",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def test_diagnostics_status_reports_local_retention_state(
    tmp_path: Path,
    capsys,
) -> None:
    _seed(tmp_path)

    code = main(
        [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "diagnostics",
            "status",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"]["retention_days"] == 7
    assert payload["diagnostics"]["max_bytes"] == 100 * 1024 * 1024
    assert payload["diagnostics"]["stall_count"] == 1


def test_diagnostics_export_and_confirmed_clear(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    target = tmp_path / "diagnostics.zip"

    assert main(
        [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "diagnostics",
            "export",
            "--output",
            str(target),
        ]
    ) == 0
    assert target.exists()
    assert main(
        [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "diagnostics",
            "clear",
        ]
    ) == 64
    assert tuple(paths.log_root.glob("diagnostics-*.jsonl"))
    assert main(
        [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "diagnostics",
            "clear",
            "--confirm",
        ]
    ) == 0
    assert tuple(paths.log_root.glob("diagnostics-*.jsonl")) == ()
