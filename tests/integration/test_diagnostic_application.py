from __future__ import annotations

import json
from pathlib import Path

from stock_toolbox.composition import build_application
from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticStatus,
)
from stock_toolbox.core.operations.executor import (
    ExecuteReservedOperation,
    OperationCandidate,
)
from stock_toolbox.core.operations.registry import OperationStatus
from stock_toolbox.infrastructure.diagnostics.jsonl import JsonlDiagnosticLogger
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_composition_correlates_operation_and_sql_diagnostics(
    tmp_path: Path,
) -> None:
    logger = JsonlDiagnosticLogger(
        tmp_path / "diagnostics",
        app_version="test",
    )
    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
        diagnostics_override=logger,
    )
    application.registry.reserve("run-1", "key-1", "rs_run")

    ExecuteReservedOperation(application.registry).execute(
        "run-1",
        lambda _context: OperationCandidate(
            OperationStatus.SUCCEEDED,
            {"success": 1, "total": 1},
        ),
    )
    application.master_data.list_securities()

    assert logger.flush()
    events = [
        json.loads(line)
        for path in logger.root.glob("diagnostics-*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any(
        event.get("task_id") == "run-1"
        and event["module"] == "operations"
        and event["status"] == "succeeded"
        for event in events
    )
    assert any(event["module"] == "sqlite" for event in events)
    assert logger.close()


def test_full_reset_clears_old_logs_and_keeps_writer_usable(
    tmp_path: Path,
) -> None:
    logger = JsonlDiagnosticLogger(
        tmp_path / "diagnostics",
        app_version="test",
    )
    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
        diagnostics_override=logger,
    )
    logger.emit(
        DiagnosticEvent(
            DiagnosticLevel.INFO,
            "application",
            "before_reset",
            DiagnosticStatus.SUCCEEDED,
        )
    )
    assert logger.flush()

    application.reset_local_data()
    logger.emit(
        DiagnosticEvent(
            DiagnosticLevel.INFO,
            "application",
            "after_reset",
            DiagnosticStatus.SUCCEEDED,
        )
    )

    assert logger.flush()
    content = "".join(
        path.read_text(encoding="utf-8")
        for path in logger.root.glob("diagnostics-*.jsonl")
    )
    assert "before_reset" not in content
    assert "after_reset" in content
    assert logger.close()
