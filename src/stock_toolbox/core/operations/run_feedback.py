"""Observable provider recovery transitions for long-running operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stock_toolbox.core.operations.failure_policy import FailureCode


class FeedbackKind(StrEnum):
    RETRYING = "retrying"
    THROTTLED = "throttled"
    RECOVERED = "recovered"
    ITEM_SKIPPED = "item_skipped"
    CIRCUIT_OPEN = "circuit_open"
    FATAL = "fatal"


@dataclass(frozen=True, slots=True)
class RunFeedback:
    kind: FeedbackKind
    failure_code: FailureCode | None = None
    symbol: str = ""
    interval: str = ""
    attempt: int = 0
    max_attempts: int = 0
    wait_seconds: float = 0
    active_concurrency: int = 4
