"""Immutable self-contained records for frozen run history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class HistorySnapshotHeader:
    run_id: str
    run_identifier: str
    operation_id: str | None
    source: str
    status: str
    pinned: bool
    display_name: str
    note: str
    original_run_name: str
    started_at: datetime
    completed_at: datetime
    created_at: datetime
    imported_at: datetime | None
    provider_id: str
    provider_display_name: str
    provider_contract_version: str
    benchmark_symbol: str
    watchlist_source_id: str | None
    watchlist_name: str
    watchlist_revision: int | None
    requested_end_date: date
    actual_end_date: date
    member_count: int
    valid_member_count: int
    failed_member_count: int
    failed_member_range_count: int
    algorithm_version: str
    snapshot_format_version: str
    snapshot_extensions: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_extensions",
            MappingProxyType(dict(self.snapshot_extensions)),
        )


@dataclass(frozen=True, slots=True)
class HistoryRangeRecord:
    run_range_id: str
    run_id: str
    ordinal: int
    range_key: str
    label: str
    kind: str
    requested_start_date: date
    requested_end_date: date
    actual_start_date: date
    actual_end_date: date
    benchmark_start_close: Decimal
    benchmark_end_close: Decimal
    base_weight: Decimal
    normalized_weight: Decimal


@dataclass(frozen=True, slots=True)
class HistoryMemberRecord:
    id: str
    run_id: str
    ordinal: int
    source_membership_id: str | None
    source_security_id: str | None
    source_binding_id: str | None
    canonical_symbol: str
    market: str
    company_name: str
    classification_snapshot_key: str
    source_classification_id: str | None
    participating_classification_name: str
    participating_classification_normalized_name: str


@dataclass(frozen=True, slots=True)
class HistoryStockResultRecord:
    id: str
    run_id: str
    run_member_id: str
    run_range_id: str
    stock_start_close: Decimal
    stock_end_close: Decimal
    benchmark_start_close: Decimal
    benchmark_end_close: Decimal
    stock_return: Decimal
    benchmark_return: Decimal
    rs_percentage_points: Decimal


def _freeze_member_list(
    values: tuple[Mapping[str, Any], ...],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(MappingProxyType(dict(value)) for value in values)


@dataclass(frozen=True, slots=True)
class HistoryClassificationPeriodRecord:
    id: str
    run_id: str
    run_range_id: str
    classification_snapshot_key: str
    classification_name: str
    total_member_count: int
    valid_member_count: int
    coverage: Decimal
    mean_rs: Decimal | None
    median_rs: Decimal | None
    positive_member_count: int
    strong_breadth: Decimal | None
    top_members: tuple[Mapping[str, Any], ...]
    bottom_members: tuple[Mapping[str, Any], ...]
    eligibility: str
    eligibility_reason: str | None
    median_percentile: Decimal | None
    breadth_percentile: Decimal | None
    period_score: Decimal | None
    score_unavailable_reason: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "top_members",
            _freeze_member_list(self.top_members),
        )
        object.__setattr__(
            self,
            "bottom_members",
            _freeze_member_list(self.bottom_members),
        )


@dataclass(frozen=True, slots=True)
class HistoryClassificationRecord:
    id: str
    run_id: str
    classification_snapshot_key: str
    classification_name: str
    composite_score: Decimal | None
    multi_period_status: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class HistoryFailureRecord:
    id: str
    run_id: str
    run_member_id: str | None
    run_range_id: str | None
    scope: str
    canonical_symbol: str | None
    stage: str
    error_code: str
    reason: str
    fatal: bool
    ordinal: int


@dataclass(frozen=True, slots=True)
class HistorySnapshotRecord:
    header: HistorySnapshotHeader
    ranges: tuple[HistoryRangeRecord, ...]
    members: tuple[HistoryMemberRecord, ...]
    stock_results: tuple[HistoryStockResultRecord, ...]
    classification_period_results: tuple[
        HistoryClassificationPeriodRecord,
        ...,
    ]
    classification_results: tuple[HistoryClassificationRecord, ...]
    failures: tuple[HistoryFailureRecord, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "ranges",
            "members",
            "stock_results",
            "classification_period_results",
            "classification_results",
            "failures",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
