"""Isolated deterministic developer scenarios exposed to QML."""

from __future__ import annotations

import json
from typing import cast

from PySide6.QtCore import Property, QObject, QRunnable, QThreadPool, Signal, Slot

from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.devtools.catalog import ScenarioCatalog
from stock_toolbox.devtools.runner import ScenarioRunner


class _ScenarioSignals(QObject):
    finished = Signal(object)


class _ScenarioTask(QRunnable):
    def __init__(
        self,
        application: StockToolboxApplication,
        scenario_id: str,
    ) -> None:
        super().__init__()
        self.application = application
        self.scenario_id = scenario_id
        self.signals = _ScenarioSignals()

    @Slot()
    def run(self) -> None:
        try:
            scenario = ScenarioCatalog.bundled().get(self.scenario_id)
            result: object = ScenarioRunner().run(
                scenario,
                home=self.application.home,
            )
        except Exception:  # noqa: BLE001 - sanitized developer boundary
            result = {"terminal": "failed", "error": "scenario_failed"}
        self.signals.finished.emit(result)


class ScenarioBridge(QObject):
    changed = Signal()
    finished = Signal(object)

    def __init__(
        self,
        application: StockToolboxApplication,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._task: _ScenarioTask | None = None
        self._result: dict[str, object] = {}

    @Property(list, constant=True)
    def scenarios(self) -> list[dict[str, str]]:
        return self._scenarios()

    def _scenarios(self) -> list[dict[str, str]]:
        return [
            {"id": item.id, "title": item.title}
            for item in ScenarioCatalog.bundled().list()
        ]

    @Property(str, constant=True)
    def isolation_note(self) -> str:
        return (
            "每次运行创建独立 Scenario 数据库和 Fake Secret Store；"
            "不会读取或修改正式数据库、正式凭据。"
        )

    @Property(bool, notify=changed)
    def running(self) -> bool:
        return self._task is not None

    @Property(dict, notify=changed)
    def result(self) -> dict[str, object]:
        return self._result

    @Property(str, notify=changed)
    def result_text(self) -> str:
        return (
            json.dumps(
                self._result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            if self._result
            else ""
        )

    @Slot(str, result=bool)
    def run_scenario(self, scenario_id: str) -> bool:
        if self._task is not None or not any(
            item["id"] == scenario_id for item in self._scenarios()
        ):
            return False
        task = _ScenarioTask(self._application, scenario_id)
        self._task = task
        self._result = {}
        task.signals.finished.connect(self._on_finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(object)
    def _on_finished(self, raw: object) -> None:
        self._task = None
        self._result = (
            cast(dict[str, object], raw)
            if isinstance(raw, dict)
            else {"terminal": "failed", "error": "invalid_result"}
        )
        self.changed.emit()
        self.finished.emit(raw)
