"""Desktop GUI entry point."""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path
from typing import cast

from PySide6.QtGui import QGuiApplication, QIcon, QWindow

from stock_toolbox.composition import StockToolboxApplication, build_application
from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticStatus,
)
from stock_toolbox.desktop_qml.app import build_pilot_engine
from stock_toolbox.desktop_qml.window_activation import WindowActivationController
from stock_toolbox.runtime.environment import RuntimeEnvironment

_ENVIRONMENT_ALIASES = {
    "production": RuntimeEnvironment.PRODUCTION,
    "dev": RuntimeEnvironment.DEVELOPMENT,
    "integration": RuntimeEnvironment.INTEGRATION,
    "scenario": RuntimeEnvironment.SCENARIO,
}


def _record_lifecycle(
    application: StockToolboxApplication,
    action: str,
) -> None:
    try:
        application.diagnostics.emit(
            DiagnosticEvent(
                DiagnosticLevel.INFO,
                "application",
                action,
                DiagnosticStatus.SUCCEEDED,
            )
        )
    except (OSError, TypeError, ValueError):
        return


def _shutdown_application(application: StockToolboxApplication) -> None:
    application.registry.close_admission()
    _record_lifecycle(application, "exit")
    application.close()
    application.diagnostics.close(timeout_seconds=1.0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="equitylens-gui")
    parser.add_argument(
        "--env",
        choices=tuple(_ENVIRONMENT_ALIASES),
        default="production",
    )
    parser.add_argument("--scenario-run-id")
    args = parser.parse_args(argv)

    qt_application = QGuiApplication(list(argv) if argv is not None else sys.argv)
    qt_application.setApplicationName("EquityLens")
    qt_application.setOrganizationName("EquityLens")
    qt_application.setWindowIcon(
        QIcon(
            str(
                files("stock_toolbox.desktop").joinpath(
                    "resources",
                    "toolbox.png",
                )
            )
        )
    )
    environment = _ENVIRONMENT_ALIASES[args.env]
    scenario_run_id = args.scenario_run_id
    if environment is RuntimeEnvironment.SCENARIO and scenario_run_id is None:
        scenario_run_id = f"manual-{uuid.uuid4()}"
    try:
        core = build_application(
            environment,
            home=Path.home(),
            scenario_run_id=scenario_run_id,
        )
    except Exception:  # noqa: BLE001 - safe bootstrap boundary
        print(
            "EquityLens 无法启动：本地数据初始化失败。",
            file=sys.stderr,
        )
        return 70
    _record_lifecycle(core, "startup")
    qt_application.aboutToQuit.connect(lambda: _shutdown_application(core))
    engine = build_pilot_engine(core, environment)
    window = cast(QWindow, engine.rootObjects()[0])
    window.show()
    activation = WindowActivationController(window, engine)
    qt_application.applicationStateChanged.connect(activation.restore_if_active)
    window.requestActivate()
    _record_lifecycle(core, "ready")
    return qt_application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
