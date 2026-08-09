"""Monotonic spans and best-effort process memory snapshots."""

from __future__ import annotations

import ctypes
import platform
import resource
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Self

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticLogger,
    DiagnosticStatus,
    DiagnosticValue,
)

_MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    rss_mb: float | None
    peak_mb: float | None


class _TimeValue(ctypes.Structure):
    _fields_ = (("seconds", ctypes.c_int32), ("microseconds", ctypes.c_int32))


class _MachTaskBasicInfo(ctypes.Structure):
    _fields_ = (
        ("virtual_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("resident_size_max", ctypes.c_uint64),
        ("user_time", _TimeValue),
        ("system_time", _TimeValue),
        ("policy", ctypes.c_int32),
        ("suspend_count", ctypes.c_int32),
    )


def sample_process_memory() -> MemorySnapshot:
    rss_mb = _mac_current_rss_mb() if platform.system() == "Darwin" else None
    peak_mb: float | None = None
    try:
        raw_peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        peak_mb = (
            raw_peak / _MIB
            if platform.system() == "Darwin"
            else raw_peak / 1024
        )
    except (OSError, ValueError):
        pass
    return MemorySnapshot(rss_mb, peak_mb)


def _mac_current_rss_mb() -> float | None:
    try:
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        info = _MachTaskBasicInfo()
        count = ctypes.c_uint32(
            ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_uint32)
        )
        task = library.mach_task_self()
        result = library.task_info(
            task,
            20,
            ctypes.byref(info),
            ctypes.byref(count),
        )
        return float(info.resident_size) / _MIB if result == 0 else None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


class DiagnosticSpan:
    """Emit a paired start/terminal event without affecting the caller."""

    def __init__(
        self,
        logger: DiagnosticLogger,
        *,
        module: str,
        action: str,
        task_id: str = "",
        stage: str = "",
        ticker: str = "",
        details: Mapping[str, DiagnosticValue] | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        memory: Callable[[], MemorySnapshot] = sample_process_memory,
    ) -> None:
        self._logger = logger
        self._module = module
        self._action = action
        self._task_id = task_id
        self._stage = stage
        self._ticker = ticker
        self._details = dict(details or {})
        self._monotonic_ns = monotonic_ns
        self._memory = memory
        self._started_ns: int | None = None
        self._finished = False

    def start(self) -> Self:
        if self._started_ns is not None:
            return self
        self._started_ns = self._monotonic_ns()
        self._emit(DiagnosticStatus.STARTED)
        return self

    def finish(
        self,
        status: DiagnosticStatus,
        *,
        error_code: str = "",
        details: Mapping[str, DiagnosticValue] | None = None,
    ) -> None:
        if self._finished:
            return
        if self._started_ns is None:
            self.start()
        assert self._started_ns is not None
        duration_ms = max(
            0,
            (self._monotonic_ns() - self._started_ns) // 1_000_000,
        )
        merged = {**self._details, **dict(details or {})}
        self._emit(
            status,
            duration_ms=duration_ms,
            error_code=error_code,
            details=merged,
        )
        self._finished = True

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exception, traceback
        self.finish(
            DiagnosticStatus.SUCCEEDED
            if exception_type is None
            else DiagnosticStatus.FAILED,
            error_code="" if exception_type is None else "unhandled_error",
        )
        return False

    def _emit(
        self,
        status: DiagnosticStatus,
        *,
        duration_ms: int | None = None,
        error_code: str = "",
        details: Mapping[str, DiagnosticValue] | None = None,
    ) -> None:
        try:
            memory = self._memory()
            self._logger.emit(
                DiagnosticEvent(
                    DiagnosticLevel.ERROR
                    if status is DiagnosticStatus.FAILED
                    else DiagnosticLevel.INFO,
                    self._module,
                    self._action,
                    status,
                    task_id=self._task_id,
                    stage=self._stage,
                    ticker=self._ticker,
                    duration_ms=duration_ms,
                    memory_rss_mb=memory.rss_mb,
                    memory_peak_mb=memory.peak_mb,
                    error_code=error_code,
                    details=details or self._details,
                )
            )
        except (OSError, TypeError, ValueError):
            return
