from __future__ import annotations

from PySide6.QtGui import QWindow

from stock_toolbox.desktop_qml.vibrancy import install_vibrancy


def test_vibrancy_uses_safe_fallback_for_offscreen_qt(qapp) -> None:
    window = QWindow()

    assert install_vibrancy(window, platform_name="offscreen") is False
