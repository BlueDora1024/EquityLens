"""Immutable contracts for the staged relative-strength engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

from stock_toolbox.core.market_data.models import PricePoint, PriceSeries

__all__ = ["PricePoint", "PriceSeries"]

ALGORITHM_VERSION = "rs-algorithm-v1"
RANGE_KINDS = frozenset(
    {
        "PRESET_1W",
        "PRESET_2W",
        "PRESET_1M",
        "PRESET_3M",
        "PRESET_6M",
        "PRESET_1Y",
        "CUSTOM",
    }
)


def _non_blank(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be blank")


def _ordinal(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _freeze_parameters(
    parameters: Sequence[Sequence[str]],
) -> tuple[tuple[str, str], ...]:
    copied: list[tuple[str, str]] = []
    keys: set[str] = set()
    for parameter in parameters:
        if len(parameter) != 2:
            raise ValueError("reason parameter must be a key/value pair")
        key, value = parameter
        _non_blank(key, "reason parameter key")
        if key in keys:
            raise ValueError("reason parameter keys must be unique")
        if not isinstance(value, str) or len(value) > 256:
            raise ValueError("reason parameter value must be a short string")
        keys.add(key)
        copied.append((key, value))
    return tuple(sorted(copied, key=lambda pair: pair[0]))


@dataclass(frozen=True, slots=True)
class RequestedRange:
    run_range_id: str
    key: str
    label: str
    kind: str
    ordinal: int
    requested_start_date: date
    requested_end_date: date

    def __post_init__(self) -> None:
        _non_blank(self.run_range_id, "run_range_id")
        _non_blank(self.key, "key")
        _non_blank(self.label, "label")
        if self.kind not in RANGE_KINDS:
            raise ValueError("kind is not supported")
        _ordinal(self.ordinal, "ordinal")
        if self.requested_start_date > self.requested_end_date:
            raise ValueError("requested start must not follow requested end")


@dataclass(frozen=True, slots=True)
class CalculationMember:
    run_member_id: str
    ordinal: int
    symbol: str
    classification_snapshot_key: str
    classification_name: str
    classification_normalized_name: str

    def __post_init__(self) -> None:
        _non_blank(self.run_member_id, "run_member_id")
        _ordinal(self.ordinal, "ordinal")
        _non_blank(self.symbol, "symbol")
        _non_blank(
            self.classification_snapshot_key,
            "classification_snapshot_key",
        )
        _non_blank(self.classification_name, "classification_name")
        _non_blank(
            self.classification_normalized_name,
            "classification_normalized_name",
        )


@dataclass(frozen=True, slots=True)
class MemberDataIssue:
    member_ordinal: int
    symbol: str
    stage: Literal["FETCH"]
    code: str
    reason_parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _ordinal(self.member_ordinal, "member_ordinal")
        _non_blank(self.symbol, "symbol")
        if self.stage != "FETCH":
            raise ValueError("member data issue stage must be FETCH")
        _non_blank(self.code, "code")
        object.__setattr__(
            self,
            "reason_parameters",
            _freeze_parameters(self.reason_parameters),
        )


@dataclass(frozen=True, slots=True)
class RunCalculationInput:
    algorithm_version: str
    benchmark_symbol: str
    requested_ranges: tuple[RequestedRange, ...]
    members: tuple[CalculationMember, ...]
    series_by_symbol: Mapping[str, PriceSeries]
    member_data_issues: tuple[MemberDataIssue, ...]

    def __post_init__(self) -> None:
        _non_blank(self.algorithm_version, "algorithm_version")
        _non_blank(self.benchmark_symbol, "benchmark_symbol")
        object.__setattr__(self, "requested_ranges", tuple(self.requested_ranges))
        object.__setattr__(self, "members", tuple(self.members))
        copied = {
            key: self.series_by_symbol[key] for key in sorted(self.series_by_symbol)
        }
        object.__setattr__(
            self,
            "series_by_symbol",
            MappingProxyType(copied),
        )
        object.__setattr__(
            self,
            "member_data_issues",
            tuple(self.member_data_issues),
        )


@dataclass(frozen=True, slots=True)
class ResolvedRange:
    run_range_id: str
    key: str
    label: str
    kind: str
    ordinal: int
    requested_start_date: date
    requested_end_date: date
    actual_start_date: date
    actual_end_date: date
    benchmark_start_close: Decimal
    benchmark_end_close: Decimal
    base_weight: Decimal
    normalized_weight: Decimal


@dataclass(frozen=True, slots=True)
class StockRSResult:
    run_member_id: str
    member_ordinal: int
    symbol: str
    run_range_id: str
    range_key: str
    range_label: str
    range_kind: str
    range_ordinal: int
    stock_start_close: Decimal
    stock_end_close: Decimal
    benchmark_start_close: Decimal
    benchmark_end_close: Decimal
    stock_return: Decimal
    benchmark_return: Decimal
    rs: Decimal
    unit: Literal["percentage_points"] = "percentage_points"


@dataclass(frozen=True, slots=True)
class CalculationFailureDraft:
    scope: Literal["MEMBER", "MEMBER_RANGE"]
    member_ordinal: int
    symbol: str
    range_key: str | None
    range_ordinal: int | None
    stage: Literal["FETCH", "VALIDATE", "CALCULATE"]
    code: str
    reason_parameters: tuple[tuple[str, str], ...]
    fatal: Literal[False] = False

    def __post_init__(self) -> None:
        if self.scope not in {"MEMBER", "MEMBER_RANGE"}:
            raise ValueError("unsupported failure scope")
        _ordinal(self.member_ordinal, "member_ordinal")
        _non_blank(self.symbol, "symbol")
        if self.scope == "MEMBER_RANGE":
            if self.range_key is None or self.range_ordinal is None:
                raise ValueError("member-range failure requires range identity")
            _non_blank(self.range_key, "range_key")
            _ordinal(self.range_ordinal, "range_ordinal")
        elif self.range_key is not None or self.range_ordinal is not None:
            raise ValueError("member failure cannot include range identity")
        if self.stage not in {"FETCH", "VALIDATE", "CALCULATE"}:
            raise ValueError("unsupported failure stage")
        _non_blank(self.code, "code")
        if self.fatal is not False:
            raise ValueError("calculation failure draft cannot be fatal")
        object.__setattr__(
            self,
            "reason_parameters",
            _freeze_parameters(self.reason_parameters),
        )


@dataclass(frozen=True, slots=True)
class CalculationFailureCandidate(CalculationFailureDraft):
    stable_ordinal: int = 0

    def __post_init__(self) -> None:
        super(CalculationFailureCandidate, self).__post_init__()
        _ordinal(self.stable_ordinal, "stable_ordinal")


@dataclass(frozen=True, slots=True)
class CalculationFatalIssue:
    stage: Literal["VALIDATE", "CALCULATE", "AGGREGATE", "FINALIZE"]
    code: str
    range_key: str | None
    reason_parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _non_blank(self.code, "code")
        object.__setattr__(
            self,
            "reason_parameters",
            _freeze_parameters(self.reason_parameters),
        )


@dataclass(frozen=True, slots=True)
class ResolvedBenchmarkRanges:
    algorithm_version: str
    benchmark_symbol: str
    ranges: tuple[ResolvedRange, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "ranges", tuple(self.ranges))


@dataclass(frozen=True, slots=True)
class MemberNormalizationChunkOutput:
    member_ordinals: tuple[int, ...]
    normalized_series_by_symbol: Mapping[str, PriceSeries]
    failure_drafts: tuple[CalculationFailureDraft, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "member_ordinals", tuple(self.member_ordinals))
        copied = {
            key: self.normalized_series_by_symbol[key]
            for key in sorted(self.normalized_series_by_symbol)
        }
        object.__setattr__(
            self,
            "normalized_series_by_symbol",
            MappingProxyType(copied),
        )
        object.__setattr__(self, "failure_drafts", tuple(self.failure_drafts))


@dataclass(frozen=True, slots=True)
class PreparedCalculation:
    algorithm_version: str
    benchmark_symbol: str
    ranges: tuple[ResolvedRange, ...]
    members: tuple[CalculationMember, ...]
    normalized_series_by_symbol: Mapping[str, PriceSeries]
    initial_failure_drafts: tuple[CalculationFailureDraft, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "ranges", tuple(self.ranges))
        object.__setattr__(self, "members", tuple(self.members))
        copied = {
            key: self.normalized_series_by_symbol[key]
            for key in sorted(self.normalized_series_by_symbol)
        }
        object.__setattr__(
            self,
            "normalized_series_by_symbol",
            MappingProxyType(copied),
        )
        object.__setattr__(
            self,
            "initial_failure_drafts",
            tuple(self.initial_failure_drafts),
        )


@dataclass(frozen=True, slots=True)
class MemberCalculationChunkOutput:
    member_ordinals: tuple[int, ...]
    stock_results: tuple[StockRSResult, ...]
    failure_drafts: tuple[CalculationFailureDraft, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "member_ordinals", tuple(self.member_ordinals))
        object.__setattr__(self, "stock_results", tuple(self.stock_results))
        object.__setattr__(self, "failure_drafts", tuple(self.failure_drafts))


@dataclass(frozen=True, slots=True)
class StockCalculationOutput:
    stock_results: tuple[StockRSResult, ...]
    failure_candidates: tuple[CalculationFailureCandidate, ...]
    valid_member_count: int
    failed_member_count: int
    failed_member_range_count: int


@dataclass(frozen=True, slots=True)
class RankedMemberRS:
    run_member_id: str
    member_ordinal: int
    symbol: str
    rs: Decimal


@dataclass(frozen=True, slots=True)
class ClassificationPeriodBase:
    classification_snapshot_key: str
    classification_name: str
    classification_normalized_name: str
    run_range_id: str
    range_key: str
    range_label: str
    range_kind: str
    range_ordinal: int
    total_member_count: int
    valid_member_count: int
    coverage: Decimal
    mean_rs: Decimal | None
    median_rs: Decimal | None
    positive_count: int
    strong_breadth: Decimal | None
    top_members: tuple[RankedMemberRS, ...]
    bottom_members: tuple[RankedMemberRS, ...]
    eligibility: str
    eligibility_reason: str | None


@dataclass(frozen=True, slots=True)
class ClassificationBaseChunkOutput:
    classification_keys: tuple[str, ...]
    period_bases: tuple[ClassificationPeriodBase, ...]


@dataclass(frozen=True, slots=True)
class ClassificationPeriodResult(ClassificationPeriodBase):
    median_percentile: Decimal | None
    breadth_percentile: Decimal | None
    period_score: Decimal | None
    score_unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class ClassificationStrengthResult:
    classification_snapshot_key: str
    classification_name: str
    classification_normalized_name: str
    period_results: tuple[ClassificationPeriodResult, ...]
    composite_score: Decimal | None
    status: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class RunCalculationOutput:
    algorithm_version: str
    resolved_ranges: tuple[ResolvedRange, ...]
    stock_results: tuple[StockRSResult, ...]
    classification_period_results: tuple[ClassificationPeriodResult, ...]
    classification_results: tuple[ClassificationStrengthResult, ...]
    failure_candidates: tuple[CalculationFailureCandidate, ...]
    valid_member_count: int
    failed_member_count: int
    failed_member_range_count: int
