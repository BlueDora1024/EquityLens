from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QMetaObject,
    QObject,
    QPointF,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QSignalSpy, QTest

from stock_toolbox.core.operations.failure_policy import AnalysisReliability
from stock_toolbox.core.operations.registry import (
    OperationStatus,
    ReserveResult,
)
from stock_toolbox.desktop_qml.app import build_pilot_engine
from stock_toolbox.desktop_qml.failure_presentation import FailureState, finish_outcome
from stock_toolbox.runtime.environment import RuntimeEnvironment

_QML_ROOT = Path("src/stock_toolbox/desktop_qml/qml").resolve()


class _FailureGroupProbe(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    @Property(list, notify=changed)
    def failure_groups(self) -> list[dict[str, object]]:
        self.reads += 1
        return [
            {
                "code": "rate_limited",
                "count": 2,
                "symbols": ["AMD.US"],
                "intervals": ["1d"],
            }
        ]


def _scene_bounds(item: QQuickItem) -> tuple[float, float, float, float]:
    origin = item.mapToScene(QPointF(0, 0))
    return origin.x(), origin.y(), item.width(), item.height()


def _is_descendant(item: QQuickItem | None, ancestor: QQuickItem) -> bool:
    current = item
    while current is not None:
        if current is ancestor:
            return True
        current = current.parentItem()
    return False


def _find_visual_item(
    root: QQuickItem,
    object_name: str,
) -> QQuickItem | None:
    pending = list(root.childItems())
    while pending:
        item = pending.pop()
        if item.objectName() == object_name:
            return item
        pending.extend(item.childItems())
    return None


def _show_partial_outcomes(engine: object) -> None:
    reliability = AnalysisReliability(
        succeeded_tasks=8,
        failed_tasks=2,
        unexecuted_tasks=0,
        success_rate=Decimal("0.8"),
        circuit_opened=False,
        primary_failure_code="rate_limited",
    )
    state = finish_outcome(FailureState(), "PARTIAL", reliability)
    for name in ("rsRunBridge", "turningPointBridge", "extremeDeviationBridge"):
        bridge = engine.rootContext().contextProperty(name)
        bridge._failure_state = state
        if hasattr(bridge, "_failed_count"):
            bridge._failed_count = 2
        if hasattr(bridge, "_failure_count"):
            bridge._failure_count = 2
        if hasattr(bridge, "_failures"):
            bridge._failures = 2
        bridge.changed.emit()


def test_shared_outcome_cards_fit_supported_sizes_and_themes(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    theme = engine.rootContext().contextProperty("themeBridge")
    _show_partial_outcomes(engine)
    window.show()

    pages = (
        ("rs_strength.run", "rsRunOutcomeCard"),
        ("turning_point.run", "turningOutcomeCard"),
        ("extreme_deviation.run", "extremeOutcomeCard"),
    )
    for width, height in ((980, 680), (1280, 800)):
        window.resize(width, height)
        for mode in ("light", "dark"):
            theme.set_evidence_mode(mode)
            for page_id, object_name in pages:
                shell.navigate(page_id)
                if page_id in {
                    "turning_point.run",
                    "extreme_deviation.run",
                }:
                    _show_partial_outcomes(engine)
                QTest.qWait(30)
                card = window.findChild(QObject, object_name)
                assert card is not None
                assert card.property("visible") is True
                card.setProperty("outcomeTitle", "授权失败")
                card.setProperty(
                    "outcomeSummary",
                    "登录凭证已失效，请前往设置重新授权。",
                )
                card.setProperty("primaryAction", "open_settings")
                card.setProperty("primaryLabel", "前往设置")
                card.setProperty("failureCount", 2)
                QTest.qWait(10)
                visual_card = window.findChild(QQuickItem, object_name)
                title = visual_card.findChild(QQuickItem, "outcomeTitleText")
                summary = visual_card.findChild(
                    QQuickItem,
                    "outcomeSummaryText",
                )
                detail_button = visual_card.findChild(
                    QQuickItem,
                    "outcomeDetailsButton",
                )
                primary_button = visual_card.findChild(
                    QQuickItem,
                    "outcomePrimaryButton",
                )
                assert title is not None
                assert summary is not None
                assert detail_button is not None
                assert primary_button is not None
                assert detail_button.property("visible") is True
                assert primary_button.property("visible") is True
                children = (title, summary, detail_button, primary_button)
                for _attempt in range(20):
                    card_x, card_y, card_width, card_height = _scene_bounds(
                        visual_card
                    )
                    if all(
                        card_x <= child_x
                        and card_y <= child_y
                        and child_x + child_width <= card_x + card_width
                        and child_y + child_height <= card_y + card_height
                        for child_x, child_y, child_width, child_height in (
                            _scene_bounds(child) for child in children
                        )
                    ):
                        break
                    QTest.qWait(5)
                assert 0 <= card_x < width
                assert 0 <= card_y < height
                assert 0 < card_width <= width - card_x
                assert 0 < card_height <= 132
                for child in children:
                    child_x, child_y, child_width, child_height = (
                        _scene_bounds(child)
                    )
                    assert card_x <= child_x
                    assert card_y <= child_y
                    assert child_x + child_width <= card_x + card_width
                    assert child_y + child_height <= card_y + card_height
                assert str(title.property("text")) == "授权失败"
                assert str(summary.property("text")).startswith("登录凭证")
                assert title.property("truncated") is False
                assert summary.property("truncated") is False
                if width == 980 and object_name == "turningOutcomeCard":
                    assert summary.property("maximumLineCount") == 2
                for _attempt in range(20):
                    detail_x, _, detail_width, _ = _scene_bounds(
                        detail_button
                    )
                    primary_x, _, _, _ = _scene_bounds(primary_button)
                    if detail_x + detail_width <= primary_x:
                        break
                    QTest.qWait(5)
                assert detail_x + detail_width <= primary_x


def test_extreme_running_progress_panel_never_consumes_the_page(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    bridge = engine.rootContext().contextProperty("extremeDeviationBridge")
    shell.navigate("extreme_deviation.run")
    bridge._running = True
    bridge.changed.emit()
    window.resize(1280, 800)
    window.show()
    QTest.qWait(30)

    panel = window.findChild(QQuickItem, "extremeProgressPanel")
    config = window.findChild(QQuickItem, "extremeConfigPanel")

    assert panel is not None
    assert config is not None
    assert panel.height() <= 300
    config_x, config_y, config_width, config_height = _scene_bounds(config)
    panel_x, panel_y, panel_width, _panel_height = _scene_bounds(panel)
    assert panel_y - (config_y + config_height) <= 16
    assert panel_x == config_x
    assert panel_width == config_width


def test_turning_start_button_stays_inside_run_console(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    window.resize(1280, 800)
    window.show()
    shell.navigate("turning_point.run")
    QTest.qWait(30)

    panel = window.findChild(QQuickItem, "turningRunConsole")
    button = window.findChild(QQuickItem, "turningStartButton")

    assert panel is not None
    assert button is not None
    panel_x, panel_y, panel_width, panel_height = _scene_bounds(panel)
    button_x, button_y, button_width, button_height = _scene_bounds(button)
    assert panel_x <= button_x
    assert panel_y <= button_y
    assert button_x + button_width <= panel_x + panel_width
    assert button_y + button_height <= panel_y + panel_height


def test_product_tour_card_and_actions_fit_minimum_window(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.resize(980, 680)
    window.setProperty("productTourOpen", True)
    window.show()
    QTest.qWait(30)

    overlay = window.findChild(QQuickItem, "productTourOverlay")
    card = window.findChild(QQuickItem, "productTourCard")
    illustration = window.findChild(QQuickItem, "productTourIllustration")
    previous = window.findChild(QQuickItem, "productTourPrevious")
    next_button = window.findChild(QQuickItem, "productTourNext")
    dismiss = window.findChild(QQuickItem, "productTourDismiss")

    assert overlay is not None
    assert card is not None
    assert illustration is not None
    assert previous is not None
    assert next_button is not None
    assert dismiss is not None
    assert overlay.property("visible") is True
    overlay_x, overlay_y, overlay_width, overlay_height = _scene_bounds(overlay)
    for child in (card, illustration, previous, next_button, dismiss):
        child_x, child_y, child_width, child_height = _scene_bounds(child)
        assert overlay_x <= child_x
        assert overlay_y <= child_y
        assert child_x + child_width <= overlay_x + overlay_width
        assert child_y + child_height <= overlay_y + overlay_height
    assert illustration.width() / illustration.height() <= 1.85

    focus_ring = window.findChild(QQuickItem, "productTourFocusRing")
    assert focus_ring is not None
    targets = (
        "productTourTargetSecurities",
        "productTourTargetOrganization",
        "productTourTargetAnalyses",
        "productTourTargetResults",
        "productTourTargetSettings",
    )
    for slide, target_name in enumerate(targets):
        overlay.setProperty("currentSlide", slide)
        QTest.qWait(220)
        target = window.findChild(QQuickItem, target_name)
        assert target is not None
        ring_x, ring_y, ring_width, ring_height = _scene_bounds(focus_ring)
        target_x, target_y, target_width, target_height = _scene_bounds(target)
        assert ring_x <= target_x
        assert ring_y <= target_y
        assert target_x + target_width <= ring_x + ring_width
        assert target_y + target_height <= ring_y + ring_height


def test_turning_running_content_stays_inside_run_console(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    bridge = engine.rootContext().contextProperty("turningPointBridge")
    window.resize(1280, 800)
    window.show()
    shell.navigate("turning_point.run")
    bridge._running = True
    bridge._status_text = "服务端指标 · 4/10 · 120m"
    bridge._progress = 0.4
    bridge.changed.emit()
    QTest.qWait(30)

    panel = window.findChild(QQuickItem, "turningRunConsole")
    card = window.findChild(QQuickItem, "turningOutcomeCard")
    button = window.findChild(QQuickItem, "turningStartButton")
    cancel_button = window.findChild(QQuickItem, "turningCancelButton")
    matched_metric = window.findChild(QQuickItem, "turningMatchedMetric")
    failure_metric = window.findChild(QQuickItem, "turningFailureMetric")
    stage_strip = window.findChild(QQuickItem, "turningStageStrip")

    assert panel is not None
    assert card is not None
    assert button is not None
    assert cancel_button is not None
    assert matched_metric is not None
    assert failure_metric is not None
    assert stage_strip is not None
    assert button.property("visible") is False
    assert cancel_button.property("visible") is True
    panel_x, panel_y, panel_width, panel_height = _scene_bounds(panel)
    for child in (card, matched_metric, failure_metric, cancel_button):
        child_x, child_y, child_width, child_height = _scene_bounds(child)
        assert panel_x <= child_x
        assert panel_y <= child_y
        assert child_x + child_width <= panel_x + panel_width
        assert child_y + child_height <= panel_y + panel_height
    _, stage_y, _, _ = _scene_bounds(stage_strip)
    assert panel_y + panel_height < stage_y


def test_turning_run_cards_are_compact_and_strategy_content_does_not_overlap(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    window.resize(1280, 800)
    window.show()
    shell.navigate("turning_point.run")
    QTest.qWait(30)

    console = window.findChild(QQuickItem, "turningRunConsole")
    strategy = window.findChild(QQuickItem, "turningStrategyPanel")
    interval_grid = window.findChild(QQuickItem, "turningIntervalGrid")

    assert console is not None
    assert strategy is not None
    assert interval_grid is not None
    _, _, _, console_height = _scene_bounds(console)
    panel_x, panel_y, panel_width, panel_height = _scene_bounds(strategy)
    grid_x, grid_y, grid_width, grid_height = _scene_bounds(interval_grid)
    # The console is content-driven: it must have room for wrapped outcome
    # copy instead of clipping it to the old 104px cap.
    assert 108 <= console_height <= 180
    assert panel_x <= grid_x
    assert panel_y <= grid_y
    assert grid_x + grid_width <= panel_x + panel_width
    assert grid_y + grid_height <= panel_y + panel_height

    left_choice = window.findChild(QQuickItem, "turningLeftChoice")
    left_help = window.findChild(QQuickItem, "turningLeftHelp")
    right_choice = window.findChild(QQuickItem, "turningRightChoice")
    right_help = window.findChild(QQuickItem, "turningRightHelp")
    assert left_choice is not None
    assert left_help is not None
    assert right_choice is not None
    assert right_help is not None
    assert _is_descendant(left_help, left_choice)
    assert _is_descendant(right_help, right_choice)


def test_extreme_run_inputs_have_comfortable_touch_height(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    window.resize(1280, 800)
    window.show()
    shell.navigate("extreme_deviation.run")
    QTest.qWait(30)

    security = window.findChild(QQuickItem, "extremeSecurityPicker")
    date_picker = window.findChild(QQuickItem, "extremeEndDatePicker")
    assert security is not None
    assert date_picker is not None
    assert security.height() >= 54
    assert date_picker.height() >= 54


def test_detail_overlay_panel_never_clips_at_supported_sizes(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()

    for width, height in ((980, 680), (1280, 800)):
        window.resize(width, height)
        overlay = window.findChild(QObject, "rsFailureDetailOverlay")
        assert overlay is not None
        overlay.setProperty(
            "snapshotModel",
            [
                {
                    "code": "rate_limited",
                    "count": 3,
                    "symbols": ["AAPL.US", "AMD.US", "NVDA.US"],
                    "intervals": ["1d", "1w"],
                }
            ],
        )
        overlay.setProperty("visible", True)
        QTest.qWait(30)
        panel = window.findChild(QObject, "failureDetailPanel")
        assert panel is not None
        assert 0 < float(panel.property("width")) <= width - 24
        assert 0 < float(panel.property("height")) <= height - 24
        assert float(panel.property("x")) >= 0
        assert float(panel.property("y")) >= 0
        overlay.setProperty("visible", False)


def test_failure_detail_large_group_is_complete_and_scrollable(
    qapp,
) -> None:
    symbols = [f"SYMBOL{number:02d}.US" for number in range(40)]
    codes = (
        "rate_limited",
        "provider_timeout",
        "network_unavailable",
        "authentication_failed",
    )
    groups = [
        {
            "code": code,
            "count": len(symbols),
            "symbols": symbols,
            "intervals": ["1m", "5m", "30m", "60m", "1d", "1w", "1M"],
        }
        for code in codes
    ]
    engine = QQmlEngine()
    engine.addImportPath(str(_QML_ROOT))
    component = QQmlComponent(engine)
    component.setData(
        f"""
import QtQuick
import QtQuick.Window
import "components"

Window {{
    width: 980
    height: 680
    visible: true

    function openLargeEvidence(): void {{
        details.openWithSnapshot({json.dumps(groups)})
        details.expandedCodes = ({{
            "rate_limited": true,
            "provider_timeout": true,
            "network_unavailable": true,
            "authentication_failed": true
        }})
    }}

    FailureDetailOverlay {{
        id: details
        objectName: "largeFailureDetails"
        anchors.fill: parent
    }}
}}
""".encode(),
        QUrl.fromLocalFile(str(_QML_ROOT / "LargeFailureProbe.qml")),
    )
    root = component.create()
    assert root is not None, [error.toString() for error in component.errors()]
    assert QMetaObject.invokeMethod(root, "openLargeEvidence") is True
    QTest.qWait(40)

    group_list = root.findChild(QQuickItem, "failureGroupList")
    overlay = root.findChild(QQuickItem, "largeFailureDetails")
    assert group_list is not None
    evidence = _find_visual_item(group_list, "failureEvidenceText")
    row = _find_visual_item(group_list, "failureGroupRow")
    assert evidence is not None, (
        overlay.property("visible"),
        group_list.property("count"),
        group_list.property("contentHeight"),
    )
    assert row is not None
    evidence_text = str(evidence.property("text"))
    assert symbols[0] in evidence_text
    assert symbols[-1] in evidence_text
    assert float(row.property("height")) > 106
    assert float(evidence.property("height")) >= float(
        evidence.property("contentHeight")
    )
    assert float(group_list.property("contentHeight")) > float(
        group_list.property("height")
    )


def test_failure_detail_traps_focus_and_restores_background(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    shell = engine.rootContext().contextProperty("shellBridge")
    shell.navigate("rs_strength.run")
    QTest.qWait(30)
    settings = window.findChild(QQuickItem, "settingsButton")
    overlay = window.findChild(QQuickItem, "rsFailureDetailOverlay")
    assert settings is not None
    assert overlay is not None
    settings.forceActiveFocus()
    QTest.qWait(10)
    assert settings.property("activeFocus") is True
    overlay.setProperty(
        "snapshotModel",
        engine.toScriptValue([
            {
                "code": "rate_limited",
                "count": 2,
                "symbols": ["AMD.US", "NVDA.US"],
                "intervals": ["1d"],
            }
        ]),
    )
    overlay.setProperty("visible", True)
    QTest.qWait(20)

    for key in (
        Qt.Key.Key_Tab,
        Qt.Key.Key_Tab,
        Qt.Key.Key_Backtab,
        Qt.Key.Key_Tab,
    ):
        QTest.keyClick(window, key)
        assert _is_descendant(window.activeFocusItem(), overlay)
        assert settings.property("activeFocus") is False

    QTest.keyClick(window, Qt.Key.Key_Escape)
    QTest.qWait(20)
    assert overlay.property("visible") is False
    assert settings.property("activeFocus") is True


def test_close_guard_traps_focus_and_escape_restores_background(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    settings = window.findChild(QQuickItem, "settingsButton")
    guard = window.findChild(QQuickItem, "activeOperationCloseGuard")
    assert settings is not None
    assert guard is not None
    settings.forceActiveFocus()
    QTest.qWait(10)
    assert settings.property("activeFocus") is True
    registry = scenario_application.registry
    registry.reserve("focus-close", "focus-close-key", "analysis")
    window.close()
    QTest.qWait(20)

    for key in (
        Qt.Key.Key_Tab,
        Qt.Key.Key_Backtab,
        Qt.Key.Key_Tab,
    ):
        QTest.keyClick(window, key)
        assert _is_descendant(window.activeFocusItem(), guard)
        assert settings.property("activeFocus") is False

    QTest.keyClick(window, Qt.Key.Key_Escape)
    QTest.qWait(20)
    assert guard.property("visible") is False
    assert settings.property("activeFocus") is True


def test_preferences_shortcut_is_blocked_by_failure_detail_overlay(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    shell = engine.rootContext().contextProperty("shellBridge")
    shell.navigate("rs_strength.run")
    QTest.qWait(30)
    overlay = window.findChild(QQuickItem, "rsFailureDetailOverlay")
    shortcut = window.findChild(QObject, "preferencesShortcut")
    assert overlay is not None
    assert shortcut is not None

    window.setProperty("settingsOpen", False)
    assert shortcut.property("enabled") is True
    assert QMetaObject.invokeMethod(
        window,
        "openSettingsUnlessModal",
    ) is True
    assert window.property("settingsOpen") is True

    window.setProperty("settingsOpen", False)
    overlay.setProperty("visible", True)
    QTest.qWait(10)
    assert shortcut.property("enabled") is False
    assert QMetaObject.invokeMethod(
        window,
        "openSettingsUnlessModal",
    ) is True
    assert window.property("settingsOpen") is False

    shell.navigate("securities")
    QTest.qWait(10)
    assert shortcut.property("enabled") is True


def test_preferences_shortcut_is_blocked_by_close_guard(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    registry = scenario_application.registry
    registry.reserve("shortcut-close", "shortcut-close-key", "analysis")
    window.close()
    QTest.qWait(20)
    assert window.property("closeGuardOpen") is True

    shortcut = window.findChild(QObject, "preferencesShortcut")
    assert shortcut is not None
    window.setProperty("settingsOpen", False)
    assert shortcut.property("enabled") is False
    assert QMetaObject.invokeMethod(
        window,
        "openSettingsUnlessModal",
    ) is True
    assert window.property("settingsOpen") is False


def test_hidden_extreme_run_modal_does_not_block_preferences(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    shell = engine.rootContext().contextProperty("shellBridge")
    shell.navigate("extreme_deviation.run")
    QTest.qWait(30)
    page = window.findChild(QQuickItem, "extremeDeviationPage")
    overlay = window.findChild(QQuickItem, "extremeFailureDetailOverlay")
    shortcut = window.findChild(QObject, "preferencesShortcut")
    assert page is not None
    assert overlay is not None
    assert shortcut is not None

    overlay.setProperty("visible", True)
    QTest.qWait(10)
    assert shortcut.property("enabled") is False

    shell.navigate("extreme_deviation.results")
    QTest.qWait(10)
    assert shortcut.property("enabled") is True


def test_dismissing_close_guard_reopens_operation_admission(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    registry = scenario_application.registry
    window.show()
    registry.reserve("wait-close", "wait-close-key", "analysis")
    window.close()
    assert window.property("closeGuardOpen") is True

    assert QMetaObject.invokeMethod(window, "dismissCloseGuard") is True
    accepted = registry.reserve(
        "after-wait",
        "after-wait-key",
        "analysis",
    )

    assert accepted.result is ReserveResult.RESERVED


def test_close_guard_wait_cancel_terminal_and_no_active_sequences(
    qapp,
    scenario_application,
) -> None:
    registry = scenario_application.registry
    registry.reserve("qml-close", "qml-close-key", "analysis")
    registry.begin_reserved("qml-close")
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    QTest.qWait(20)

    window.close()
    QTest.qWait(20)
    assert window.isVisible()
    assert window.property("closeGuardOpen") is True
    assert len(window.findChildren(QObject, "activeOperationCloseGuard")) == 1

    window.close()
    QTest.qWait(20)
    assert len(window.findChildren(QObject, "activeOperationCloseGuard")) == 1
    assert QMetaObject.invokeMethod(window, "dismissCloseGuard") is True
    assert window.property("closeGuardOpen") is False
    assert window.isVisible()

    window.close()
    assert QMetaObject.invokeMethod(window, "cancelAndClose") is True
    QTest.qWait(20)
    assert window.isVisible()
    assert window.property("closeAfterCancel") is True

    registry.try_complete("qml-close", OperationStatus.CANCELED, {})
    QTest.qWait(60)
    assert not window.isVisible()

    registry.reset_admission()
    clean_engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    clean_window = clean_engine.rootObjects()[0]
    clean_window.show()
    QTest.qWait(20)
    clean_window.close()
    QTest.qWait(20)
    assert not clean_window.isVisible()


def test_failure_groups_are_read_once_only_on_explicit_detail_open(qapp) -> None:
    probe = _FailureGroupProbe()
    engine = QQmlEngine()
    engine.addImportPath(str(_QML_ROOT))
    engine.rootContext().setContextProperty("probeBridge", probe)
    component = QQmlComponent(engine)
    component.setData(
        """
import QtQuick
import "components"

Item {
    width: 980
    height: 680

    function requestDetails(): void {
        card.detailsRequested()
    }

    RunOutcomeCard {
        id: card
        running: true
        runningTitle: "执行进度"
        runningReason: "正在处理"
        failureCount: 2
    }
    FailureDetailOverlay {
        id: details
        objectName: "probeFailureDetails"
        anchors.fill: parent
    }
    Connections {
        target: card
        function onDetailsRequested(): void {
            details.openWithSnapshot(probeBridge.failure_groups)
        }
    }
}
""".encode(),
        QUrl.fromLocalFile(str(_QML_ROOT / "FailureGroupProbe.qml")),
    )
    root = component.create()
    assert root is not None, [error.toString() for error in component.errors()]

    for _ in range(3600):
        probe.changed.emit()
    assert probe.reads == 0

    assert QMetaObject.invokeMethod(root, "requestDetails") is True
    QTest.qWait(10)
    assert probe.reads == 1
    overlay = root.findChild(QObject, "probeFailureDetails")
    assert overlay is not None
    assert overlay.property("visible") is True


def test_close_guard_can_exit_when_operation_finishes_before_cancel_click(
    qapp,
    scenario_application,
) -> None:
    registry = scenario_application.registry
    registry.reserve("natural-finish", "natural-finish-key", "analysis")
    registry.begin_reserved("natural-finish")
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    window.close()
    QTest.qWait(20)
    assert window.isVisible()
    assert window.property("closeGuardOpen") is True

    registry.try_complete(
        "natural-finish",
        OperationStatus.SUCCEEDED,
        {},
    )
    QTest.qWait(20)
    assert window.isVisible()

    assert QMetaObject.invokeMethod(window, "cancelAndClose") is True
    QTest.qWait(30)
    assert not window.isVisible()


def test_close_guard_closes_once_when_cancel_unwinds_before_events_drain(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    registry = scenario_application.registry
    closing_spy = QSignalSpy(window.closing)
    window.show()

    registry.reserve("fast-close", "fast-close-key", "analysis")
    registry.begin_reserved("fast-close")
    window.close()
    assert window.isVisible()
    assert window.property("closeGuardOpen") is True

    assert QMetaObject.invokeMethod(window, "cancelAndClose") is True
    registry.try_complete(
        "fast-close",
        OperationStatus.CANCELED,
        {},
    )
    QTest.qWait(50)

    assert not window.isVisible(), (
        window.property("closeAfterCancel"),
        window.property("closeGuardOpen"),
        engine.rootContext().contextProperty(
            "shellBridge"
        ).has_active_operation,
        closing_spy.count(),
    )
    assert closing_spy.count() == 2


def test_cancel_and_close_rejects_new_operation_before_false_edge_drains(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    registry = scenario_application.registry
    closing_spy = QSignalSpy(window.closing)
    window.show()
    registry.reserve("close-a", "close-a-key", "analysis")
    registry.begin_reserved("close-a")
    window.close()

    assert QMetaObject.invokeMethod(window, "cancelAndClose") is True
    registry.try_complete("close-a", OperationStatus.CANCELED, {})
    rejected = registry.reserve("close-b", "close-b-key", "analysis")
    QTest.qWait(50)

    assert rejected.result is ReserveResult.ADMISSION_CLOSED
    assert registry.status("close-b") is None
    assert not window.isVisible()
    assert closing_spy.count() == 2


def test_accepted_close_atomically_rejects_immediate_reserve(
    qapp,
    qtbot,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    registry = scenario_application.registry
    window.show()
    qtbot.waitUntil(
        lambda: not registry.has_active_operations(),
        timeout=5_000,
    )

    window.close()
    rejected = registry.reserve(
        "after-accepted-close",
        "after-accepted-close-key",
        "analysis",
    )

    assert rejected.result is ReserveResult.ADMISSION_CLOSED
    assert registry.status("after-accepted-close") is None

    def assert_window_hidden() -> None:
        assert not window.isVisible(), (
            f"visible={window.isVisible()}, "
            f"visibility={window.visibility()}, "
            f"close_guard={window.property('closeGuardOpen')}, "
            f"reserve={rejected.result}"
        )

    qtbot.waitUntil(assert_window_hidden, timeout=5_000)
    assert not window.isVisible()


def test_close_intent_survives_stale_false_while_registry_is_active(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    registry = scenario_application.registry
    shell = engine.rootContext().contextProperty("shellBridge")
    closing_spy = QSignalSpy(window.closing)
    window.show()
    registry.reserve("stale-false", "stale-false-key", "analysis")
    registry.begin_reserved("stale-false")
    window.close()
    assert QMetaObject.invokeMethod(window, "cancelAndClose") is True

    shell.registry_state_changed.emit(False)
    QTest.qWait(30)

    assert registry.has_active_operations() is True
    assert window.isVisible()
    assert window.property("closeAfterCancel") is True
    assert window.property("closeGuardOpen") is True

    registry.try_complete("stale-false", OperationStatus.CANCELED, {})
    QTest.qWait(40)
    assert not window.isVisible()
    assert closing_spy.count() == 2
