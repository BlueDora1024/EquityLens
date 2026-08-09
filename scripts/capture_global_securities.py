#!/usr/bin/env python3
"""Capture deterministic light-mode evidence for the global securities flow."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import cast

from PySide6.QtCore import QProcess
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

try:
    from scripts.qml_capture import require_qml_object, save_window
except ModuleNotFoundError:
    from qml_capture import require_qml_object, save_window
from stock_toolbox.composition import build_application
from stock_toolbox.desktop_qml.app import build_pilot_engine
from stock_toolbox.desktop_qml.master_data_bridge import MasterDataBridge
from stock_toolbox.desktop_qml.shell_bridge import ShellBridge
from stock_toolbox.desktop_qml.theme_bridge import ThemeBridge
from stock_toolbox.runtime.environment import RuntimeEnvironment


def _save(window: QQuickWindow, output: Path, name: str) -> None:
    save_window(window, output / name, wait_ms=120)


def capture(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="global-securities-evidence-") as raw_home:
        application = build_application(
            RuntimeEnvironment.SCENARIO,
            home=Path(raw_home),
            scenario_run_id="global-securities-evidence",
        )
        application.import_securities("AAPL, AMD, IREN, MSFT, NVDA")
        selected = next(
            row
            for row in application.master_data.list_securities()
            if row.canonical_symbol == "IREN.US"
        )
        for name in ("AI 核心", "复盘观察"):
            watchlist = application.master_data.create_watchlist(name)
            application.master_data.add_watchlist_members(
                watchlist.id,
                ((selected.id, selected.bindings[0].id),),
            )

        qt_application = cast(
            QGuiApplication | None,
            QGuiApplication.instance(),
        )
        if qt_application is None:
            qt_application = QGuiApplication([])
        engine = build_pilot_engine(
            application,
            RuntimeEnvironment.SCENARIO,
        )
        shell = cast(
            ShellBridge,
            engine.rootContext().contextProperty("shellBridge"),
        )
        bridge = cast(
            MasterDataBridge,
            engine.rootContext().contextProperty("masterDataBridge"),
        )
        theme = cast(
            ThemeBridge,
            engine.rootContext().contextProperty("themeBridge"),
        )
        theme.set_evidence_mode("light")
        shell.navigate("securities")
        window = cast(QQuickWindow, engine.rootObjects()[0])
        window.setWidth(1280)
        window.setHeight(800)
        window.show()

        page = require_qml_object(
            window, "masterDataPage", "master data page"
        )
        _save(window, output, "01-securities-list.png")

        row = next(item for item in bridge.securities if item["id"] == selected.id)
        page.setProperty("selectedSecurity", row)
        page.setProperty("selectedEntity", row)
        bridge.load_security_snapshot(selected.id)
        for _attempt in range(100):
            if not bridge.snapshot_running:
                break
            QTest.qWait(50)
        if bridge.snapshot_running:
            raise RuntimeError("snapshot evidence timed out")
        _save(window, output, "02-security-detail.png")

        page.setProperty("tagManagerOpen", True)
        _save(window, output, "03-tag-manager.png")
        page.setProperty("tagManagerOpen", False)

        page.setProperty(
            "deleteImpact",
            bridge.security_delete_impact(selected.id),
        )
        page.setProperty("deleteConfirmOpen", True)
        _save(window, output, "04-delete-confirmation.png")
        page.setProperty("deleteConfirmOpen", False)

        window.setProperty("importOpen", True)
        import_text = require_qml_object(
            window, "importText", "import input"
        )
        _save(window, output, "05-import-empty.png")

        import_text.setProperty(
            "text",
            "\n".join(f"TEST{number:03d}" for number in range(1, 201)),
        )
        bridge._import_total = 200
        bridge._import_completed = 180
        bridge._import_progress = 0.9
        bridge._import_process = QProcess()
        bridge._status = "正在校验并分类 · 180/200"
        bridge._import_details = [
            {
                "symbol": f"TEST{number:03d}",
                "status": "IMPORTED",
                "reason": "",
                "category": "success",
            }
            for number in range(176, 181)
        ]
        bridge._import_summary = {"success": 180}
        bridge.import_changed.emit()
        bridge.changed.emit()
        _save(window, output, "06-import-progress.png")

        bridge._import_completed = 200
        bridge._import_progress = 1.0
        bridge._import_process = None
        bridge._status = "导入完成 · 成功 192 · 已存在 3 · 失败 3"
        bridge._import_summary = {
            "success": 192,
            "existing": 3,
            "duplicate": 2,
            "unavailable": 1,
            "excluded": 1,
            "invalid": 1,
        }
        bridge._import_details = [
            {
                "symbol": "NVDA",
                "status": "IMPORTED",
                "reason": "",
                "category": "success",
            },
            {
                "symbol": "AAPL",
                "status": "EXISTING",
                "reason": "",
                "category": "existing",
            },
            {
                "symbol": "TQQQ",
                "status": "EXCLUDED",
                "reason": "杠杆 ETF，不属于美股正股",
                "category": "excluded",
            },
            {
                "symbol": "MISSING",
                "status": "UNAVAILABLE",
                "reason": "供应商没有返回该证券",
                "category": "unavailable",
            },
        ]
        bridge.import_changed.emit()
        bridge.changed.emit()
        _save(window, output, "07-import-result.png")

        window.setProperty("importOpen", False)
        target = application.master_data.create_classification("复盘核心")
        rows_by_symbol = {
            item.canonical_symbol: item
            for item in application.master_data.list_securities()
        }
        application.master_data.set_security_classifications(
            rows_by_symbol["AAPL.US"].id,
            (target.id,),
        )
        full_ids = tuple(
            application.master_data.create_classification(name).id
            for name in ("标签一", "标签二", "标签三")
        )
        application.master_data.set_security_classifications(
            rows_by_symbol["AMD.US"].id,
            full_ids,
        )
        bridge.changed.emit()
        shell.navigate("classifications")
        page.setProperty("selectedSecurity", None)
        target_row = next(
            item for item in bridge.classifications if item["id"] == target.id
        )
        page.setProperty("selectedEntity", target_row)
        bridge.select_classification(target.id)
        _save(window, output, "08-tag-member-detail.png")

        page.setProperty("classificationMemberOpen", True)
        overlay = require_qml_object(
            window,
            "classificationMemberOverlay",
            "classification member overlay",
        )
        overlay.setProperty(
            "selectedIds",
            [
                rows_by_symbol["AMD.US"].id,
                rows_by_symbol["NVDA.US"].id,
            ],
        )
        _save(window, output, "09-tag-member-selection.png")

        bridge.add_classification_members(
            target.id,
            [
                rows_by_symbol["AMD.US"].id,
                rows_by_symbol["NVDA.US"].id,
            ],
        )
        _save(window, output, "10-tag-member-partial-result.png")

        page.setProperty("classificationMemberOpen", False)
        shell.navigate("watchlists")
        pool_row = next(
            item for item in bridge.watchlists if item["name"] == "AI 核心"
        )
        page.setProperty("selectedEntity", pool_row)
        bridge.select_watchlist(str(pool_row["id"]))
        name_input = require_qml_object(
            window, "watchlistNameInput", "watchlist name input"
        )
        name_input.setProperty("text", pool_row["name"])
        _save(window, output, "11-watchlist-detail.png")

        page.setProperty("watchlistMemberOpen", True)
        pool_overlay = require_qml_object(
            window,
            "watchlistMemberOverlay",
            "watchlist member overlay",
        )
        candidates = bridge.watchlist_candidates
        chosen = candidates[:2]
        pool_overlay.setProperty(
            "selectedIds",
            [item["id"] for item in chosen],
        )
        _save(window, output, "12-watchlist-select-securities.png")

        selections = [
            {
                "securityId": item["id"],
                "displaySymbol": item["displaySymbol"],
                "name": item["name"],
                "bindings": item["classifications"],
                "bindingId": item["classifications"][0]["bindingId"],
            }
            for item in chosen
        ]
        pool_overlay.setProperty("selections", selections)
        pool_overlay.setProperty("step", 2)
        _save(window, output, "13-watchlist-adjust-bindings.png")

        result = bridge.add_watchlist_members_batch(
            str(pool_row["id"]),
            [
                {
                    "securityId": item["securityId"],
                    "bindingId": item["bindingId"],
                }
                for item in selections
            ],
        )
        pool_overlay.setProperty("addedCount", result["added"])
        pool_overlay.setProperty("step", 3)
        _save(window, output, "14-watchlist-add-success.png")

        page.setProperty("watchlistMemberOpen", False)
        _save(window, output, "15-watchlist-members-added.png")

        first_member = bridge.selected_watchlist_members[0]
        if len(first_member["bindings"]) > 1:
            bridge.update_watchlist_member_binding(
                str(pool_row["id"]),
                str(first_member["securityId"]),
                str(first_member["bindings"][1]["bindingId"]),
            )
        _save(window, output, "16-watchlist-binding-updated.png")
        window.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/global-securities"),
    )
    args = parser.parse_args()
    capture(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
