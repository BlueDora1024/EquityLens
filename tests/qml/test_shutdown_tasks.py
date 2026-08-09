from __future__ import annotations

from datetime import date

from PySide6.QtTest import QSignalSpy

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
)
from stock_toolbox.analyses.rs_strength.application.models import RunRequest
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
)
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.desktop_qml.extreme_deviation_bridge import (
    ExtremeDeviationBridge,
)
from stock_toolbox.desktop_qml.extreme_deviation_bridge import (
    _Task as ExtremeTask,
)
from stock_toolbox.desktop_qml.rs_run_bridge import (
    RsRunBridge,
)
from stock_toolbox.desktop_qml.rs_run_bridge import (
    _CalendarTask as RsCalendarTask,
)
from stock_toolbox.desktop_qml.rs_run_bridge import (
    _RunTask as RsTask,
)
from stock_toolbox.desktop_qml.turning_point_bridge import (
    TurningPointBridge,
)
from stock_toolbox.desktop_qml.turning_point_bridge import (
    _Task as TurningTask,
)


def test_late_calendar_tasks_are_quiet_after_admission_closes(
    qapp,
    scenario_application,
) -> None:
    rs_bridge = RsRunBridge(scenario_application)
    rs_task = RsCalendarTask(scenario_application)
    rs_bridge._calendar_task = rs_task
    rs_task.signals.finished.connect(rs_bridge._on_calendar_finished)

    turning_bridge = TurningPointBridge(scenario_application)
    turning_task = TurningTask(scenario_application)
    turning_bridge._calendar_task = turning_task
    turning_task.signals.finished.connect(turning_bridge._on_finished)

    scenario_application.registry.close_admission()
    rs_task.run()
    turning_task.run()

    assert rs_bridge.calendar_loading is False
    assert turning_bridge.calendar_loading is False
    assert rs_bridge.end_date == ""
    assert turning_bridge.end_date == ""


def test_late_run_tasks_stop_quietly_without_terminal_or_history(
    qapp,
    scenario_application,
) -> None:
    requested_end = date(2026, 7, 24)
    rs_bridge = RsRunBridge(scenario_application)
    rs_task = RsTask(
        scenario_application,
        RunRequest(
            "late-watchlist",
            "SPY.US",
            requested_end,
            ("1M",),
            None,
        ),
    )
    rs_bridge._task = rs_task
    rs_bridge._running = True
    rs_finished = QSignalSpy(rs_bridge.finished)
    rs_task.signals.finished.connect(rs_bridge._on_finished)

    turning_bridge = TurningPointBridge(scenario_application)
    turning_task = TurningTask(
        scenario_application,
        request=TurningPointRequest(
            "late-watchlist",
            (CandleInterval.DAY,),
            requested_end,
        ),
    )
    turning_bridge._task = turning_task
    turning_bridge._running = True
    turning_finished = QSignalSpy(turning_bridge.finished)
    turning_task.signals.finished.connect(turning_bridge._on_finished)

    extreme_bridge = ExtremeDeviationBridge(scenario_application)
    extreme_task = ExtremeTask(
        scenario_application,
        request=ExtremeDeviationRequest(
            "late-watchlist",
            (CandleInterval.DAY,),
            requested_end,
        ),
    )
    extreme_bridge._task = extreme_task
    extreme_bridge._running = True
    extreme_finished = QSignalSpy(extreme_bridge.finished)
    extreme_task.signals.finished.connect(extreme_bridge._on_finished)

    scenario_application.registry.close_admission()
    rs_task.run()
    turning_task.run()
    extreme_task.run()

    assert rs_bridge.running is False
    assert turning_bridge.running is False
    assert extreme_bridge.running is False
    assert rs_bridge.last_status == ""
    assert turning_bridge.last_status == ""
    assert extreme_bridge.last_status == ""
    assert rs_finished.count() == 0
    assert turning_finished.count() == 0
    assert extreme_finished.count() == 0
    assert turning_bridge.history == []
    assert extreme_bridge.history == []
