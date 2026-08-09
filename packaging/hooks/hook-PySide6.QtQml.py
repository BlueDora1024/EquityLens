"""Collect only the QML modules imported by the desktop application."""

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

_QML_PREFIX = "PySide6/Qt/qml/"
_USED_MODULES = (
    "QtCore",
    "QtQml",
    "QtQml/Models",
    "QtQml/WorkerScript",
    "QtQuick",
    "QtQuick/Controls",
    "QtQuick/Controls/Basic",
    "QtQuick/Controls/Basic/impl",
    "QtQuick/Controls/impl",
    "QtQuick/Dialogs",
    "QtQuick/Dialogs/quickimpl",
    "QtQuick/Dialogs/quickimpl/qml",
    "QtQuick/Layouts",
    "QtQuick/Templates",
    "QtQuick/Window",
)


def _used(entry: tuple[str, str]) -> bool:
    destination = entry[1].removeprefix(_QML_PREFIX)
    return destination in _USED_MODULES


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()
binaries += [entry for entry in qml_binaries if _used(entry)]
datas += [entry for entry in qml_datas if _used(entry)]
