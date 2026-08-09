"""Small typed event contract; serialization belongs to infrastructure."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

type DiagnosticValue = str | int | float | bool | None

_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_CORRELATION = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_TICKER = re.compile(r"^[A-Za-z0-9.^_-]{1,32}$")


class DiagnosticLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"
    OBSERVED = "observed"


@dataclass(frozen=True, slots=True)
class DiagnosticEvent:
    level: DiagnosticLevel
    module: str
    action: str
    status: DiagnosticStatus
    task_id: str = ""
    stage: str = ""
    ticker: str = ""
    duration_ms: int | None = None
    memory_rss_mb: float | None = None
    memory_peak_mb: float | None = None
    error_code: str = ""
    details: Mapping[str, DiagnosticValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (("module", self.module), ("action", self.action)):
            if _NAME.fullmatch(value) is None:
                raise ValueError(f"{name} must be a stable diagnostic name")
        for name, value in (
            ("task_id", self.task_id),
            ("stage", self.stage),
            ("error_code", self.error_code),
        ):
            if value and _CORRELATION.fullmatch(value) is None:
                raise ValueError(f"{name} contains unsupported characters")
        if self.ticker and _TICKER.fullmatch(self.ticker) is None:
            raise ValueError("ticker contains unsupported characters")
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        copied: dict[str, DiagnosticValue] = {}
        for key, detail_value in self.details.items():
            if not isinstance(key, str) or _NAME.fullmatch(key) is None:
                raise ValueError("diagnostic detail keys must be stable names")
            if detail_value is not None and not isinstance(
                detail_value,
                (str, int, float, bool),
            ):
                raise TypeError("diagnostic detail values must be JSON primitives")
            copied[key] = detail_value
        object.__setattr__(self, "details", MappingProxyType(copied))


class DiagnosticLogger(Protocol):
    def emit(self, event: DiagnosticEvent) -> None: ...

    def flush(self, timeout_seconds: float = 1.0) -> bool: ...

    def close(self, timeout_seconds: float = 1.0) -> bool: ...


class NullDiagnosticLogger:
    """Default that keeps diagnostics optional at pure-domain boundaries."""

    def emit(self, event: DiagnosticEvent) -> None:
        del event

    def flush(self, timeout_seconds: float = 1.0) -> bool:
        del timeout_seconds
        return True

    def close(self, timeout_seconds: float = 1.0) -> bool:
        del timeout_seconds
        return True
