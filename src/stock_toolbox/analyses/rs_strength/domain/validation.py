"""Input normalization and benchmark range resolution."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Hashable, Iterable
from dataclasses import replace
from datetime import date

from stock_toolbox.analyses.rs_strength.domain.models import (
    ALGORITHM_VERSION,
    CalculationFatalIssue,
    PricePoint,
    PriceSeries,
    ResolvedBenchmarkRanges,
    ResolvedRange,
    RunCalculationInput,
)
from stock_toolbox.analyses.rs_strength.domain.numeric import (
    base_weight,
    normalize_weights,
    validate_close,
)
from stock_toolbox.core.market_data.date_policy import boundary_within_buffer

_MINIMUM_MEMBER_COVERAGE_NUMERATOR = 4
_MINIMUM_MEMBER_COVERAGE_DENOMINATOR = 5


def _fatal(
    code: str,
    *,
    range_key: str | None = None,
    **parameters: str,
) -> CalculationFatalIssue:
    return CalculationFatalIssue(
        stage="VALIDATE",
        code=code,
        range_key=range_key,
        reason_parameters=tuple(parameters.items()),
    )


def _has_duplicate(values: Iterable[Hashable]) -> bool:
    items = tuple(values)
    return len(items) != len(set(items))


def normalize_price_series(series: PriceSeries) -> PriceSeries:
    """Validate and return a new date-sorted immutable price series."""

    if not series.points:
        raise ValueError("price series must not be empty")
    seen: set[date] = set()
    copied: list[PricePoint] = []
    for point in series.points:
        if not isinstance(point, PricePoint) or not isinstance(point.date, date):
            raise TypeError("price point is invalid")
        if point.date in seen:
            raise ValueError("price series contains a duplicate date")
        seen.add(point.date)
        copied.append(PricePoint(point.date, validate_close(point.close)))
    copied.sort(key=lambda point: point.date)
    return PriceSeries(series.symbol, tuple(copied))


def align_benchmark_to_member_coverage(
    input: RunCalculationInput,
) -> RunCalculationInput:
    """Drop a newer benchmark tail when at least 80% of members share an earlier day.

    Providers may expose the ETF benchmark through daily K-lines while returning
    stocks through a server-side quant route that settles one day later.  Alignment
    only inspects the already-fetched data and stays inside the normal end-date
    buffer; it never performs a compensating market-data request.
    """

    benchmark = input.series_by_symbol.get(input.benchmark_symbol)
    if benchmark is None or not input.members or not input.requested_ranges:
        return input
    requested_end = max(
        item.requested_end_date for item in input.requested_ranges
    )
    candidates = tuple(
        sorted(
            {
                point.date
                for point in benchmark.points
                if point.date <= requested_end
                and boundary_within_buffer(
                    requested_end,
                    point.date,
                    side="end",
                )
            },
            reverse=True,
        )
    )
    member_dates = {
        member.symbol: {
            point.date
            for point in input.series_by_symbol.get(
                member.symbol,
                PriceSeries(member.symbol, ()),
            ).points
        }
        for member in input.members
    }
    aligned_end = next(
        (
            candidate
            for candidate in candidates
            if sum(
                candidate in member_dates[member.symbol]
                for member in input.members
            )
            * _MINIMUM_MEMBER_COVERAGE_DENOMINATOR
            >= len(input.members) * _MINIMUM_MEMBER_COVERAGE_NUMERATOR
        ),
        None,
    )
    if aligned_end is None:
        return input
    benchmark_tail = tuple(
        point for point in benchmark.points if point.date <= aligned_end
    )
    if len(benchmark_tail) == len(benchmark.points):
        return input
    series_by_symbol = dict(input.series_by_symbol)
    series_by_symbol[input.benchmark_symbol] = PriceSeries(
        benchmark.symbol,
        benchmark_tail,
    )
    return replace(input, series_by_symbol=series_by_symbol)


def _validate_unique_dimensions(input: RunCalculationInput) -> str | None:
    ranges = input.requested_ranges
    members = input.members
    checks: tuple[tuple[Iterable[Hashable], str], ...] = (
        ((item.run_range_id for item in ranges), "RANGE_ID_DUPLICATE"),
        ((item.key for item in ranges), "RANGE_KEY_DUPLICATE"),
        ((item.ordinal for item in ranges), "RANGE_ORDINAL_DUPLICATE"),
        ((item.run_member_id for item in members), "MEMBER_ID_DUPLICATE"),
        ((item.symbol for item in members), "MEMBER_SYMBOL_DUPLICATE"),
        ((item.ordinal for item in members), "MEMBER_ORDINAL_DUPLICATE"),
    )
    for values, code in checks:
        if _has_duplicate(values):
            return code
    return None


def resolve_benchmark_and_ranges(
    input: RunCalculationInput,
) -> ResolvedBenchmarkRanges | CalculationFatalIssue:
    """Normalize the benchmark once and resolve every requested range."""

    if input.algorithm_version != ALGORITHM_VERSION:
        return _fatal(
            "ALGORITHM_VERSION_UNSUPPORTED",
            algorithm_version=input.algorithm_version,
        )
    duplicate = _validate_unique_dimensions(input)
    if duplicate is not None:
        return _fatal(duplicate)
    if not input.requested_ranges:
        return _fatal("RANGES_EMPTY")
    benchmark = input.series_by_symbol.get(input.benchmark_symbol)
    if benchmark is None:
        return _fatal("BENCHMARK_SERIES_MISSING")
    if benchmark.symbol != input.benchmark_symbol:
        return _fatal("BENCHMARK_SYMBOL_MISMATCH")
    try:
        normalized = normalize_price_series(benchmark)
    except (ArithmeticError, TypeError, ValueError):
        return _fatal("BENCHMARK_SERIES_INVALID")

    dates = tuple(point.date for point in normalized.points)
    closes = tuple(point.close for point in normalized.points)
    ordered_ranges = tuple(
        sorted(
            input.requested_ranges,
            key=lambda item: (item.ordinal, item.key, item.run_range_id),
        )
    )
    weights = tuple(
        base_weight(item.requested_start_date, item.requested_end_date)
        for item in ordered_ranges
    )
    normalized_weights = normalize_weights(weights)

    resolved: list[ResolvedRange] = []
    for requested, weight, normalized_weight in zip(
        ordered_ranges,
        weights,
        normalized_weights,
        strict=True,
    ):
        start_index = bisect_left(dates, requested.requested_start_date)
        if (
            start_index >= len(dates)
            or dates[start_index] > requested.requested_end_date
        ):
            return _fatal(
                "BENCHMARK_RANGE_START_NOT_FOUND",
                range_key=requested.key,
            )
        end_index = bisect_right(dates, requested.requested_end_date) - 1
        if (
            end_index < 0
            or dates[end_index] < requested.requested_start_date
        ):
            return _fatal(
                "BENCHMARK_RANGE_END_NOT_FOUND",
                range_key=requested.key,
            )
        if not boundary_within_buffer(
            requested.requested_start_date,
            dates[start_index],
            side="start",
        ):
            return _fatal(
                "BENCHMARK_RANGE_START_BUFFER_EXCEEDED",
                range_key=requested.key,
            )
        if not boundary_within_buffer(
            requested.requested_end_date,
            dates[end_index],
            side="end",
        ):
            return _fatal(
                "BENCHMARK_RANGE_END_BUFFER_EXCEEDED",
                range_key=requested.key,
            )
        if start_index >= end_index:
            return _fatal(
                "BENCHMARK_RANGE_INVALID_BOUNDARIES",
                range_key=requested.key,
            )
        resolved.append(
            ResolvedRange(
                run_range_id=requested.run_range_id,
                key=requested.key,
                label=requested.label,
                kind=requested.kind,
                ordinal=requested.ordinal,
                requested_start_date=requested.requested_start_date,
                requested_end_date=requested.requested_end_date,
                actual_start_date=dates[start_index],
                actual_end_date=dates[end_index],
                benchmark_start_close=closes[start_index],
                benchmark_end_close=closes[end_index],
                base_weight=weight,
                normalized_weight=normalized_weight,
            )
        )
    return ResolvedBenchmarkRanges(
        algorithm_version=input.algorithm_version,
        benchmark_symbol=input.benchmark_symbol,
        ranges=tuple(resolved),
    )
