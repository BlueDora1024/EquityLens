"""Background cache-only resource preflight shared by analysis bridges."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
)
from stock_toolbox.analyses.rs_strength.application.models import RunRequest
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
)
from stock_toolbox.composition import StockToolboxApplication


class BudgetTaskSignals(QObject):
    finished = Signal(object, object)


class AnalysisBudgetTask(QRunnable):
    def __init__(
        self,
        application: StockToolboxApplication,
        request: (
            RunRequest
            | TurningPointRequest
            | ExtremeDeviationRequest
        ),
    ) -> None:
        super().__init__()
        self.application = application
        self.request = request
        self.signals = BudgetTaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            if isinstance(self.request, RunRequest):
                result: object = self.application.estimate_rs_budget(
                    self.request
                )
            elif isinstance(self.request, TurningPointRequest):
                result = self.application.estimate_turning_budget(
                    self.request
                )
            else:
                result = self.application.estimate_extreme_budget(
                    self.request
                )
        except Exception as error:  # noqa: BLE001 - UI boundary
            result = error
        self.signals.finished.emit(self.request, result)
