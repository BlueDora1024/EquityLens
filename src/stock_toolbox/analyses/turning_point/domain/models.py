"""Immutable turning-point screening results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ScreeningDecision(StrEnum):
    MATCHED = "MATCHED"
    NOT_MATCHED = "NOT_MATCHED"
    FAILED = "FAILED"


class TurningPointTradeSide(StrEnum):
    LEFT_CD = "LEFT_CD"
    RIGHT_CONFIRMED = "RIGHT_CONFIRMED"


@dataclass(frozen=True, slots=True)
class SymbolScreenResult:
    symbol: str
    decision: ScreeningDecision
    reason: str
    signal_kind: str | None = None
    signal_at: datetime | None = None
    crossed_at: datetime | None = None
    last_price: float | None = None
    volume_ratio: float | None = None
    quality_score: int | None = None
    enhanced_at: datetime | None = None
