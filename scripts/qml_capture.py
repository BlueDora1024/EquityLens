"""Shared checked screenshot writer for QML evidence scripts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest


def save_window(
    window: QQuickWindow,
    target: Path,
    *,
    wait_ms: int = 0,
) -> None:
    if wait_ms:
        QTest.qWait(wait_ms)
    if not window.grabWindow().save(str(target)):
        raise RuntimeError(f"unable to save {target}")


def require_qml_object(
    root: QObject,
    object_name: str,
    description: str | None = None,
) -> QObject:
    """Return a named QML object or fail the evidence run with useful context."""
    target = root.findChild(QObject, object_name)
    if target is None:
        label = description or object_name
        raise RuntimeError(f"{label} is unavailable")
    return target
