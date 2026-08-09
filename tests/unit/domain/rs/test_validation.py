from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from stock_toolbox.analyses.rs_strength.domain.models import (
    ALGORITHM_VERSION,
    CalculationFatalIssue,
    CalculationMember,
    PricePoint,
    PriceSeries,
    RequestedRange,
    ResolvedBenchmarkRanges,
    RunCalculationInput,
)
from stock_toolbox.analyses.rs_strength.domain.numeric import canonical_decimal
from stock_toolbox.analyses.rs_strength.domain.validation import resolve_benchmark_and_ranges


def series(symbol: str, *points: tuple[str, object]) -> PriceSeries:
    return PriceSeries(
        symbol,
        tuple(
            PricePoint(date.fromisoformat(day), close)  # type: ignore[arg-type]
            for day, close in points
        ),
    )


def requested_range(
    *,
    identity: str = "range-1",
    key: str = "R1",
    ordinal: int = 0,
    start: str = "2026-01-01",
    end: str = "2026-01-06",
) -> RequestedRange:
    return RequestedRange(
        run_range_id=identity,
        key=key,
        label=key,
        kind="CUSTOM",
        ordinal=ordinal,
        requested_start_date=date.fromisoformat(start),
        requested_end_date=date.fromisoformat(end),
    )


def member(
    *,
    identity: str = "member-1",
    symbol: str = "ABC.US",
    ordinal: int = 0,
) -> CalculationMember:
    return CalculationMember(
        run_member_id=identity,
        ordinal=ordinal,
        symbol=symbol,
        classification_snapshot_key="C1",
        classification_name="Cloud",
        classification_normalized_name="cloud",
    )


def calculation_input(
    *,
    benchmark: PriceSeries | None = None,
    ranges: tuple[RequestedRange, ...] | None = None,
    members: tuple[CalculationMember, ...] | None = None,
    version: str = ALGORITHM_VERSION,
) -> RunCalculationInput:
    benchmark = benchmark or series(
        "SPY.US",
        ("2026-01-06", Decimal(104)),
        ("2026-01-02", Decimal(100)),
        ("2026-01-05", Decimal(102)),
    )
    members = members or (member(),)
    return RunCalculationInput(
        algorithm_version=version,
        benchmark_symbol="SPY.US",
        requested_ranges=ranges or (requested_range(),),
        members=members,
        series_by_symbol={
            "SPY.US": benchmark,
            "ABC.US": series(
                "ABC.US",
                ("2026-01-02", Decimal(50)),
                ("2026-01-06", Decimal(55)),
            ),
        },
        member_data_issues=(),
    )


def assert_fatal(result: object, code: str) -> CalculationFatalIssue:
    assert isinstance(result, CalculationFatalIssue)
    assert result.stage == "VALIDATE"
    assert result.code == code
    return result


def test_v4_resolves_inclusive_common_boundaries_from_unsorted_benchmark() -> None:
    result = resolve_benchmark_and_ranges(calculation_input())

    assert isinstance(result, ResolvedBenchmarkRanges)
    resolved = result.ranges[0]
    assert resolved.run_range_id == "range-1"
    assert resolved.requested_start_date == date(2026, 1, 1)
    assert resolved.actual_start_date == date(2026, 1, 2)
    assert resolved.actual_end_date == date(2026, 1, 6)
    assert resolved.benchmark_start_close == Decimal(100)
    assert resolved.benchmark_end_close == Decimal(104)
    assert canonical_decimal(resolved.normalized_weight) == "1"


def test_range_resolution_never_uses_points_outside_requested_interval() -> None:
    result = resolve_benchmark_and_ranges(
        calculation_input(
            benchmark=series(
                "SPY.US",
                ("2025-12-31", Decimal(99)),
                ("2026-01-07", Decimal(105)),
            )
        )
    )

    assert_fatal(result, "BENCHMARK_RANGE_START_NOT_FOUND")


def test_range_resolution_rejects_boundaries_beyond_four_workday_buffer() -> None:
    start = resolve_benchmark_and_ranges(
        calculation_input(
            ranges=(requested_range(start="2026-01-01", end="2026-01-20"),),
            benchmark=series(
                "SPY.US",
                ("2026-01-09", Decimal(100)),
                ("2026-01-20", Decimal(104)),
            ),
        )
    )
    end = resolve_benchmark_and_ranges(
        calculation_input(
            ranges=(requested_range(start="2026-01-01", end="2026-01-20"),),
            benchmark=series(
                "SPY.US",
                ("2026-01-01", Decimal(100)),
                ("2026-01-12", Decimal(104)),
            ),
        )
    )

    assert_fatal(start, "BENCHMARK_RANGE_START_BUFFER_EXCEEDED")
    assert_fatal(end, "BENCHMARK_RANGE_END_BUFFER_EXCEEDED")


@pytest.mark.parametrize(
    ("points", "code"),
    [
        (
            (
                ("2026-01-02", Decimal(100)),
                ("2026-01-02", Decimal(100)),
                ("2026-01-06", Decimal(104)),
            ),
            "BENCHMARK_SERIES_INVALID",
        ),
        (
            (("2026-01-02", Decimal(100)),),
            "BENCHMARK_RANGE_INVALID_BOUNDARIES",
        ),
        (
            (
                ("2026-01-02", Decimal("NaN")),
                ("2026-01-06", Decimal(104)),
            ),
            "BENCHMARK_SERIES_INVALID",
        ),
        (
            (
                ("2026-01-02", Decimal(0)),
                ("2026-01-06", Decimal(104)),
            ),
            "BENCHMARK_SERIES_INVALID",
        ),
        (
            (
                ("2026-01-02", 100.0),
                ("2026-01-06", Decimal(104)),
            ),
            "BENCHMARK_SERIES_INVALID",
        ),
    ],
)
def test_invalid_benchmark_is_fatal(
    points: tuple[tuple[str, object], ...],
    code: str,
) -> None:
    result = resolve_benchmark_and_ranges(
        calculation_input(benchmark=series("SPY.US", *points))
    )
    assert_fatal(result, code)


def test_missing_benchmark_and_symbol_mismatch_are_fatal() -> None:
    missing = calculation_input()
    missing = replace(
        missing,
        series_by_symbol={"ABC.US": missing.series_by_symbol["ABC.US"]},
    )
    assert_fatal(resolve_benchmark_and_ranges(missing), "BENCHMARK_SERIES_MISSING")

    mismatch = calculation_input(benchmark=series("QQQ.US", ("2026-01-02", Decimal(1))))
    assert_fatal(resolve_benchmark_and_ranges(mismatch), "BENCHMARK_SYMBOL_MISMATCH")


def test_duplicate_range_dimensions_and_member_dimensions_are_fatal() -> None:
    base_range = requested_range()
    for duplicate, code in (
        (replace(base_range, key="R2", ordinal=1), "RANGE_ID_DUPLICATE"),
        (
            replace(base_range, run_range_id="range-2", ordinal=1),
            "RANGE_KEY_DUPLICATE",
        ),
        (
            replace(base_range, run_range_id="range-2", key="R2"),
            "RANGE_ORDINAL_DUPLICATE",
        ),
    ):
        assert_fatal(
            resolve_benchmark_and_ranges(
                calculation_input(ranges=(base_range, duplicate))
            ),
            code,
        )

    base_member = member()
    for duplicate, code in (
        (replace(base_member, symbol="DEF.US", ordinal=1), "MEMBER_ID_DUPLICATE"),
        (
            replace(base_member, run_member_id="member-2", ordinal=1),
            "MEMBER_SYMBOL_DUPLICATE",
        ),
        (
            replace(base_member, run_member_id="member-2", symbol="DEF.US"),
            "MEMBER_ORDINAL_DUPLICATE",
        ),
    ):
        assert_fatal(
            resolve_benchmark_and_ranges(
                calculation_input(members=(base_member, duplicate))
            ),
            code,
        )


def test_unknown_algorithm_version_is_fatal() -> None:
    assert_fatal(
        resolve_benchmark_and_ranges(calculation_input(version="future")),
        "ALGORITHM_VERSION_UNSUPPORTED",
    )
