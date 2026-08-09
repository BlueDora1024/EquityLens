"""Physical provider-call plans for market-data preflight.

Logical work items describe how much analysis is performed.  Provider calls
describe the external resource cost after batching, pagination and local
aggregation.  Keeping both prevents a 220-bar Longbridge request from being
reported as one call when it is actually two 200-row pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from stock_toolbox.core.market_data.models import CandleInterval

PHYSICAL_REQUEST_WARNING_THRESHOLD = 50
_LONGBRIDGE_PAGE_SIZE = 200
_FUTU_PAGE_SIZE = 1_000
_FUTU_FIRST_PAGE_INTERVAL_SECONDS = 0.5
_TURNING_CANDLE_COUNT = 220
_EXTREME_CANDLE_COUNT = 650
_LONGBRIDGE_RAW_TURNING = frozenset({CandleInterval.MIN_120, CandleInterval.MIN_240})


@dataclass(frozen=True, slots=True)
class PhysicalRequestPlan:
    calculation_calls: int
    annotation_calls: int = 0
    quota_checks: int = 0
    page_size: int = 0
    minimum_seconds: float = 0.0
    warning_threshold: int = PHYSICAL_REQUEST_WARNING_THRESHOLD

    def __post_init__(self) -> None:
        if (
            self.calculation_calls < 0
            or self.annotation_calls < 0
            or self.quota_checks < 0
            or self.page_size < 0
            or self.minimum_seconds < 0
            or self.warning_threshold < 1
        ):
            raise ValueError("invalid physical request plan")

    @property
    def provider_calls(self) -> int:
        return self.calculation_calls + self.annotation_calls + self.quota_checks

    @property
    def requires_confirmation(self) -> bool:
        return self.provider_calls > self.warning_threshold


def plan_rs_requests(
    provider_id: str,
    *,
    member_count: int,
    cache_hits: int,
    quant_supported: bool = True,
) -> PhysicalRequestPlan:
    total = member_count + 1
    _validate_counts(total, cache_hits)
    provider = provider_id.strip().casefold()
    cold = total - cache_hits
    if cold == 0:
        return PhysicalRequestPlan(0)
    if provider == "yahoo":
        # Benchmark fail-fast and member batch are intentionally separate.
        return PhysicalRequestPlan(1 if member_count == 0 else 2)
    if provider == "futu":
        return PhysicalRequestPlan(
            cold,
            quota_checks=1,
            page_size=_FUTU_PAGE_SIZE,
            minimum_seconds=cold * _FUTU_FIRST_PAGE_INTERVAL_SECONDS,
        )
    if provider == "longbridge" and quant_supported:
        return PhysicalRequestPlan(cold)
    return PhysicalRequestPlan(cold, page_size=_LONGBRIDGE_PAGE_SIZE)


def plan_turning_requests(
    provider_id: str,
    *,
    member_count: int,
    intervals: tuple[CandleInterval, ...],
    quant_cache_hits: int,
    raw_cache_hits: int = 0,
    quant_supported: bool = True,
) -> PhysicalRequestPlan:
    if member_count < 0 or not intervals:
        raise ValueError("invalid turning request plan")
    provider = provider_id.strip().casefold()
    unique_intervals = tuple(dict.fromkeys(intervals))
    if provider == "yahoo":
        total = member_count * len(unique_intervals)
        _validate_counts(total, raw_cache_hits)
        calls = 0 if raw_cache_hits == total else len(_yahoo_families(unique_intervals))
        return PhysicalRequestPlan(calls)
    if provider == "futu":
        total = member_count * len(unique_intervals)
        _validate_counts(total, raw_cache_hits)
        calculation = total - raw_cache_hits
        annotation = ceil(member_count / 400) if member_count else 0
        return PhysicalRequestPlan(
            calculation,
            annotation_calls=annotation,
            quota_checks=(1 if calculation else 0),
            page_size=_FUTU_PAGE_SIZE,
            minimum_seconds=calculation * _FUTU_FIRST_PAGE_INTERVAL_SECONDS,
        )

    if quant_supported:
        raw_intervals = (
            tuple(interval for interval in unique_intervals if interval in _LONGBRIDGE_RAW_TURNING)
            if provider == "longbridge"
            else ()
        )
    else:
        raw_intervals = unique_intervals
    quant_intervals = tuple(
        interval for interval in unique_intervals if interval not in raw_intervals
    )
    quant_total = member_count * len(quant_intervals)
    raw_total = member_count * len(raw_intervals)
    _validate_counts(quant_total, quant_cache_hits)
    _validate_counts(raw_total, raw_cache_hits)
    raw_pages = ceil(_TURNING_CANDLE_COUNT / _LONGBRIDGE_PAGE_SIZE)
    calculation = quant_total - quant_cache_hits + (raw_total - raw_cache_hits) * raw_pages
    annotation = ceil(member_count / 100) if member_count else 0
    return PhysicalRequestPlan(
        calculation,
        annotation_calls=annotation,
        page_size=_LONGBRIDGE_PAGE_SIZE,
    )


def plan_extreme_requests(
    provider_id: str,
    *,
    member_count: int,
    intervals: tuple[CandleInterval, ...],
    cache_hits: int,
) -> PhysicalRequestPlan:
    if member_count < 0 or not intervals:
        raise ValueError("invalid extreme request plan")
    unique_intervals = tuple(dict.fromkeys(intervals))
    total = member_count * len(unique_intervals)
    _validate_counts(total, cache_hits)
    cold = total - cache_hits
    provider = provider_id.strip().casefold()
    if cold == 0:
        return PhysicalRequestPlan(0)
    if provider == "yahoo":
        return PhysicalRequestPlan(len(_yahoo_families(unique_intervals)))
    if provider == "futu":
        return PhysicalRequestPlan(
            cold,
            quota_checks=1,
            page_size=_FUTU_PAGE_SIZE,
            minimum_seconds=cold * _FUTU_FIRST_PAGE_INTERVAL_SECONDS,
        )
    pages = ceil(_EXTREME_CANDLE_COUNT / _LONGBRIDGE_PAGE_SIZE)
    return PhysicalRequestPlan(
        cold * pages,
        page_size=_LONGBRIDGE_PAGE_SIZE,
    )


def _yahoo_families(
    intervals: tuple[CandleInterval, ...],
) -> frozenset[str]:
    family_by_interval = {
        CandleInterval.MIN_30: "30m",
        CandleInterval.MIN_60: "hourly",
        CandleInterval.MIN_120: "hourly",
        CandleInterval.MIN_240: "hourly",
        CandleInterval.DAY: "daily",
        CandleInterval.WEEK: "weekly",
    }
    return frozenset(family_by_interval[interval] for interval in intervals)


def _validate_counts(total: int, cache_hits: int) -> None:
    if total < 0 or not 0 <= cache_hits <= total:
        raise ValueError("invalid physical request counts")
