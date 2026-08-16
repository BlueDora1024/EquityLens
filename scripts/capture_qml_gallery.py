#!/usr/bin/env python3
"""Capture representative production QML pages with deterministic data."""

from __future__ import annotations

import argparse
import tempfile
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

from PySide6.QtCore import QMetaObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

try:
    from scripts.qml_capture import require_qml_object, save_window
except ModuleNotFoundError:
    from qml_capture import require_qml_object, save_window
from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import (
    SUPPORTED_INTERVALS,
)
from stock_toolbox.analyses.resource_budget import AnalysisBudgetSnapshot
from stock_toolbox.analyses.rs_strength.application.models import RunRequest
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
)
from stock_toolbox.composition import build_application
from stock_toolbox.core.market_data.fallback import FallbackOffer
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.operations.failure_policy import (
    AnalysisReliability,
    FailureCode,
)
from stock_toolbox.core.operations.registry import OperationStatus
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback
from stock_toolbox.desktop_qml.app import build_pilot_engine
from stock_toolbox.desktop_qml.extreme_deviation_bridge import (
    ExtremeDeviationBridge,
)
from stock_toolbox.desktop_qml.failure_presentation import (
    FailureState,
    advance_feedback,
    finish_outcome,
)
from stock_toolbox.desktop_qml.master_data_bridge import MasterDataBridge
from stock_toolbox.desktop_qml.rs_history_bridge import RsHistoryBridge
from stock_toolbox.desktop_qml.rs_run_bridge import RsRunBridge
from stock_toolbox.desktop_qml.settings_bridge import SettingsBridge
from stock_toolbox.desktop_qml.shell_bridge import ShellBridge
from stock_toolbox.desktop_qml.theme_bridge import ThemeBridge
from stock_toolbox.desktop_qml.turning_point_bridge import TurningPointBridge
from stock_toolbox.runtime.environment import RuntimeEnvironment

_SYMBOLS = ("IREN", "NVDA", "AMD", "AAPL", "MSFT", "PLTR")


def _capture(output: Path, *, width: int = 1280, height: int = 800) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stock-toolbox-qml-gallery-") as home:
        application = build_application(
            RuntimeEnvironment.SCENARIO,
            home=Path(home),
            scenario_run_id="gallery",
        )
        application.import_securities(", ".join(_SYMBOLS))
        watchlist = application.master_data.create_watchlist("科技成长")
        application.master_data.add_watchlist_members(
            watchlist.id,
            tuple(
                (security.id, security.bindings[0].id)
                for security in application.master_data.list_securities()
            ),
        )
        end_date = date(2026, 7, 24)
        rs_result = application.run(
            RunRequest(
                watchlist.id,
                "SPY.US",
                end_date,
                ("3M", "6M", "1Y"),
                None,
            )
        )
        if rs_result.run_id is not None:
            application.generate_rs_strength_report(rs_result.run_id)
        turning = application.run_turning_point(
            TurningPointRequest(
                watchlist.id,
                (
                    CandleInterval.MIN_30,
                    CandleInterval.MIN_60,
                    CandleInterval.DAY,
                ),
                end_date,
            )
        )
        extreme = application.run_extreme_deviation(
            ExtremeDeviationRequest(
                "",
                SUPPORTED_INTERVALS,
                end_date,
                security_id=application.master_data.get_watchlist(watchlist.id)
                .memberships[0]
                .security_id,
            )
        )

        qt_application = cast(QGuiApplication | None, QGuiApplication.instance())
        if qt_application is None:
            qt_application = QGuiApplication([])
        engine = build_pilot_engine(application, RuntimeEnvironment.SCENARIO)
        shell = cast(ShellBridge, engine.rootContext().contextProperty("shellBridge"))
        theme = cast(ThemeBridge, engine.rootContext().contextProperty("themeBridge"))
        settings = cast(
            SettingsBridge,
            engine.rootContext().contextProperty("settingsBridge"),
        )
        rs_run = cast(RsRunBridge, engine.rootContext().contextProperty("rsRunBridge"))
        master_data = cast(
            MasterDataBridge,
            engine.rootContext().contextProperty("masterDataBridge"),
        )
        rs_history = cast(
            RsHistoryBridge,
            engine.rootContext().contextProperty("rsHistoryBridge"),
        )
        turning_bridge = cast(
            TurningPointBridge,
            engine.rootContext().contextProperty("turningPointBridge"),
        )
        extreme_bridge = cast(
            ExtremeDeviationBridge,
            engine.rootContext().contextProperty("extremeDeviationBridge"),
        )
        rs_run.select_watchlist(watchlist.id)
        rs_run.set_end_date(end_date.isoformat())
        if rs_result.run_id is not None:
            rs_history.select_run(rs_result.run_id)
        turning_bridge.select_watchlist(watchlist.id)
        turning_bridge.set_end_date(end_date.isoformat())
        turning_bridge.load_support_data()
        for _attempt in range(50):
            if turning_bridge.support_loaded:
                break
            QTest.qWait(20)
        if turning.run is not None:
            turning_bridge.select_run(turning.run.run_id)
        if turning_bridge._all_results:
            turning_bridge._all_results[0]["riskLabels"] = [
                "小市值 · 低于 20 亿美元",
            ]
            turning_bridge.changed.emit()
        extreme_bridge.load_support_data()
        for _attempt in range(50):
            if extreme_bridge.securities_loaded:
                break
            QTest.qWait(20)
        extreme_bridge.select_watchlist(watchlist.id)
        extreme_bridge.set_end_date(end_date.isoformat())
        for _attempt in range(50):
            if not extreme_bridge.calendar_loading:
                break
            QTest.qWait(20)
        if extreme.run is not None:
            extreme_bridge.select_run(extreme.run.run_id)

        window = cast(QQuickWindow, engine.rootObjects()[0])
        window.setWidth(width)
        window.setHeight(height)
        window.show()

        def save_state(filename: str) -> None:
            save_window(window, output / filename, wait_ms=100)

        def set_rs_state(
            state: FailureState,
            *,
            running: bool,
            failed_count: int = 0,
            status: str = "正在获取行情",
        ) -> None:
            rs_run._failure_state = state
            rs_run._running = running
            rs_run._failed_count = failed_count
            rs_run._status_text = status
            rs_run._stage_label = "获取收盘结果" if running else status
            rs_run._stage_detail = "正在处理科技成长股票池" if running else "运行状态已冻结"
            rs_run._progress = 0.46 if running else 1.0
            rs_run.changed.emit()

        retrying = advance_feedback(
            FailureState(),
            RunFeedback(
                FeedbackKind.RETRYING,
                FailureCode.TIMEOUT,
                "AMD.US",
                "1d",
                attempt=2,
                max_attempts=3,
                wait_seconds=2,
            ),
        )
        throttled = advance_feedback(
            FailureState(),
            RunFeedback(
                FeedbackKind.THROTTLED,
                FailureCode.RATE_LIMITED,
                "NVDA.US",
                "1d",
                wait_seconds=8,
                active_concurrency=1,
            ),
        )
        recovered = advance_feedback(
            retrying,
            RunFeedback(
                FeedbackKind.RECOVERED,
                symbol="AMD.US",
                interval="1d",
            ),
        )
        evidence = advance_feedback(
            FailureState(),
            RunFeedback(
                FeedbackKind.ITEM_SKIPPED,
                FailureCode.TIMEOUT,
                "AMD.US",
                "1d",
            ),
        )
        evidence = advance_feedback(
            evidence,
            RunFeedback(
                FeedbackKind.CIRCUIT_OPEN,
                FailureCode.RATE_LIMITED,
                "NVDA.US",
                "1w",
            ),
        )
        exact_eighty = finish_outcome(
            evidence,
            "PARTIAL",
            AnalysisReliability(
                8,
                2,
                0,
                Decimal("0.8"),
                True,
                FailureCode.RATE_LIMITED.value,
            ),
        )
        below_eighty = finish_outcome(
            evidence,
            "FAILED",
            AnalysisReliability(
                7,
                2,
                1,
                Decimal("0.7"),
                True,
                FailureCode.RATE_LIMITED.value,
            ),
        )
        auth_failure = finish_outcome(
            evidence,
            "FAILED",
            AnalysisReliability(
                7,
                2,
                1,
                Decimal("0.7"),
                False,
                FailureCode.AUTHENTICATION_FAILED.value,
            ),
        )
        disk_blocked = finish_outcome(
            FailureState(),
            "FAILED",
            None,
            FailureCode.STORAGE_UNAVAILABLE.value,
        )

        pages = (
            ("securities", "global-securities"),
            ("watchlists", "watchlists"),
            ("rs_strength.run", "rs-run"),
            ("rs_strength.history", "rs-history"),
            ("turning_point.run", "turning-run"),
            ("turning_point.history", "turning-history"),
            ("extreme_deviation.run", "extreme-run"),
            ("extreme_deviation.results", "extreme-results"),
        )
        for mode in ("light", "dark"):
            theme.set_evidence_mode(mode)
            for page_id, filename in pages:
                if page_id == "extreme_deviation.run":
                    extreme_bridge._failure_state = FailureState()
                    extreme_bridge._running = False
                    extreme_bridge.changed.emit()
                shell.navigate(page_id)
                QTest.qWait(100)
                if page_id == "extreme_deviation.run":
                    idle_progress = require_qml_object(
                        window,
                        "extremeProgressPanel",
                        "extreme deviation idle progress panel",
                    )
                    idle_progress_height = float(idle_progress.property("height"))
                    if idle_progress_height > 80:
                        raise RuntimeError(
                            "idle extreme progress panel exceeds 80 px: "
                            f"{idle_progress_height:.1f}; "
                            f"running={extreme_bridge.running}, "
                            f"recovery={extreme_bridge.recovery_visible}, "
                            f"outcome={extreme_bridge.outcome_visible}"
                        )
                target = output / f"{filename}-{mode}.png"
                save_window(window, target)
                if page_id == "turning_point.run":
                    turning_bridge._running = True
                    turning_bridge._progress = 0.4
                    turning_bridge._active_stage = 2
                    turning_bridge._status_text = "服务端指标 · 4/10 · IREN.US · 120m"
                    turning_bridge.changed.emit()
                    QTest.qWait(100)
                    save_state(f"turning-running-{mode}.png")
                    turning_bridge._running = False
                    turning_bridge._progress = 0.0
                    turning_bridge._active_stage = -1
                    turning_bridge._status_text = "就绪 · 选择股票池和周期"
                    turning_bridge.changed.emit()
                if page_id == "extreme_deviation.results":
                    if extreme.run is not None:
                        extreme_bridge.select_run(extreme.run.run_id)
                    extreme_page = require_qml_object(
                        window,
                        "extremeDeviationPage",
                        "extreme deviation page",
                    )
                    extreme_page.setProperty("detailOpen", True)
                    save_state(f"extreme-detail-{mode}.png")
                    extreme_bridge._report_text = (
                        "结论\n"
                        "四个周期均为买入偏离，短周期与长周期方向一致。\n\n"
                        "复盘重点\n"
                        "关注日线和周线偏离是否继续扩大，以及后续价格是否确认。"
                    )
                    extreme_bridge.changed.emit()
                    report_dialog = require_qml_object(
                        window,
                        "extremeReportDialog",
                        "extreme report dialog",
                    )
                    report_dialog.setProperty("visible", True)
                    QTest.qWait(100)
                    save_window(
                        window,
                        output / f"extreme-ai-dialog-{mode}.png",
                    )
                    report_dialog.setProperty("visible", False)
                    extreme_page.setProperty("detailOpen", False)
                if page_id == "rs_strength.history":
                    history_page = require_qml_object(window, "rsHistoryPage", "RS history page")
                    history_page.setProperty("reportDialogOpen", True)
                    QTest.qWait(100)
                    dialog_target = output / f"rs-history-ai-dialog-{mode}.png"
                    save_window(window, dialog_target)
                    history_page.setProperty("reportDialogOpen", False)
                if page_id == "turning_point.history":
                    turning_page = require_qml_object(
                        window, "turningPointPage", "turning point page"
                    )
                    turning_bridge._report_text = (
                        "整体反转聚集\n"
                        "IREN 在 30 分钟、1 小时和日线同时命中，短周期领先，"
                        "日线提供更高权重证据。\n\n"
                        "后续复盘\n优先确认长周期是否继续保持，避免只看单一周期。"
                    )
                    turning_bridge.changed.emit()
                    turning_page.setProperty("reportDialogOpen", True)
                    QTest.qWait(100)
                    save_window(
                        window,
                        output / f"turning-history-ai-dialog-{mode}.png",
                    )
                    turning_page.setProperty("reportDialogOpen", False)
                    if mode != "light":
                        continue
                    turning_page.setProperty("missOverlayOpen", True)
                    QTest.qWait(100)
                    miss_target = output / "turning-miss-reasons-light.png"
                    save_window(window, miss_target)
                    turning_page.setProperty("missOverlayOpen", False)
                    matched_rows = turning_bridge._all_results
                    turning_bridge._all_results = []
                    turning_bridge.changed.emit()
                    save_state("turning-zero-match-inline-light.png")
                    turning_bridge._all_results = matched_rows
                    turning_bridge.changed.emit()
                    if turning_bridge.select_result_interval("30m"):
                        save_state("turning-history-30m-light.png")
                        turning_bridge.select_result_interval("attention")
                    if turning_bridge._all_results:
                        turning_bridge._all_results[0]["riskLabels"] = ["小市值 · 低于 20 亿美元"]
                        turning_bridge.changed.emit()
                        save_state("turning-risk-single-light.png")
                        turning_bridge._all_results[0]["riskLabels"] = [
                            "市值未知",
                        ]
                        turning_bridge.changed.emit()
                        save_state("turning-risk-unknown-light.png")

            shell.navigate("rs_strength.run")
            rs_run._budget_request = rs_run.build_request()
            rs_run._budget_snapshot = AnalysisBudgetSnapshot(
                member_count=600,
                dimension_count=6,
                total_tasks=3600,
                cache_hits=125,
                cold_requests=3475,
                cold_limit=50,
                data_path="Longbridge · 当前数据源",
                provider_id="longbridge",
            )
            rs_run.changed.emit()
            save_state(f"resource-budget-confirm-{mode}.png")
            rs_run._budget_request = None
            rs_run._budget_snapshot = None
            rs_run.changed.emit()
            for filename, state, running, failures, status in (
                ("outcome-retrying", retrying, True, 0, "连接波动 · 正在恢复"),
                ("outcome-one-lane", throttled, True, 0, "请求受限 · 等待继续"),
                ("outcome-recovered", recovered, True, 0, "连接已恢复 · 继续运行"),
                ("outcome-exact80-partial", exact_eighty, False, 2, "运行完成"),
                ("outcome-below80-no-save", below_eighty, False, 2, "运行失败"),
                ("outcome-auth-action", auth_failure, False, 2, "授权已失效"),
                ("outcome-disk-blocked", disk_blocked, False, 0, "存储不可用"),
            ):
                set_rs_state(
                    state,
                    running=running,
                    failed_count=failures,
                    status=status,
                )
                save_state(f"{filename}-{mode}.png")

            set_rs_state(
                exact_eighty,
                running=False,
                failed_count=2,
                status="运行完成",
            )
            rs_page = require_qml_object(window, "rsRunPage", "RS run page")
            if not QMetaObject.invokeMethod(
                rs_page,
                "openFailureDetails",
            ):
                raise RuntimeError("failure detail overlay is unavailable")
            save_state(f"outcome-detail-collapsed-{mode}.png")
            failure_overlay = require_qml_object(
                window,
                "rsFailureDetailOverlay",
                "failure detail overlay",
            )
            failure_overlay.setProperty(
                "expandedCodes",
                {"rate_limited": True},
            )
            save_state(f"outcome-detail-expanded-{mode}.png")
            failure_overlay.setProperty("visible", False)

            operation_id = f"gallery-close-{mode}"
            application.registry.reserve(
                operation_id,
                f"gallery-close-key-{mode}",
                "gallery",
            )
            application.registry.begin_reserved(operation_id)
            window.close()
            save_state(f"close-guard-{mode}.png")
            if not QMetaObject.invokeMethod(window, "dismissCloseGuard"):
                raise RuntimeError("close guard cannot be dismissed")
            application.registry.try_complete(
                operation_id,
                OperationStatus.SUCCEEDED,
                {},
            )

            turning_bridge._failure_state = exact_eighty
            turning_bridge._failure_count = 2
            turning_bridge._running = False
            turning_bridge._status_text = "筛选完成 · 部分项目未执行"
            turning_bridge.changed.emit()
            shell.navigate("turning_point.run")
            save_state(f"turning-outcome-exact80-{mode}.png")

            turning_bridge._failure_state = auth_failure
            turning_bridge._failure_count = 2
            turning_bridge._running = False
            turning_bridge._status_text = "授权已失效 · 无法继续筛选"
            turning_bridge.changed.emit()
            window.setWidth(980)
            window.setHeight(680)
            save_state(f"turning-outcome-auth-narrow-{mode}.png")
            window.setWidth(width)
            window.setHeight(height)

            extreme_bridge._failure_state = exact_eighty
            extreme_bridge._failures = 2
            extreme_bridge._running = False
            extreme_bridge._status_text = "复盘完成 · 部分项目未执行"
            extreme_bridge.changed.emit()
            shell.navigate("extreme_deviation.run")
            save_state(f"extreme-outcome-exact80-{mode}.png")

            extreme_page = require_qml_object(
                window,
                "extremeDeviationPage",
                "extreme deviation page",
            )
            shell.navigate("extreme_deviation.results")
            extreme_bridge._failure_state = auth_failure
            extreme_bridge._last_status = "FAILED"
            extreme_bridge._terminal_has_usable_results = False
            extreme_bridge.changed.emit()
            extreme_bridge.finished.emit(object())
            save_state(f"extreme-outcome-auth-{mode}.png")

            window.setProperty("settingsOpen", True)
            settings.select_page("provider")
            settings.select_provider("longbridge")
            QTest.qWait(220)
            save_window(window, output / f"settings-provider-{mode}.png")
            settings.select_provider("futu")
            QTest.qWait(240)
            save_window(
                window,
                output / f"settings-futu-guide-{mode}.png",
            )
            settings_overlay = require_qml_object(window, "settingsOverlay", "settings overlay")
            settings_overlay.setProperty("futuGuideOpen", False)
            QTest.qWait(100)
            save_window(window, output / f"settings-futu-{mode}.png")
            settings.select_provider("add")
            QTest.qWait(100)
            save_window(
                window,
                output / f"settings-provider-add-{mode}.png",
            )
            settings.select_page("ai")
            QTest.qWait(100)
            save_window(window, output / f"settings-ai-{mode}.png")
            settings.select_page("appearance")
            QTest.qWait(100)
            save_window(
                window,
                output / f"settings-appearance-{mode}.png",
            )
            settings.set_developer_mode(True)
            QMetaObject.invokeMethod(settings_overlay, "focusNetworkSection")
            QTest.qWait(100)
            save_window(window, output / f"settings-advanced-{mode}.png")
            window.setProperty("settingsOpen", False)
            window.setProperty("importOpen", True)
            # Let the modal fade/scale transition settle before taking evidence.
            QTest.qWait(220)
            save_window(window, output / f"import-{mode}.png")
            window.setProperty("importOpen", False)

            if mode == "light":
                auto_csv = Path(home) / "broker-auto.csv"
                auto_csv.write_text(
                    "公司名称,Symbol,最新价\n"
                    "英伟达,NVDA,177.50\n"
                    "超微半导体,AMD,163.20\n"
                    "Iris Energy,IREN,15.40\n",
                    encoding="utf-8",
                )
                window.setProperty("importOpen", True)
                import_text = require_qml_object(window, "importText", "import text area")
                imported = master_data.read_import_file(str(auto_csv))
                import_text.setProperty("text", imported)
                QTest.qWait(100)
                save_window(
                    window,
                    output / "resilience-csv-auto-preview-light.png",
                )

                ambiguous_csv = Path(home) / "broker-ambiguous.csv"
                ambiguous_csv.write_text(
                    "Symbol,Underlying,名称\nAAPL,QQQ,Apple\nNVDA,SPY,NVIDIA\n",
                    encoding="utf-8",
                )
                import_text.setProperty("text", "")
                master_data.read_import_file(str(ambiguous_csv))
                QTest.qWait(100)
                save_window(
                    window,
                    output / "resilience-csv-column-choice-light.png",
                )
                window.setProperty("importOpen", False)

                shell.navigate("rs_strength.run")
                set_rs_state(
                    FailureState(),
                    running=True,
                    status="长桥暂不可用 · 等待备用数据确认",
                )
                fallback_gate = rs_run._fallback_gate
                with fallback_gate._condition:
                    fallback_gate._offer = FallbackOffer(
                        "rs",
                        ("AMD.US", "IREN.US", "NVDA.US"),
                        ("1d",),
                        (
                            FailureCode.RATE_LIMITED,
                            FailureCode.TIMEOUT,
                        ),
                        3,
                        6,
                    )
                    fallback_gate._decision = None
                    fallback_gate._pending = True
                fallback_gate.changed.emit()
                for state_width, state_height, suffix in (
                    (980, 680, "minimum"),
                    (1280, 800, "default"),
                    (1600, 1000, "wide"),
                ):
                    window.setWidth(state_width)
                    window.setHeight(state_height)
                    save_state(f"resilience-fallback-confirm-{suffix}-light.png")

                with fallback_gate._condition:
                    fallback_gate._decision = True
                    fallback_gate._pending = False
                fallback_gate.changed.emit()
                window.setWidth(width)
                window.setHeight(height)
                set_rs_state(
                    FailureState(),
                    running=True,
                    status="正在使用 Yahoo 重新计算",
                )
                rs_run._stage_label = "Yahoo 单源重跑"
                rs_run._stage_detail = "主源临时结果已丢弃 · 正在重跑完整冻结请求"
                rs_run._progress = 0.72
                rs_run.changed.emit()
                save_state("resilience-fallback-running-light.png")

                if rs_history._selected is not None:
                    selected = rs_history._selected
                    rs_history._selected = replace(
                        selected,
                        header=replace(
                            selected.header,
                            provider_id="yahoo",
                            provider_display_name="Yahoo 备用数据",
                        ),
                    )
                    rs_history.changed.emit()
                shell.navigate("rs_strength.history")
                save_state("resilience-yahoo-only-result-light.png")

                unavailable = FailureState(
                    outcome_visible=True,
                    outcome_tone="danger",
                    outcome_title="主行情与备用行情均不可用",
                    outcome_summary=("Yahoo 整次重跑仍未达到 80% 可用门槛，没有新增历史记录。"),
                    outcome_primary_action="retry",
                    outcome_primary_label="稍后重试",
                )
                shell.navigate("rs_strength.run")
                set_rs_state(
                    unavailable,
                    running=False,
                    failed_count=3,
                    status="备用行情仍不可用",
                )
                save_state("resilience-yahoo-unavailable-light.png")

            window.setProperty("scenarioOpen", True)
            QTest.qWait(220)
            save_window(window, output / f"scenario-lab-{mode}.png")
            window.setProperty("scenarioOpen", False)
        window.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    args = parser.parse_args()
    _capture(args.output.resolve(), width=args.width, height=args.height)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
