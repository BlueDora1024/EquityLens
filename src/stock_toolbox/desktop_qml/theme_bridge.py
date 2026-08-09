"""System appearance signal exposed to QML."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot
from PySide6.QtGui import QStyleHints

_MODES = frozenset({"system", "light", "dark"})


class ThemeBridge(QObject):
    changed = Signal()

    def __init__(
        self,
        hints: QStyleHints,
        parent: QObject | None = None,
        *,
        initial_mode: str = "system",
        save_mode: Callable[[str], None] = lambda _mode: None,
    ) -> None:
        super().__init__(parent)
        if initial_mode not in _MODES:
            initial_mode = "system"
        self._hints = hints
        self._mode = initial_mode
        self._save_mode = save_mode
        self._override: bool | None = None
        hints.colorSchemeChanged.connect(self._on_scheme_changed)

    @Property(str, notify=changed)
    def mode(self) -> str:
        return self._mode

    @Property(bool, notify=changed)
    def dark(self) -> bool:
        if self._override is not None:
            return self._override
        if self._mode != "system":
            return self._mode == "dark"
        return self._hints.colorScheme() is Qt.ColorScheme.Dark

    @Slot(str, result=bool)
    def set_mode(self, mode: str) -> bool:
        if mode not in _MODES:
            return False
        self._save_mode(mode)
        self._mode = mode
        self._override = None
        self.changed.emit()
        return True

    @Slot(str)
    def set_evidence_mode(self, mode: str) -> None:
        self._override = None if mode == "system" else mode == "dark"
        self.changed.emit()

    @Slot(Qt.ColorScheme)
    def _on_scheme_changed(self, _scheme: Qt.ColorScheme) -> None:
        if self._override is None and self._mode == "system":
            self.changed.emit()
