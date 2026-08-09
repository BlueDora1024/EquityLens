"""Immutable DTOs and ports for one RS run."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from stock_toolbox.analyses.rs_strength.domain.models import RunCalculationOutput
from stock_toolbox.core.market_data.models import DailyBarsDataset, DailyBarsProviderPort
from stock_toolbox.core.master_data.models import WatchlistDTO
from stock_toolbox.core.operations.failure_policy import AnalysisReliability
from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.core.operations.run_feedback import RunFeedback

BarsResult = DailyBarsDataset
RunBarsPort = DailyBarsProviderPort
__all__ = ["BarsResult", "RunBarsPort"]

@dataclass(frozen=True, slots=True)
class CustomRange:
    start_date: date
    end_date: date


@dataclass(frozen=True, slots=True)
class RunRequest:
    watchlist_id: str
    benchmark_symbol: str
    requested_end_date: date
    preset_ranges: tuple[str, ...]
    custom_range: CustomRange | None


@dataclass(frozen=True, slots=True)
class RunProgress:
    stage: str
    completed: int
    total: int
    current: str | None = None
    succeeded: int | None = None
    failed: int | None = None
    feedback: RunFeedback | None = None


@dataclass(frozen=True, slots=True)
class CompletedRun:
    run_id: str
    operation_id: str
    started_at: datetime
    completed_at: datetime
    request: RunRequest
    watchlist: WatchlistDTO
    provider_id: str
    provider_display_name: str
    run_member_ids: tuple[str, ...]
    output: RunCalculationOutput
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


class RunStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    run_id: str | None = None
    output: RunCalculationOutput | None = None
    error_code: str | None = None
    reliability: AnalysisReliability | None = None


class RunWatchlistPort(Protocol):
    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO: ...


class CompletedRunStorePort(Protocol):
    def save(
        self,
        snapshot: CompletedRun,
        *,
        operation_control: OperationControl,
    ) -> bool: ...


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]
ProgressSink = Callable[[RunProgress], None]
