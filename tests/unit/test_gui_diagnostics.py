from __future__ import annotations

import json
from pathlib import Path

from stock_toolbox.composition import build_application
from stock_toolbox.gui import _record_lifecycle, _shutdown_application
from stock_toolbox.infrastructure.diagnostics.jsonl import JsonlDiagnosticLogger
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_gui_lifecycle_records_ready_and_flushes_exit(tmp_path: Path) -> None:
    logger = JsonlDiagnosticLogger(tmp_path / "logs", app_version="test")
    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
        diagnostics_override=logger,
    )

    _record_lifecycle(application, "ready")
    _shutdown_application(application)

    events = [
        json.loads(line)
        for path in logger.root.glob("diagnostics-*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert [event["action"] for event in events if event["module"] == "application"] == [
        "ready",
        "exit",
    ]
    assert application.registry.close_admission() is False
