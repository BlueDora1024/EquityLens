"""Pure shared failure classification, circuit-breaking, and run reliability rules."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum


class FailureCode(StrEnum):
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    MALFORMED_RESPONSE = "malformed_response"
    DATA_UNAVAILABLE = "data_unavailable"
    INSUFFICIENT_DATA = "insufficient_data"
    DATABASE_BUSY = "database_busy"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    DATABASE_CORRUPT = "database_corrupt"
    MEMORY_EXHAUSTED = "memory_exhausted"
    INTERNAL = "internal"


class FailureDecision(StrEnum):
    RETRY = "retry"
    SKIP = "skip"
    STOP = "stop"


class RunTerminal(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


INFRASTRUCTURE_FAILURES = frozenset(
    {
        FailureCode.TIMEOUT,
        FailureCode.NETWORK_ERROR,
        FailureCode.SERVICE_UNAVAILABLE,
        FailureCode.RATE_LIMITED,
    }
)

_RELIABILITY_DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class RunReliabilitySummary:
    succeeded: int
    failed: int
    unexecuted: int
    success_rate: Decimal
    terminal: RunTerminal
    should_save: bool


@dataclass(frozen=True, slots=True)
class AnalysisReliability:
    """Stable scalar evidence frozen into analysis results and history."""

    succeeded_tasks: int
    failed_tasks: int
    unexecuted_tasks: int
    success_rate: Decimal
    circuit_opened: bool
    primary_failure_code: str | None


def freeze_reliability(
    summary: RunReliabilitySummary,
    *,
    circuit_opened: bool,
    primary_failure_code: str | None,
) -> AnalysisReliability:
    return AnalysisReliability(
        succeeded_tasks=summary.succeeded,
        failed_tasks=summary.failed,
        unexecuted_tasks=summary.unexecuted,
        success_rate=summary.success_rate,
        circuit_opened=circuit_opened,
        primary_failure_code=primary_failure_code,
    )


class CircuitBreaker:
    """Opens for persistent infrastructure failures within one run."""

    def __init__(self) -> None:
        self._recent: deque[FailureCode] = deque(maxlen=20)
        self._consecutive_code: FailureCode | None = None
        self._consecutive = 0
        self._open = False

    @property
    def open(self) -> bool:
        return self._open

    def record(self, code: FailureCode) -> bool:
        infrastructure = code in INFRASTRUCTURE_FAILURES
        self._recent.append(code)
        if infrastructure and code == self._consecutive_code:
            self._consecutive += 1
        else:
            self._consecutive = int(infrastructure)
        self._consecutive_code = code if infrastructure else None

        infrastructure_counts = Counter(
            item for item in self._recent if item in INFRASTRUCTURE_FAILURES
        )
        rolling_threshold_reached = (
            len(self._recent) == self._recent.maxlen
            and any(count >= 16 for count in infrastructure_counts.values())
        )
        self._open = self._open or self._consecutive >= 8 or rolling_threshold_reached
        return self._open


def reliability_summary(
    succeeded: int,
    failed: int,
    unexecuted: int,
    *,
    core_input_valid: bool = True,
    canceled: bool = False,
) -> RunReliabilitySummary:
    """Summarize a run without allowing skipped work to improve reliability."""
    if min(succeeded, failed, unexecuted) < 0:
        raise ValueError("reliability counts must be non-negative")

    total = succeeded + failed + unexecuted
    with localcontext(_RELIABILITY_DECIMAL_CONTEXT):
        success_rate = Decimal(succeeded) / Decimal(total) if total else Decimal(0)

    if total == 0:
        terminal = RunTerminal.FAILED
    elif succeeded == total:
        terminal = RunTerminal.READY
    elif succeeded * 5 >= total * 4:
        terminal = RunTerminal.PARTIAL
    else:
        terminal = RunTerminal.FAILED

    return RunReliabilitySummary(
        succeeded=succeeded,
        failed=failed,
        unexecuted=unexecuted,
        success_rate=success_rate,
        terminal=terminal,
        should_save=(
            core_input_valid and not canceled and terminal is not RunTerminal.FAILED
        ),
    )
