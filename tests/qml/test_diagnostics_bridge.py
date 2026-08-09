from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl

from stock_toolbox.composition import build_application
from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticStatus,
)
from stock_toolbox.desktop_qml.settings_bridge import SettingsBridge
from stock_toolbox.infrastructure.diagnostics.jsonl import JsonlDiagnosticLogger
from stock_toolbox.runtime.environment import RuntimeEnvironment


def _application(tmp_path: Path):
    logger = JsonlDiagnosticLogger(
        tmp_path / "Library" / "Logs" / "EquityLens" / "Integration",
        app_version="test",
    )
    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
        diagnostics_override=logger,
    )
    return application, logger


def test_advanced_page_loads_diagnostic_status_off_main_thread(
    qtbot,
    tmp_path: Path,
) -> None:
    application, logger = _application(tmp_path)
    logger.emit(
        DiagnosticEvent(
            DiagnosticLevel.WARNING,
            "sqlite",
            "slow_query",
            DiagnosticStatus.SUCCEEDED,
            duration_ms=420,
            ticker="IREN.US",
        )
    )
    assert logger.flush()
    bridge = SettingsBridge(application)

    with qtbot.waitSignal(bridge.diagnostics_finished, timeout=5_000):
        bridge.select_page("advanced")

    assert bridge.diagnostic_loading is False
    assert bridge.diagnostic_status == "正常"
    assert bridge.diagnostic_size_text.endswith(("KB", "B"))
    assert bridge.diagnostic_events[0]["ticker"] == "IREN.US"
    assert bridge.diagnostic_summary == "卡顿 0 · 慢查询 1 · 错误 0"
    assert logger.close()


def test_diagnostic_export_uses_default_zip_and_contains_no_database(
    qtbot,
    tmp_path: Path,
) -> None:
    application, logger = _application(tmp_path)
    bridge = SettingsBridge(application)
    target = tmp_path / "exported.zip"

    with qtbot.waitSignal(bridge.diagnostics_finished, timeout=5_000):
        assert bridge.export_diagnostics(QUrl.fromLocalFile(str(target)).toString())

    assert target.exists()
    assert target.suffix == ".zip"
    assert application.paths.database.name.encode() not in target.read_bytes()
    assert bridge.diagnostic_export_default_url.startswith("file:")
    assert logger.close()


def test_clear_diagnostics_requires_exact_second_confirmation(
    qtbot,
    tmp_path: Path,
) -> None:
    application, logger = _application(tmp_path)
    bridge = SettingsBridge(application)
    logger.emit(
        DiagnosticEvent(
            DiagnosticLevel.INFO,
            "application",
            "startup",
            DiagnosticStatus.SUCCEEDED,
        )
    )
    assert logger.flush()

    bridge.request_clear_diagnostics()

    assert bridge.diagnostic_clear_pending is True
    assert bridge.confirm_clear_diagnostics("确认") is False
    with qtbot.waitSignal(bridge.diagnostics_finished, timeout=5_000):
        assert bridge.confirm_clear_diagnostics("清空日志") is True

    assert bridge.diagnostic_clear_pending is False
    assert bridge.diagnostic_events == []
    assert logger.close()
