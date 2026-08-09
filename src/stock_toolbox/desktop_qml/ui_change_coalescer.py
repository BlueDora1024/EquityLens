"""Bound high-frequency worker updates to one QML refresh per frame slice."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot


class UiChangeCoalescer(QObject):
    changed = Signal()

    def __init__(self, parent: QObject, *, interval_ms: int = 50) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.changed.emit)

    def request(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    @Slot()
    def cancel(self) -> None:
        self._timer.stop()
