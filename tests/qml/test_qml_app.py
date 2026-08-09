from __future__ import annotations

from datetime import date
from threading import Event

import pytest
from PySide6.QtCore import QMetaObject, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWindow
from PySide6.QtTest import QTest

from stock_toolbox.analyses.rs_strength.application.models import RunRequest
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRunResult,
    TurningPointRunStatus,
)
from stock_toolbox.core.operations.registry import ReserveResult
from stock_toolbox.core.settings.models import ServiceTestResult
from stock_toolbox.desktop_qml.app import build_pilot_engine
from stock_toolbox.desktop_qml.shell_bridge import ShellBridge
from stock_toolbox.runtime.environment import RuntimeEnvironment
from tests.qml.helpers import seeded_watchlist

pytestmark = pytest.mark.qml_app


def test_pilot_engine_loads_one_root_window(qapp, scenario_application) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )

    assert len(engine.rootObjects()) == 1
    assert engine.rootObjects()[0].objectName() == "softGlassWindow"
    assert isinstance(
        engine.rootContext().contextProperty("shellBridge"),
        ShellBridge,
    )


def test_settings_changes_refresh_rs_history_timezone_projection(
    qtbot,
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    settings = engine.rootContext().contextProperty("settingsBridge")
    history = engine.rootContext().contextProperty("rsHistoryBridge")

    with qtbot.waitSignal(history.changed, timeout=1_000):
        settings.changed.emit()


def test_settings_changes_refresh_extreme_result_projection(
    qtbot,
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    bridge = engine.rootContext().contextProperty("extremeDeviationBridge")

    with qtbot.waitSignal(bridge.changed, timeout=1_000):
        bridge.refresh_settings()


def test_custom_titlebar_window_controls_work(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.setProperty("settingsOpen", True)
    window.show()
    QTest.qWait(40)

    QTest.mouseClick(
        window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(43, 24),
    )
    QTest.qWait(40)
    assert window.visibility() is QWindow.Visibility.Minimized

    window.showNormal()
    QTest.qWait(40)
    QTest.mouseClick(
        window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(63, 24),
    )
    QTest.qWait(40)
    assert window.visibility() is QWindow.Visibility.Maximized

    window.showNormal()
    QTest.qWait(40)
    QTest.mouseClick(
        window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(23, 24),
    )
    QTest.qWait(40)
    assert not window.isVisible()


def test_pilot_contains_the_complete_rs_run_scene(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]

    for object_name in (
        "shellSidebar",
        "rsRunPage",
        "runConfigPanel",
        "preflightBar",
        "runStageStrip",
        "startRunButton",
        "cancelRunButton",
        "settingsButton",
        "settingsOverlay",
    ):
        assert window.findChild(QObject, object_name) is not None


def test_qml_shell_contains_all_tool_pages_and_overlays(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]

    for object_name in (
        "turningPointPage",
        "extremeDeviationPage",
        "importOverlay",
        "scenarioLabOverlay",
    ):
        assert window.findChild(QObject, object_name) is not None


def test_completed_turning_run_opens_its_saved_history(
    qtbot,
    qapp,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    shell = engine.rootContext().contextProperty("shellBridge")
    bridge = engine.rootContext().contextProperty("turningPointBridge")
    assert shell.navigate("turning_point.run")
    assert bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.start()

    assert shell.current_page == "turning_point.history"
    assert bridge.selected_run_id == bridge.history[0]["runId"]


def test_unsaved_turning_terminal_result_stays_on_run_page(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    shell = engine.rootContext().contextProperty("shellBridge")
    bridge = engine.rootContext().contextProperty("turningPointBridge")
    assert shell.navigate("turning_point.run")

    bridge.finished.emit(TurningPointRunResult(TurningPointRunStatus.FAILED))

    assert shell.current_page == "turning_point.run"


def test_extreme_page_keeps_failed_terminal_actions_on_run_view(
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
    window.show()

    bridge._last_status = "FAILED"
    bridge._terminal_has_usable_results = False
    bridge.finished.emit(object())
    QTest.qWait(20)
    assert shell.current_page == "extreme_deviation.run"

    bridge._last_status = "PARTIAL"
    bridge._terminal_has_usable_results = True
    bridge.finished.emit(object())
    QTest.qWait(20)
    assert shell.current_page == "extreme_deviation.run"
    QTest.qWait(550)
    assert shell.current_page == "extreme_deviation.results"

    bridge._last_status = "CANCELED"
    bridge._terminal_has_usable_results = False
    bridge.finished.emit(object())
    QTest.qWait(20)
    assert shell.current_page == "extreme_deviation.run"


def test_settings_workspace_contains_progressive_provider_and_ai_controls(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    engine.rootContext().contextProperty("settingsBridge").select_page("appearance")
    QTest.qWait(20)

    for object_name in (
        "providerCatalog",
        "providerAddCard",
        "longbridgeQuality",
        "providerPrompt",
        "aiBaseUrl",
        "aiApiKey",
        "aiModelSelect",
        "aiCapabilityPanel",
        "aiAutoCheckButton",
        "appearanceMode_system",
        "appearanceMode_light",
        "appearanceMode_dark",
        "appearanceProductTourButton",
    ):
        assert window.findChild(QObject, object_name) is not None


def test_appearance_settings_can_reopen_product_tour_after_dismissal(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    bridge = engine.rootContext().contextProperty("settingsBridge")
    bridge.select_page("appearance")
    window.setProperty("productTourDismissed", True)
    window.setProperty("productTourOpen", False)
    window.setProperty("settingsOpen", True)
    window.show()
    QTest.qWait(30)

    button = window.findChild(QObject, "appearanceProductTourButton")
    assert button is not None
    center = button.mapToScene(QPointF(button.width() / 2, button.height() / 2))
    QTest.mouseClick(
        window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        center.toPoint(),
    )
    QTest.qWait(30)

    assert window.property("settingsOpen") is False
    assert window.property("productTourOpen") is True
    assert window.property("productTourDismissed") is True


def test_settings_pages_are_mutually_exclusive_and_ai_inputs_stay_equal_width(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.setProperty("settingsOpen", True)
    window.show()
    bridge = engine.rootContext().contextProperty("settingsBridge")
    provider_page = window.findChild(QObject, "providerSettingsPage")
    ai_page = window.findChild(QObject, "aiSettingsPage")
    base_url = window.findChild(QObject, "aiBaseUrl")
    api_key = window.findChild(QObject, "aiApiKey")

    bridge.select_page("provider")
    QTest.qWait(20)
    assert provider_page.property("visible") is True
    assert ai_page.property("visible") is False

    bridge.select_page("ai")
    QTest.qWait(100)
    assert provider_page.property("visible") is False
    assert ai_page.property("visible") is True
    assert abs(base_url.property("width") - api_key.property("width")) <= 0.5
    assert base_url.property("width") + api_key.property("width") >= ai_page.property("width") * 0.8
    api_key.setProperty("text", "secret")
    QTest.qWait(20)
    assert abs(base_url.property("width") - api_key.property("width")) <= 0.5


def test_provider_quality_has_visible_running_feedback(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.setProperty("settingsOpen", True)
    window.show()
    quality_button = window.findChild(QObject, "providerQualityButton")
    quality_spinner = window.findChild(QObject, "providerQualitySpinner")
    bridge = engine.rootContext().contextProperty("settingsBridge")

    release = Event()
    bridge._start(
        lambda: (
            release.wait(2),
            ServiceTestResult("provider", True, "OK"),
        )[1],
        lambda _raw: None,
        "provider_quality",
    )
    QTest.qWait(20)

    assert quality_button.property("text") == "正在质检…"
    assert quality_spinner.property("visible") is True
    assert quality_spinner.property("running") is True
    release.set()


def test_theme_choice_is_applied_immediately_and_restored_by_next_engine(
    qapp,
    scenario_application,
) -> None:
    first = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    first_theme = first.rootContext().contextProperty("themeBridge")

    assert first_theme.set_mode("dark") is True
    assert first_theme.dark is True
    first.rootObjects()[0].close()

    second = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    second_theme = second.rootContext().contextProperty("themeBridge")
    admitted = scenario_application.registry.reserve(
        "recreated-engine",
        "recreated-engine-key",
        "analysis",
    )

    assert second_theme.mode == "dark"
    assert second_theme.dark is True
    assert admitted.result is ReserveResult.RESERVED


def test_shared_button_content_stays_centered_at_supported_window_sizes(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()

    for width, height in ((980, 680), (1280, 800), (1600, 1000)):
        window.resize(width, height)
        QTest.qWait(20)
        for control in window.findChildren(QObject):
            if "GlassButton" not in control.metaObject().className():
                continue
            content = control.property("contentItem")
            assert content is not None
            horizontal_offset = (
                content.property("x")
                + content.property("width") / 2
                - control.property("width") / 2
            )
            vertical_offset = (
                content.property("y")
                + content.property("height") / 2
                - control.property("height") / 2
            )
            assert abs(horizontal_offset) <= 0.5
            assert abs(vertical_offset) <= 0.5


def test_watchlist_completion_action_is_centered_in_its_overlay(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.resize(1280, 800)
    window.show()
    overlay = window.findChild(QObject, "watchlistMemberOverlay")
    button = window.findChild(QObject, "watchlistCompletionButton")

    overlay.setProperty("visible", True)
    QTest.qWait(20)
    overlay.setProperty("step", 3)
    QTest.qWait(100)
    button_center = button.mapToItem(
        overlay,
        QPointF(
            button.property("width") / 2,
            button.property("height") / 2,
        ),
    )

    assert button.property("visible") is True
    assert abs(button_center.x() - overlay.property("width") / 2) <= 0.5


def test_watchlist_overlay_selects_all_eligible_visible_candidates(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    overlay = window.findChild(QObject, "watchlistMemberOverlay")
    overlay.setProperty(
        "candidates",
        [
            {
                "id": "one",
                "displaySymbol": "AMD",
                "name": "超威半导体",
                "classifications": [{"bindingId": "a", "name": "半导体"}],
            },
            {
                "id": "two",
                "displaySymbol": "NVDA",
                "name": "英伟达",
                "classifications": [{"bindingId": "a", "name": "半导体"}],
            },
            {
                "id": "disabled",
                "displaySymbol": "NONE",
                "name": "未分类",
                "classifications": [],
            },
        ],
    )
    overlay.setProperty("visible", True)
    QTest.qWait(20)

    assert QMetaObject.invokeMethod(overlay, "toggleAllVisible") is True
    selected = overlay.property("selectedIds").toVariant()

    assert selected == ["one", "two"]


def test_watchlist_overlay_keeps_open_candidate_snapshot_during_bridge_refresh(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.resize(1280, 800)
    window.show()
    overlay = window.findChild(QObject, "watchlistMemberOverlay")
    candidates = [
        {
            "id": f"security-{index}",
            "displaySymbol": f"TEST{index}",
            "name": f"测试证券 {index}",
            "classifications": [{"bindingId": "tag", "name": "测试标签"}],
        }
        for index in range(124)
    ]

    overlay.setProperty("candidates", candidates)
    overlay.setProperty("visible", True)
    QTest.qWait(20)
    assert QMetaObject.invokeMethod(overlay, "toggleAllVisible") is True

    # A bridge refresh can transiently expose an empty property while the
    # overlay is open. The user's in-progress selection must remain visible.
    overlay.setProperty("candidates", [])
    QTest.qWait(20)
    visible_lists = [
        item
        for item in overlay.findChildren(QObject)
        if item.metaObject().className() == "QQuickListView"
        and item.property("visible") is True
    ]

    assert len(overlay.property("selectedIds").toVariant()) == 124
    assert len(visible_lists) == 1
    assert visible_lists[0].property("count") == 124


def test_import_progress_animates_between_stage_targets(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    bridge = engine.rootContext().contextProperty("masterDataBridge")
    progress_bar = window.findChild(QObject, "importProgressBar")

    bridge._import_total = 10
    bridge.import_changed.emit()
    QTest.qWait(20)
    bridge._import_progress = 0.96
    bridge.import_changed.emit()

    immediate = float(progress_bar.property("value"))
    QTest.qWait(220)
    intermediate = float(progress_bar.property("value"))
    QTest.qWait(420)
    settled = float(progress_bar.property("value"))

    assert immediate < intermediate < 0.96
    assert settled == pytest.approx(0.96, abs=0.01)


def test_import_editor_scrolls_and_finish_clears_the_session(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    bridge = engine.rootContext().contextProperty("masterDataBridge")
    window.setProperty("importOpen", True)
    window.show()
    QTest.qWait(30)

    overlay = window.findChild(QObject, "importOverlay")
    editor = window.findChild(QObject, "importText")
    scroll = window.findChild(QObject, "importTickerScroll")
    content_item = scroll.property("contentItem")
    editor.setProperty(
        "text",
        "\n".join(f"TEST{number:03d}" for number in range(1, 51)),
    )
    bridge._import_total = 50
    bridge._import_completed = 50
    bridge._import_progress = 1.0
    bridge._import_summary = {"success": 50}
    bridge._import_details = [{"symbol": "TEST001", "category": "success"}]
    bridge.import_changed.emit()
    QTest.qWait(30)

    assert float(content_item.property("contentHeight")) > float(
        scroll.property("height")
    )
    assert content_item.setProperty("contentY", 100.0)
    assert float(content_item.property("contentY")) == pytest.approx(100.0)

    # Closing without finishing preserves the draft in the current app session.
    window.setProperty("importOpen", False)
    window.setProperty("importOpen", True)
    assert editor.property("text").startswith("TEST001\nTEST002")
    assert bridge.import_total == 50

    # Finishing explicitly starts the next import with a clean editor and state.
    assert QMetaObject.invokeMethod(overlay, "finishAndClear") is True
    QTest.qWait(20)
    assert editor.property("text") == ""
    assert bridge.import_total == 0
    assert bridge.import_summary == {}
    assert bridge.import_details == []


def test_rs_date_picker_opens_and_custom_date_fields_become_visible(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    bridge = engine.rootContext().contextProperty("rsRunBridge")
    shell.navigate("rs_strength.run")
    window.show()
    QTest.qWait(30)
    end_picker = window.findChild(QObject, "rsEndDatePicker")
    custom_start = window.findChild(QObject, "rsCustomStartPicker")
    custom_end = window.findChild(QObject, "rsCustomEndPicker")

    assert QMetaObject.invokeMethod(end_picker, "openCalendar") is True
    QTest.qWait(20)
    assert end_picker.property("calendarOpen") is True

    bridge.set_end_date("2026-07-24")
    bridge.set_custom_enabled(True)
    QTest.qWait(20)

    assert custom_start.property("visible") is True
    assert custom_end.property("visible") is True


def test_choice_chip_reserves_space_for_indicator_and_full_label(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    window.show()
    QTest.qWait(20)

    chips = [
        item
        for item in window.findChildren(QObject)
        if "ChoiceChip" in item.metaObject().className()
    ]
    assert chips
    for chip in chips:
        content = chip.property("contentItem")
        indicator = chip.property("indicator")
        assert content.property("x") >= (
            indicator.property("x") + indicator.property("width") + chip.property("spacing")
        )
        assert content.property("width") >= content.property("implicitWidth")


def test_navigation_and_settings_labels_are_not_truncated_at_minimum_size(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    settings = engine.rootContext().contextProperty("settingsBridge")
    window.resize(980, 680)
    window.show()

    def truncated_labels() -> list[str]:
        return [
            str(item.property("text"))
            for item in window.findChildren(QObject)
            if item.metaObject().className().startswith("QQuickText")
            and hasattr(item, "isVisible")
            and item.isVisible()
            and bool(item.property("truncated"))
        ]

    for page in (
        "securities",
        "classifications",
        "watchlists",
        "rs_strength.run",
        "rs_strength.history",
        "turning_point.run",
        "turning_point.history",
        "extreme_deviation.run",
        "extreme_deviation.results",
    ):
        shell.navigate(page)
        QTest.qWait(10)
        assert truncated_labels() == [], page

    window.setProperty("settingsOpen", True)
    for page in ("provider", "ai", "appearance", "advanced"):
        settings.select_page(page)
        QTest.qWait(10)
        assert truncated_labels() == [], f"settings.{page}"


def test_rs_ai_report_dialog_stays_centered_inside_supported_sizes(
    qapp,
    scenario_application,
) -> None:
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    shell.navigate("rs_strength.history")
    window.show()
    page = window.findChild(QObject, "rsHistoryPage")
    overlay = window.findChild(QObject, "rsAIReportOverlay")
    panel = window.findChild(QObject, "rsAIReportPanel")
    close_button = window.findChild(QObject, "rsAIReportCloseButton")
    card = window.findChild(QObject, "rsAIReportCard")
    page.setProperty("reportDialogOpen", True)

    for width, height in ((980, 680), (1280, 800)):
        window.resize(width, height)
        QTest.qWait(40)
        panel_center = panel.mapToItem(
            overlay,
            QPointF(
                panel.property("width") / 2,
                panel.property("height") / 2,
            ),
        )
        content = close_button.property("contentItem")
        horizontal_offset = (
            content.property("x")
            + content.property("width") / 2
            - close_button.property("width") / 2
        )
        vertical_offset = (
            content.property("y")
            + content.property("height") / 2
            - close_button.property("height") / 2
        )

        assert overlay.property("visible") is True
        assert panel.property("width") <= page.property("width") - 36
        assert panel.property("height") <= page.property("height") - 36
        assert abs(panel_center.x() - overlay.property("width") / 2) <= 0.5
        assert abs(panel_center.y() - overlay.property("height") / 2) <= 0.5
        assert abs(horizontal_offset) <= 0.5
        assert abs(vertical_offset) <= 0.5
        assert card.property("height") == pytest.approx(88, abs=0.5)


def test_rs_history_hides_status_help_for_unscored_classifications(
    qapp,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    result = scenario_application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M", "6M", "1Y"),
            None,
        )
    )
    engine = build_pilot_engine(
        scenario_application,
        RuntimeEnvironment.SCENARIO,
    )
    window = engine.rootObjects()[0]
    shell = engine.rootContext().contextProperty("shellBridge")
    history = engine.rootContext().contextProperty("rsHistoryBridge")
    assert history.select_run(str(result.run_id))
    shell.navigate("rs_strength.history")
    window.resize(1280, 800)
    window.show()
    QTest.qWait(80)

    help_items = window.findChildren(QObject, "classificationStatusHelp")
    assert all(not item.isVisible() for item in help_items)
    unscored = [item for item in history.classification_results if item["score"] is None]
    assert unscored
    assert all(
        str(item["statusLabel"]).startswith("样本不足") and item["statusHelpVisible"] is False
        for item in unscored
    )
