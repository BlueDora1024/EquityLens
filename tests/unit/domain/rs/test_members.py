from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from stock_toolbox.analyses.rs_strength.domain.members import (
    calculate_member_chunk,
    complete_stock_calculation,
    complete_validation,
    normalize_member_chunk,
)
from stock_toolbox.analyses.rs_strength.domain.models import (
    ALGORITHM_VERSION,
    CalculationFatalIssue,
    CalculationMember,
    MemberDataIssue,
    PricePoint,
    PriceSeries,
    RequestedRange,
    ResolvedBenchmarkRanges,
    RunCalculationInput,
    StockCalculationOutput,
)
from stock_toolbox.analyses.rs_strength.domain.numeric import canonical_decimal
from stock_toolbox.analyses.rs_strength.domain.validation import resolve_benchmark_and_ranges


def price_series(symbol: str, values: tuple[tuple[str, str], ...]) -> PriceSeries:
    return PriceSeries(
        symbol,
        tuple(
            PricePoint(date.fromisoformat(day), Decimal(close))
            for day, close in values
        ),
    )


def calculation(
    *,
    benchmark_symbol: str = "SPY.US",
    benchmark: tuple[tuple[str, str], ...] = (
        ("2026-01-02", "100"),
        ("2026-04-02", "110"),
    ),
    stocks: dict[str, tuple[tuple[str, str], ...]] | None = None,
    members: tuple[CalculationMember, ...] | None = None,
    issues: tuple[MemberDataIssue, ...] = (),
) -> RunCalculationInput:
    members = members or (
        CalculationMember("member-1", 0, "AAPL.US", "C1", "Cloud", "cloud"),
    )
    stock_values = stocks or {
        "AAPL.US": (("2026-01-02", "100"), ("2026-04-02", "125"))
    }
    series = {benchmark_symbol: price_series(benchmark_symbol, benchmark)}
    series.update(
        {
            symbol: price_series(symbol, values)
            for symbol, values in stock_values.items()
        }
    )
    return RunCalculationInput(
        algorithm_version=ALGORITHM_VERSION,
        benchmark_symbol=benchmark_symbol,
        requested_ranges=(
            RequestedRange(
                "range-1",
                "R1",
                "R1",
                "CUSTOM",
                0,
                date(2026, 1, 2),
                date(2026, 4, 2),
            ),
        ),
        members=members,
        series_by_symbol=series,
        member_data_issues=issues,
    )


def resolved(input: RunCalculationInput) -> ResolvedBenchmarkRanges:
    output = resolve_benchmark_and_ranges(input)
    assert isinstance(output, ResolvedBenchmarkRanges)
    return output


def prepare_and_calculate(input: RunCalculationInput) -> StockCalculationOutput:
    benchmark = resolved(input)
    normalization = normalize_member_chunk(
        input,
        benchmark,
        tuple(member.ordinal for member in input.members),
    )
    assert not isinstance(normalization, CalculationFatalIssue)
    prepared = complete_validation(input, benchmark, (normalization,))
    assert not isinstance(prepared, CalculationFatalIssue)
    calculation_chunk = calculate_member_chunk(
        prepared,
        tuple(member.ordinal for member in input.members),
    )
    assert not isinstance(calculation_chunk, CalculationFatalIssue)
    output = complete_stock_calculation(prepared, (calculation_chunk,))
    assert isinstance(output, StockCalculationOutput)
    return output


def test_v1_stock_outperforms_spy_by_15_percentage_points() -> None:
    output = prepare_and_calculate(calculation())

    assert len(output.stock_results) == 1
    result = output.stock_results[0]
    assert canonical_decimal(result.stock_return) == "0.25"
    assert canonical_decimal(result.benchmark_return) == "0.1"
    assert canonical_decimal(result.rs) == "15"
    assert result.unit == "percentage_points"
    assert (output.valid_member_count, output.failed_member_count) == (1, 0)


def test_v2_stock_underperforms_qqq_by_6_percentage_points() -> None:
    output = prepare_and_calculate(
        calculation(
            benchmark_symbol="QQQ.US",
            benchmark=(("2026-01-02", "200"), ("2026-04-02", "220")),
            stocks={
                "AAPL.US": (("2026-01-02", "50"), ("2026-04-02", "52"))
            },
        )
    )

    assert canonical_decimal(output.stock_results[0].rs) == "-6"


def test_v5_missing_exact_end_boundary_creates_nonfatal_member_range_failure() -> None:
    output = prepare_and_calculate(
        calculation(stocks={"AAPL.US": (("2026-01-02", "50"),)})
    )

    assert output.stock_results == ()
    assert len(output.failure_candidates) == 1
    failure = output.failure_candidates[0]
    assert failure.scope == "MEMBER_RANGE"
    assert failure.range_key == "R1"
    assert failure.code == "MISSING_COMMON_END_CLOSE"
    assert failure.stable_ordinal == 0
    assert (output.valid_member_count, output.failed_member_count) == (0, 1)
    assert output.failed_member_range_count == 1


def test_missing_exact_start_boundary_is_a_separate_nonfatal_code() -> None:
    output = prepare_and_calculate(
        calculation(stocks={"AAPL.US": (("2026-04-02", "50"),)})
    )

    assert output.failure_candidates[0].code == "MISSING_COMMON_START_CLOSE"


def test_invalid_member_series_becomes_one_member_validation_failure() -> None:
    input = calculation()
    input = replace(
        input,
        series_by_symbol={
            "SPY.US": input.series_by_symbol["SPY.US"],
            "AAPL.US": PriceSeries(
                "AAPL.US",
                (
                    PricePoint(date(2026, 1, 2), Decimal("NaN")),
                    PricePoint(date(2026, 4, 2), Decimal(125)),
                ),
            ),
        },
    )
    output = prepare_and_calculate(input)

    assert output.failure_candidates[0].scope == "MEMBER"
    assert output.failure_candidates[0].stage == "VALIDATE"
    assert output.failure_candidates[0].code == "MEMBER_SERIES_INVALID"


def test_member_fetch_issue_becomes_one_member_failure_not_range_failures() -> None:
    input = calculation(
        stocks={},
        issues=(
            MemberDataIssue(
                0,
                "AAPL.US",
                "FETCH",
                "PROVIDER_TIMEOUT",
                (("provider", "virtual"),),
            ),
        ),
    )
    input = replace(
        input,
        series_by_symbol={
            "SPY.US": input.series_by_symbol["SPY.US"],
        },
    )
    output = prepare_and_calculate(input)

    assert output.stock_results == ()
    assert output.failure_candidates[0].scope == "MEMBER"
    assert output.failure_candidates[0].code == "PROVIDER_TIMEOUT"
    assert output.failed_member_range_count == 0


def test_validation_chunks_may_finish_out_of_order_but_must_cover_once() -> None:
    members = (
        CalculationMember("m0", 0, "A.US", "C1", "Cloud", "cloud"),
        CalculationMember("m1", 1, "B.US", "C1", "Cloud", "cloud"),
    )
    input = calculation(
        members=members,
        stocks={
            "A.US": (("2026-01-02", "10"), ("2026-04-02", "11")),
            "B.US": (("2026-01-02", "20"), ("2026-04-02", "22")),
        },
    )
    benchmark = resolved(input)
    second = normalize_member_chunk(input, benchmark, (1,))
    first = normalize_member_chunk(input, benchmark, (0,))
    assert not isinstance(first, CalculationFatalIssue)
    assert not isinstance(second, CalculationFatalIssue)

    prepared = complete_validation(input, benchmark, (second, first))
    assert not isinstance(prepared, CalculationFatalIssue)
    assert tuple(prepared.normalized_series_by_symbol) == ("A.US", "B.US")

    overlap = complete_validation(input, benchmark, (first, first, second))
    assert isinstance(overlap, CalculationFatalIssue)
    assert overlap.code == "MEMBER_CHUNK_COVERAGE_INVALID"

    missing = complete_validation(input, benchmark, (first,))
    assert isinstance(missing, CalculationFatalIssue)
    assert missing.code == "MEMBER_CHUNK_COVERAGE_INVALID"


def test_classification_snapshot_conflicts_fail_before_calculation() -> None:
    members = (
        CalculationMember("m0", 0, "A.US", "C1", "Cloud", "cloud"),
        CalculationMember("m1", 1, "B.US", "C1", "Different", "different"),
    )
    input = calculation(
        members=members,
        stocks={
            "A.US": (("2026-01-02", "10"), ("2026-04-02", "11")),
            "B.US": (("2026-01-02", "20"), ("2026-04-02", "22")),
        },
    )
    benchmark = resolved(input)
    chunk = normalize_member_chunk(input, benchmark, (0, 1))
    assert not isinstance(chunk, CalculationFatalIssue)

    output = complete_validation(input, benchmark, (chunk,))
    assert isinstance(output, CalculationFatalIssue)
    assert output.code == "CLASSIFICATION_SNAPSHOT_CONFLICT"


def test_failure_candidate_order_is_independent_of_chunk_completion_order() -> None:
    members = (
        CalculationMember("m0", 0, "A.US", "C1", "Cloud", "cloud"),
        CalculationMember("m1", 1, "B.US", "C1", "Cloud", "cloud"),
    )
    input = calculation(
        members=members,
        stocks={
            "A.US": (("2026-01-02", "10"),),
            "B.US": (("2026-01-02", "20"),),
        },
    )
    benchmark = resolved(input)
    normalized = normalize_member_chunk(input, benchmark, (0, 1))
    assert not isinstance(normalized, CalculationFatalIssue)
    prepared = complete_validation(input, benchmark, (normalized,))
    assert not isinstance(prepared, CalculationFatalIssue)
    zero = calculate_member_chunk(prepared, (0,))
    one = calculate_member_chunk(prepared, (1,))
    assert not isinstance(zero, CalculationFatalIssue)
    assert not isinstance(one, CalculationFatalIssue)

    forward = complete_stock_calculation(prepared, (zero, one))
    reverse = complete_stock_calculation(prepared, (one, zero))

    assert isinstance(forward, StockCalculationOutput)
    assert isinstance(reverse, StockCalculationOutput)
    assert forward.failure_candidates == reverse.failure_candidates
    assert tuple(item.stable_ordinal for item in forward.failure_candidates) == (0, 1)
