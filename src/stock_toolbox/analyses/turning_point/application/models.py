"""Requests, progress and run results for turning-point screening."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from stock_toolbox.analyses.turning_point.domain.attention import (
    AttentionEvidence,
    AttentionScore,
    attention_conclusion,
    attention_level,
    attention_score,
    attention_score_for_evidence,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    SymbolScreenResult,
    TurningPointTradeSide,
)
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.operations.failure_policy import AnalysisReliability
from stock_toolbox.core.operations.run_feedback import RunFeedback


@dataclass(frozen=True, slots=True)
class TurningPointRequest:
    watchlist_id: str
    intervals: tuple[CandleInterval, ...]
    requested_end_date: date
    trade_side: TurningPointTradeSide = TurningPointTradeSide.RIGHT_CONFIRMED

    def __post_init__(self) -> None:
        raw = self.intervals
        normalized = (raw,) if isinstance(raw, CandleInterval) else tuple(raw)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("intervals must be non-empty and unique")
        object.__setattr__(self, "intervals", normalized)

    @property
    def interval(self) -> CandleInterval:
        """Compatibility projection for old single-period callers."""
        return self.intervals[0]


@dataclass(frozen=True, slots=True)
class TurningPointProgress:
    stage: str
    completed: int
    total: int
    current: str | None = None
    feedback: RunFeedback | None = None


class TurningPointRunStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class PeriodScreenResult:
    interval: CandleInterval
    decision: str
    reason: str
    signal_kind: str | None = None
    signal_at: datetime | None = None
    crossed_at: datetime | None = None
    last_price: float | None = None
    volume_ratio: float | None = None
    quality_score: int | None = None
    enhanced_at: datetime | None = None

    @classmethod
    def from_screen(
        cls,
        interval: CandleInterval,
        result: SymbolScreenResult,
    ) -> PeriodScreenResult:
        return cls(
            interval,
            result.decision.value,
            result.reason,
            result.signal_kind,
            result.signal_at,
            result.crossed_at,
            result.last_price,
            result.volume_ratio,
            result.quality_score,
            result.enhanced_at,
        )


@dataclass(frozen=True, slots=True)
class SymbolTurningResult:
    symbol: str
    company_name: str
    classification_name: str
    period_results: tuple[PeriodScreenResult, ...]
    attention_score: int
    attention_level: str
    conclusion: str
    status: str
    market_value_usd: int | None = None
    risk_flags: tuple[str, ...] = ()
    attention_breakdown: AttentionScore | None = None

    @classmethod
    def build(
        cls,
        symbol: str,
        company_name: str,
        classification_name: str,
        period_results: tuple[PeriodScreenResult, ...],
    ) -> SymbolTurningResult:
        matched = tuple(
            item for item in period_results if item.decision == "MATCHED"
        )
        failed = sum(item.decision == "FAILED" for item in period_results)
        evidence = tuple(
            AttentionEvidence(
                item.interval,
                _completed_signal_at(item.signal_at, item.interval),
                right_confirmed=item.crossed_at is not None,
            )
            for item in matched
            if item.signal_at is not None
        )
        breakdown = attention_score_for_evidence(evidence)
        score = (
            breakdown.total
            if evidence
            else attention_score(item.interval for item in matched)
        )
        return cls(
            symbol,
            company_name,
            classification_name,
            period_results,
            score,
            attention_level(score),
            attention_conclusion(
                (item.interval for item in matched),
                (
                    item.signal_kind
                    for item in matched
                    if item.signal_kind is not None
                ),
                score=score,
            ),
            (
                "FAILED"
                if failed == len(period_results)
                else "PARTIAL"
                if failed
                else "READY"
            ),
            attention_breakdown=breakdown if evidence else None,
        )

    @property
    def matched_periods(self) -> tuple[CandleInterval, ...]:
        return tuple(
            item.interval
            for item in self.period_results
            if item.decision == "MATCHED"
        )


_INTRADAY_LENGTHS = {
    CandleInterval.MIN_30: timedelta(minutes=30),
    CandleInterval.MIN_60: timedelta(minutes=60),
    CandleInterval.MIN_120: timedelta(minutes=120),
    CandleInterval.MIN_240: timedelta(minutes=240),
}


def _completed_signal_at(value: datetime, interval: CandleInterval) -> datetime:
    return value + _INTRADAY_LENGTHS.get(interval, timedelta())


@dataclass(frozen=True, slots=True)
class TurningPointRun:
    run_id: str
    operation_id: str
    started_at: datetime
    completed_at: datetime
    request: TurningPointRequest
    watchlist_name: str
    watchlist_revision: int
    provider_id: str
    provider_display_name: str
    results: tuple[SymbolTurningResult, ...]
    algorithm_version: str = "turning-point-v7"
    reliability: AnalysisReliability | None = None
    source_by_symbol: Mapping[str, str] = field(default_factory=dict)
    requested_date_window: tuple[date, date] | None = None
    actual_date_window: tuple[date, date] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_by_symbol",
            MappingProxyType(dict(self.source_by_symbol)),
        )

    @property
    def matched_count(self) -> int:
        return sum(bool(item.matched_periods) for item in self.results)

    @property
    def failed_count(self) -> int:
        return sum(
            period.decision == "FAILED"
            for item in self.results
            for period in item.period_results
        )


@dataclass(frozen=True, slots=True)
class TurningPointRunResult:
    status: TurningPointRunStatus
    run: TurningPointRun | None = None
    error_code: str | None = None
    reliability: AnalysisReliability | None = None

    @property
    def run_id(self) -> str | None:
        return self.run.run_id if self.run is not None else None
