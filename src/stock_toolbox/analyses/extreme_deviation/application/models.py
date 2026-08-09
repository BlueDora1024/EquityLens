"""Requests, progress, frozen results, and terminal status."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType

from stock_toolbox.analyses.extreme_deviation.domain.consensus import (
    MultiPeriodConsensus,
)
from stock_toolbox.analyses.extreme_deviation.domain.scoring import PeriodScore
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.operations.failure_policy import AnalysisReliability
from stock_toolbox.core.operations.run_feedback import RunFeedback


@dataclass(frozen=True, slots=True)
class ExtremeDeviationRequest:
    watchlist_id: str
    intervals: tuple[CandleInterval, ...]
    requested_end_date: date
    selected_symbols: tuple[str, ...] = ()
    security_id: str = ""


@dataclass(frozen=True, slots=True)
class ExtremeDeviationProgress:
    stage: str
    completed: int
    total: int
    current: str | None = None
    cache_hits: int = 0
    fetched: int = 0
    failures: int = 0
    feedback: RunFeedback | None = None


@dataclass(frozen=True, slots=True)
class FrozenSecurity:
    symbol: str
    company_name: str
    classification_name: str


@dataclass(frozen=True, slots=True)
class DeviationChartPoint:
    """One completed OHLC bar with frozen score and original pressure."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    score: int | None
    label: str | None
    buy_pressure: float = 0.0
    sell_pressure: float = 0.0


@dataclass(frozen=True, slots=True)
class PeriodOutcome:
    interval: CandleInterval
    candle_count: int
    score: PeriodScore | None
    error_code: str | None = None
    chart_points: tuple[DeviationChartPoint, ...] = ()


@dataclass(frozen=True, slots=True)
class SymbolDeviationResult:
    symbol: str
    company_name: str
    classification_name: str
    periods: tuple[PeriodOutcome, ...]
    consensus: MultiPeriodConsensus
    status: str

    @property
    def successful_periods(self) -> int:
        return sum(item.score is not None and item.score.score is not None for item in self.periods)


class ExtremeDeviationRunStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class ExtremeDeviationRun:
    run_id: str
    operation_id: str
    started_at: datetime
    completed_at: datetime
    request: ExtremeDeviationRequest
    watchlist_name: str
    watchlist_revision: int
    securities: tuple[FrozenSecurity, ...]
    provider_id: str
    provider_display_name: str
    cache_hits: int
    fetched: int
    results: tuple[SymbolDeviationResult, ...]
    algorithm_version: str = "extreme-deviation-v2"
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


@dataclass(frozen=True, slots=True)
class ExtremeDeviationRunResult:
    status: ExtremeDeviationRunStatus
    run: ExtremeDeviationRun | None = None
    error_code: str | None = None
    reliability: AnalysisReliability | None = None

    @property
    def run_id(self) -> str | None:
        return self.run.run_id if self.run is not None else None
