"""Minimal QML engine bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import QCoreApplication, QProcess, Qt, QUrl
from PySide6.QtGui import QFont, QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from stock_toolbox.analyses.rs_strength.application.models import RunResult
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRunResult,
)
from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.desktop_qml.extreme_deviation_bridge import (
    ExtremeDeviationBridge,
)
from stock_toolbox.desktop_qml.master_data_bridge import MasterDataBridge
from stock_toolbox.desktop_qml.rs_history_bridge import RsHistoryBridge
from stock_toolbox.desktop_qml.rs_run_bridge import RsRunBridge
from stock_toolbox.desktop_qml.scenario_bridge import ScenarioBridge
from stock_toolbox.desktop_qml.settings_bridge import SettingsBridge
from stock_toolbox.desktop_qml.shell_bridge import ShellBridge
from stock_toolbox.desktop_qml.theme_bridge import ThemeBridge
from stock_toolbox.desktop_qml.turning_point_bridge import TurningPointBridge
from stock_toolbox.desktop_qml.ui_stall_monitor import UiStallMonitor
from stock_toolbox.desktop_qml.update_bridge import UpdateBridge
from stock_toolbox.desktop_qml.vibrancy import install_vibrancy
from stock_toolbox.runtime.environment import RuntimeEnvironment

_QML_ROOT = Path(__file__).with_name("qml")


def build_pilot_engine(
    application: StockToolboxApplication,
    environment: RuntimeEnvironment,
) -> QQmlApplicationEngine:
    application.registry.reset_admission()
    qt_application = cast(QGuiApplication | None, QGuiApplication.instance())
    if qt_application is None:
        raise TypeError("QML pilot requires an active QGuiApplication")
    if qt_application.font().family() == "Sans Serif":
        qt_application.setFont(QFont(".AppleSystemUIFont"))
    QQuickStyle.setStyle("Basic")
    engine = QQmlApplicationEngine()
    theme_bridge = ThemeBridge(
        qt_application.styleHints(),
        engine,
        initial_mode=application.appearance_mode(),
        save_mode=application.save_appearance_mode,
    )
    shell_bridge = ShellBridge(application, engine)
    settings_bridge = SettingsBridge(application, engine)
    master_data_bridge = MasterDataBridge(application, engine)
    rs_run_bridge = RsRunBridge(application, engine)
    rs_history_bridge = RsHistoryBridge(application, engine)
    turning_point_bridge = TurningPointBridge(application, engine)
    extreme_deviation_bridge = ExtremeDeviationBridge(application, engine)
    scenario_bridge = ScenarioBridge(application, engine)
    update_bridge = UpdateBridge(engine)
    settings = application.settings()
    engine.rootContext().setContextProperty("themeBridge", theme_bridge)
    engine.rootContext().setContextProperty("shellBridge", shell_bridge)
    engine.rootContext().setContextProperty("settingsBridge", settings_bridge)
    engine.rootContext().setContextProperty("masterDataBridge", master_data_bridge)
    engine.rootContext().setContextProperty("rsRunBridge", rs_run_bridge)
    engine.rootContext().setContextProperty("rsHistoryBridge", rs_history_bridge)
    engine.rootContext().setContextProperty(
        "turningPointBridge",
        turning_point_bridge,
    )
    engine.rootContext().setContextProperty(
        "extremeDeviationBridge",
        extreme_deviation_bridge,
    )
    engine.rootContext().setContextProperty("scenarioBridge", scenario_bridge)
    engine.rootContext().setContextProperty("updateBridge", update_bridge)
    rs_run_bridge.finished.connect(
        lambda raw: _show_rs_result(
            raw,
            rs_history_bridge,
            shell_bridge,
        )
    )
    turning_point_bridge.finished.connect(
        lambda raw: _show_turning_result(
            raw,
            turning_point_bridge,
            shell_bridge,
        )
    )
    settings_bridge.changed.connect(rs_run_bridge.refresh_provider_status)
    settings_bridge.changed.connect(rs_history_bridge.refresh)
    settings_bridge.changed.connect(turning_point_bridge.refresh_display_timezone)
    settings_bridge.changed.connect(extreme_deviation_bridge.refresh_settings)
    engine.setInitialProperties(
        {
            "environmentLabel": environment.value,
            "applicationReady": application is not None,
            "firstRunRequired": (
                environment is RuntimeEnvironment.PRODUCTION
                and not settings.first_run_complete
            ),
            "productTourDismissed": settings.product_tour_dismissed,
            "productTourOpen": (
                environment is RuntimeEnvironment.PRODUCTION
                and settings.first_run_complete
                and not settings.product_tour_dismissed
            ),
        }
    )
    engine.load(QUrl.fromLocalFile(str(_QML_ROOT / "PilotWindow.qml")))
    if not engine.rootObjects():
        raise RuntimeError("qml_pilot_load_failed")
    root = engine.rootObjects()[0]
    stall_monitor = UiStallMonitor(
        application.diagnostics,
        current_page=lambda: str(shell_bridge.current_page),
        active_operations=lambda: len(
            application.registry.active_snapshots()
        ),
        application_active=lambda: (
            qt_application.applicationState()
            == Qt.ApplicationState.ApplicationActive
        ),
        parent=engine,
    )
    qt_application.applicationStateChanged.connect(
        lambda _state: stall_monitor.reset_clock()
    )
    stall_monitor.start()
    qt_application.aboutToQuit.connect(stall_monitor.stop)
    settings_bridge.reset_completed.connect(lambda: _finish_reset(root, environment))
    if isinstance(root, QWindow):
        root.setProperty("nativeVibrancyActive", install_vibrancy(root))
    return engine


def _show_first_run(root: object) -> None:
    if not hasattr(root, "setProperty"):
        return
    root.setProperty("firstRunRequired", True)
    root.setProperty("settingsOpen", True)


def _finish_reset(root: object, environment: RuntimeEnvironment) -> None:
    if environment is not RuntimeEnvironment.PRODUCTION:
        _show_first_run(root)
        return
    executable = QCoreApplication.applicationFilePath()
    if executable and QProcess.startDetached(executable, list(QCoreApplication.arguments()[1:]))[0]:
        QCoreApplication.quit()
        return
    _show_first_run(root)


def _show_rs_result(
    raw: object,
    history: RsHistoryBridge,
    shell: ShellBridge,
) -> None:
    if not isinstance(raw, RunResult) or raw.run_id is None:
        return
    history.refresh()
    history.select_run(raw.run_id)
    shell.navigate("rs_strength.history")


def _show_turning_result(
    raw: object,
    history: TurningPointBridge,
    shell: ShellBridge,
) -> None:
    if not isinstance(raw, TurningPointRunResult) or raw.run_id is None:
        return
    if history.select_run(raw.run_id):
        shell.navigate("turning_point.history")
