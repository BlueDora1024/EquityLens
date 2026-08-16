from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt

from stock_toolbox.desktop_qml.window_activation import WindowActivationController


@dataclass
class _Window:
    visible: bool = False
    minimized: bool = False
    show_calls: int = 0
    normal_calls: int = 0
    raise_calls: int = 0
    activate_calls: int = 0

    def isVisible(self) -> bool:
        return self.visible

    def visibility(self) -> object:
        return Qt.WindowMinimized if self.minimized else Qt.Windowed

    def show(self) -> None:
        self.visible = True
        self.show_calls += 1

    def showNormal(self) -> None:
        self.visible = True
        self.minimized = False
        self.normal_calls += 1

    def raise_(self) -> None:
        self.raise_calls += 1

    def requestActivate(self) -> None:
        self.activate_calls += 1


def test_application_activation_restores_and_focuses_existing_window() -> None:
    window = _Window(minimized=True)
    controller = WindowActivationController(window)  # type: ignore[arg-type]

    controller.restore_if_active(Qt.ApplicationActive)

    assert window.normal_calls == 1
    assert window.raise_calls == 1
    assert window.activate_calls == 1


def test_background_state_does_not_force_window_to_front() -> None:
    window = _Window()
    controller = WindowActivationController(window)  # type: ignore[arg-type]

    controller.restore_if_active(Qt.ApplicationInactive)

    assert window.show_calls == 0
    assert window.raise_calls == 0
