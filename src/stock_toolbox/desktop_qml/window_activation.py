"""Restore the existing desktop window when macOS re-activates the app."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QObject, Qt, Slot


class _RestorableWindow(Protocol):
    def isVisible(self) -> bool: ...
    def visibility(self) -> object: ...
    def show(self) -> None: ...
    def showNormal(self) -> None: ...
    def raise_(self) -> None: ...
    def requestActivate(self) -> None: ...


class WindowActivationController(QObject):
    """Keep one running app instance discoverable from Dock/Finder re-open."""

    def __init__(
        self,
        window: _RestorableWindow,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window

    @Slot(Qt.ApplicationState)
    def restore_if_active(self, state: Qt.ApplicationState) -> None:
        if state != Qt.ApplicationState.ApplicationActive:
            return
        if self._window.visibility() == Qt.WindowState.WindowMinimized:
            self._window.showNormal()
        elif not self._window.isVisible():
            self._window.show()
        self._window.raise_()
        self._window.requestActivate()
