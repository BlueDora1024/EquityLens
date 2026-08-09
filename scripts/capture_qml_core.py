#!/usr/bin/env python3
"""Capture the frozen QML core scene in light and dark appearances."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import cast

from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

try:
    from scripts.qml_capture import save_window
except ModuleNotFoundError:
    from qml_capture import save_window
from stock_toolbox.composition import build_application
from stock_toolbox.desktop_qml.app import build_pilot_engine
from stock_toolbox.desktop_qml.rs_run_bridge import RsRunBridge
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
    "CRWD",
    "ARM",
    "DELL",
    "SMCI",
    "ORCL",
    "ANET",
)


def _write_comparisons(
    baseline_path: Path,
    actual_path: Path,
    output: Path,
    mode: str,
) -> None:
    baseline = QImage(str(baseline_path))
    actual = QImage(str(actual_path))
    if baseline.isNull() or actual.isNull():
        raise RuntimeError(f"unable to load evidence images for {mode}")
    if actual.size() != baseline.size():
        actual = actual.scaled(baseline.size())

    comparison = QImage(
        baseline.width() * 2,
        baseline.height(),
        QImage.Format.Format_ARGB32,
    )
    comparison.fill(0)
    painter = QPainter(comparison)
    painter.drawImage(0, 0, baseline)
    painter.drawImage(baseline.width(), 0, actual)
    painter.end()
    if not comparison.save(str(output / f"comparison-{mode}.png")):
        raise RuntimeError(f"unable to save comparison evidence for {mode}")

    overlay = baseline.copy()
    painter = QPainter(overlay)
    painter.setOpacity(0.5)
    painter.drawImage(0, 0, actual)
    painter.end()
    if not overlay.save(str(output / f"overlay-{mode}.png")):
        raise RuntimeError(f"unable to save overlay evidence for {mode}")


def _capture(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stock-toolbox-qml-core-") as raw_home:
        application = build_application(
            RuntimeEnvironment.SCENARIO,
            home=Path(raw_home),
            scenario_run_id="qml-core-evidence",
        )
        application.import_securities(", ".join(_SYMBOLS))
        watchlist = application.master_data.create_watchlist("科技观察")
        application.master_data.add_watchlist_members(
            watchlist.id,
            tuple(
                (security.id, security.bindings[0].id)
                for security in application.master_data.list_securities()
                if security.bindings
            ),
        )

        qt_application = cast(QGuiApplication | None, QGuiApplication.instance())
        if qt_application is None:
            qt_application = QGuiApplication([])
        engine = build_pilot_engine(application, RuntimeEnvironment.SCENARIO)
        bridge = cast(RsRunBridge, engine.rootContext().contextProperty("rsRunBridge"))
        theme = cast(ThemeBridge, engine.rootContext().contextProperty("themeBridge"))
        bridge.select_watchlist(watchlist.id)
        bridge.set_end_date("2026-07-24")
        bridge.set_custom_range(True, "2026-04-24", "2026-07-24")

        window = cast(QQuickWindow, engine.rootObjects()[0])
        window.setWidth(1280)
        window.setHeight(800)
        window.show()
        QTest.qWait(120)
        product_tour = window.findChild(QObject, "productTourOverlay")
        if product_tour is None:
            raise RuntimeError("product tour overlay not found")
        for mode in ("light", "dark"):
            theme.set_evidence_mode(mode)
            QTest.qWait(120)
            target = output / f"rs-run-{mode}.png"
            save_window(window, target)
            window.setProperty("settingsOpen", True)
            QTest.qWait(80)
            settings_target = output / f"settings-{mode}.png"
            save_window(window, settings_target)
            window.setProperty("settingsOpen", False)
            window.setProperty("firstRunRequired", True)
            window.setProperty("settingsOpen", True)
            QTest.qWait(80)
            onboarding_target = output / f"first-run-{mode}.png"
            save_window(window, onboarding_target)
            window.setProperty("firstRunRequired", False)
            window.setProperty("settingsOpen", False)
            window.setProperty("productTourOpen", True)
            for slide in range(5):
                product_tour.setProperty("currentSlide", slide)
                QTest.qWait(220)
                save_window(
                    window,
                    output / f"product-tour-{mode}-{slide + 1}.png",
                )
            window.setProperty("productTourOpen", False)
        window.close()

        repository_root = Path(__file__).resolve().parents[1]
        for mode in ("light", "dark"):
            _write_comparisons(
                repository_root
                / "docs"
                / "design"
                / "qml-soft-glass"
                / f"baseline-{mode}.png",
                output / f"rs-run-{mode}.png",
                output,
                mode,
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/qml-core"))
    args = parser.parse_args()
    _capture(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
