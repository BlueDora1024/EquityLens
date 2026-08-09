"""Optional macOS vibrancy installed behind the QML window."""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtGui import QGuiApplication, QWindow


class _Point(ctypes.Structure):
    _fields_ = (("x", ctypes.c_double), ("y", ctypes.c_double))


class _Size(ctypes.Structure):
    _fields_ = (("width", ctypes.c_double), ("height", ctypes.c_double))


class _Rect(ctypes.Structure):
    _fields_ = (("origin", _Point), ("size", _Size))


def _message(
    library: ctypes.CDLL,
    result: type[ctypes._CData] | None,
    *arguments: type[ctypes._CData],
) -> Callable[..., Any]:
    address = ctypes.cast(library.objc_msgSend, ctypes.c_void_p).value
    if address is None:
        raise RuntimeError("objc_msgSend_unavailable")
    return ctypes.CFUNCTYPE(result, ctypes.c_void_p, ctypes.c_void_p, *arguments)(
        address
    )


def install_vibrancy(
    window: QWindow,
    *,
    platform_name: str | None = None,
) -> bool:
    """Install NSVisualEffectView when Cocoa is available, otherwise no-op."""

    active_platform = platform_name or QGuiApplication.platformName()
    if sys.platform != "darwin" or active_platform != "cocoa":
        return False
    try:
        return _install_cocoa_vibrancy(window)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _install_cocoa_vibrancy(window: QWindow) -> bool:
    library_path = ctypes.util.find_library("objc")
    if library_path is None:
        return False
    library = ctypes.CDLL(library_path)
    library.objc_getClass.argtypes = (ctypes.c_char_p,)
    library.objc_getClass.restype = ctypes.c_void_p
    library.sel_registerName.argtypes = (ctypes.c_char_p,)
    library.sel_registerName.restype = ctypes.c_void_p

    def selector(name: bytes) -> int:
        value = library.sel_registerName(name)
        if not value:
            raise RuntimeError("objective_c_selector_unavailable")
        return int(value)

    visual_effect_class = library.objc_getClass(b"NSVisualEffectView")
    if not visual_effect_class:
        return False

    send_object = _message(library, ctypes.c_void_p)
    send_integer = _message(library, None, ctypes.c_long)
    send_rect = _message(library, ctypes.c_void_p, _Rect)
    send_positioned = _message(
        library,
        None,
        ctypes.c_void_p,
        ctypes.c_long,
        ctypes.c_void_p,
    )

    host_view = ctypes.c_void_p(int(window.winId()))
    superview = send_object(host_view, selector(b"superview"))
    if not superview:
        return False
    effect = send_object(visual_effect_class, selector(b"alloc"))
    effect = send_rect(
        effect,
        selector(b"initWithFrame:"),
        _Rect(_Point(0, 0), _Size(window.width(), window.height())),
    )
    if not effect:
        return False

    send_integer(effect, selector(b"setAutoresizingMask:"), 18)
    send_integer(effect, selector(b"setBlendingMode:"), 0)
    send_integer(effect, selector(b"setMaterial:"), 21)
    send_integer(effect, selector(b"setState:"), 1)
    send_positioned(
        superview,
        selector(b"addSubview:positioned:relativeTo:"),
        effect,
        -1,
        host_view,
    )
    return True
