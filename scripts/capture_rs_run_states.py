#!/usr/bin/env python3
"""Capture deterministic light-mode RS run states for visual regression."""

from __future__ import annotations

import argparse
import tempfile
from dataclasses import replace
from datetime import date
from pathlib import Path
from time import monotonic
from typing import cast

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest

try:
    from scripts.qml_capture import require_qml_object, save_window
except ModuleNotFoundError:
    from qml_capture import require_qml_object, save_window
from stock_toolbox.analyses.rs_strength.application.models import (
    RunProgress,
    RunRequest,
    RunResult,
    RunStatus,
)
from stock_toolbox.composition import build_application
from stock_toolbox.desktop_qml.app import build_pilot_engine
from stock_toolbox.desktop_qml.rs_history_bridge import RsHistoryBridge
from stock_toolbox.desktop_qml.rs_run_bridge import RsRunBridge
from stock_toolbox.desktop_qml.shell_bridge import ShellBridge
from stock_toolbox.desktop_qml.theme_bridge import ThemeBridge
from stock_toolbox.runtime.environment import RuntimeEnvironment

_SYMBOLS = (
    "IREN",
    "NVDA",
    "AMD",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "AVGO",
    "MU",
    "TSM",
    "PLTR",
)


def _save(window: QQuickWindow, path: Path) -> None:
    save_window(window, path, wait_ms=120)


def _visual_items(root: QQuickItem) -> tuple[QQuickItem, ...]:
    descendants: list[QQuickItem] = []
    pending = list(root.childItems())
    while pending:
        item = pending.pop()
        descendants.append(item)
        pending.extend(item.childItems())
    return tuple(descendants)


def _hover(
    window: QQuickWindow,
    object_name: str,
) -> None:
    candidates = [
        item
        for item in _visual_items(window.contentItem())
        if item.objectName() == object_name
        and item.property("visible")
        and item.property("tipText")
    ]
    target = (
        min(
            candidates,
            key=lambda item: item.mapToScene(QPointF(0, 0)).y(),
        )
        if candidates
        else None
    )
    if target is None:
        target = window.findChild(QQuickItem, object_name)
    if target is None:
        raise RuntimeError(f"hover target is unavailable: {object_name}")
    center = target.mapToScene(
        QPointF(target.width() / 2, target.height() / 2)
    ).toPoint()
    QTest.mouseMove(window, center)
    QTest.qWait(420)


def _clear_hover(window: QQuickWindow) -> None:
    QTest.mouseMove(window, QPoint(window.width() - 8, 8))
    QTest.qWait(80)


def _capture(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stock-toolbox-rs-states-") as home:
        application = build_application(
            RuntimeEnvironment.SCENARIO,
            home=Path(home),
            scenario_run_id="rs-run-state-evidence",
        )
        application.import_securities(", ".join(_SYMBOLS))
        # Keep this evidence fixture in three sufficiently large groups.
        # Classification scoring needs comparable peer groups, and this makes
        # the scored-status tooltip visible without touching production data.
        evidence_classifications = tuple(
            application.master_data.create_classification(f"审计样本 {label}")
            for label in ("A", "B", "C")
        )
        for index, security in enumerate(application.master_data.list_securities()):
            application.master_data.set_security_classifications(
                security.id,
                (evidence_classifications[index % len(evidence_classifications)].id,),
            )
        watchlist = application.master_data.create_watchlist("科技成长")
        application.master_data.add_watchlist_members(
            watchlist.id,
            tuple(
                (security.id, security.bindings[0].id)
                for security in application.master_data.list_securities()
            ),
        )
        result = application.run(
            RunRequest(
                watchlist.id,
                "SPY.US",
                date(2026, 7, 24),
                ("3M", "6M", "1Y"),
                None,
            )
        )

        qt_application = cast(QGuiApplication | None, QGuiApplication.instance())
        if qt_application is None:
            qt_application = QGuiApplication([])
        engine = build_pilot_engine(application, RuntimeEnvironment.SCENARIO)
        shell = cast(ShellBridge, engine.rootContext().contextProperty("shellBridge"))
        bridge = cast(RsRunBridge, engine.rootContext().contextProperty("rsRunBridge"))
        history = cast(
            RsHistoryBridge,
            engine.rootContext().contextProperty("rsHistoryBridge"),
        )
        theme = cast(ThemeBridge, engine.rootContext().contextProperty("themeBridge"))
        bridge.select_watchlist(watchlist.id)
        bridge.set_end_date("2026-07-24")
        theme.set_evidence_mode("light")
        shell.navigate("rs_strength.run")

        window = cast(QQuickWindow, engine.rootObjects()[0])
        window.setWidth(1280)
        window.setHeight(800)
        window.show()
        _save(window, output / "01-ready.png")

        bridge._running = True
        bridge._started_monotonic = monotonic() - 18
        bridge._update_elapsed()
        bridge._on_progress(
            RunProgress("FETCHING", 67, 181, "NVDA.US", 64, 2)
        )
        _save(window, output / "02-fetching.png")

        bridge._on_progress(
            RunProgress("CALCULATING", 100, 180, "AAPL.US", 174, 6)
        )
        _save(window, output / "03-calculating.png")

        bridge._canceling = True
        bridge._stage_label = "正在取消"
        bridge._stage_detail = "等待当前请求或计算块到达安全检查点"
        bridge._status_text = "正在取消 · 等待当前安全检查点"
        bridge.changed.emit()
        _save(window, output / "04-canceling.png")

        bridge._on_finished(
            RunResult(
                RunStatus.FAILED,
                error_code="BENCHMARK_FETCH_FAILED",
            )
        )
        _save(window, output / "05-failed.png")

        if result.run_id is not None:
            history.select_run(result.run_id)
        shell.navigate("rs_strength.history")
        _save(window, output / "06-completed-history.png")

        history_page = require_qml_object(
            window, "rsHistoryPage", "RS history page"
        )
        history_page.setProperty("showClassifications", False)
        _save(window, output / "07-stock-range.png")

        scenario_paths = application.paths
        application.paths = replace(
            scenario_paths,
            environment=RuntimeEnvironment.PRODUCTION,
        )
        history.changed.emit()
        _save(window, output / "08-ai-unconfigured.png")

        application.paths = scenario_paths
        history._report_task = cast(object, object())  # visual state only
        history.changed.emit()
        _save(window, output / "09-ai-running.png")
        history._report_task = None
        application.generate_rs_strength_report(result.run_id)
        history.select_run(result.run_id)
        _save(window, output / "10-ai-report.png")

        shell.navigate("rs_strength.run")
        bridge._running = True
        bridge._last_status = ""
        bridge._on_progress(
            RunProgress("FETCHING", 67, 181, "NVDA.US", 64, 2)
        )
        window.setWidth(1120)
        window.setHeight(720)
        _save(window, output / "11-fetching-compact.png")

        window.setWidth(1280)
        window.setHeight(800)
        bridge._running = False
        bridge.changed.emit()
        _hover(window, "sidebarRsHelp")
        _save(window, output / "12-sidebar-rs-help.png")
        _clear_hover(window)

        window.setProperty("importOpen", True)
        QTest.qWait(100)
        _hover(window, "csvFormatHelp")
        _save(window, output / "13-csv-format-help.png")
        window.setProperty("importOpen", False)
        _clear_hover(window)

        shell.navigate("rs_strength.history")
        QTest.qWait(100)
        # Navigation recreates the history page.  Resolve the current page
        # before changing its local projection, otherwise the screenshot can
        # target an invisible, stale QML object.
        history_page = require_qml_object(
            window,
            "rsHistoryPage",
            "RS history page after navigation",
        )
        history_page.setProperty("showClassifications", True)
        QTest.qWait(100)
        _hover(window, "classificationStatusHelp")
        _save(window, output / "14-classification-status-help.png")
        window.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    _capture(arguments.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
