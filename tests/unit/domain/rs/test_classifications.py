from __future__ import annotations

from datetime import date
from decimal import Decimal

from stock_toolbox.analyses.rs_strength.domain.classifications import (
    aggregate_classification_chunk,
    calculate_composite_and_status,
    finalize_run_calculation,
)
from stock_toolbox.analyses.rs_strength.domain.models import (
    CalculationMember,
    ClassificationBaseChunkOutput,
    ClassificationPeriodResult,
    PreparedCalculation,
    ResolvedRange,
    RunCalculationOutput,
    StockCalculationOutput,
    StockRSResult,
)
from stock_toolbox.analyses.rs_strength.domain.numeric import canonical_decimal


def prepared(members: tuple[CalculationMember, ...]) -> PreparedCalculation:
    return PreparedCalculation(
        algorithm_version="rs-algorithm-v1",
        benchmark_symbol="SPY.US",
        ranges=(
            ResolvedRange(
                "r1",
                "R1",
                "R1",
                "CUSTOM",
                0,
                date(2026, 1, 2),
                date(2026, 4, 2),
                date(2026, 1, 2),
                date(2026, 4, 2),
                Decimal(100),
                Decimal(110),
                Decimal("1.00"),
                Decimal(1),
            ),
        ),
        members=members,
        normalized_series_by_symbol={},
        initial_failure_drafts=(),
    )


def member(ordinal: int, classification: str = "D") -> CalculationMember:
    return CalculationMember(
        f"m{ordinal}",
        ordinal,
        f"S{ordinal}.US",
        classification,
        classification,
        classification.lower(),
    )


def result(item: CalculationMember, rs: str) -> StockRSResult:
    return StockRSResult(
        run_member_id=item.run_member_id,
        member_ordinal=item.ordinal,
        symbol=item.symbol,
        run_range_id="r1",
        range_key="R1",
        range_label="R1",
        range_kind="CUSTOM",
        range_ordinal=0,
        stock_start_close=Decimal(100),
        stock_end_close=Decimal(100),
        benchmark_start_close=Decimal(100),
        benchmark_end_close=Decimal(100),
        stock_return=Decimal(0),
        benchmark_return=Decimal(0),
        rs=Decimal(rs),
    )


def stock(results: tuple[StockRSResult, ...]) -> StockCalculationOutput:
    return StockCalculationOutput(
        stock_results=results,
        failure_candidates=(),
        valid_member_count=len({item.member_ordinal for item in results}),
        failed_member_count=0,
        failed_member_range_count=0,
    )


def test_v6_partial_coverage_at_exactly_60_percent_is_eligible() -> None:
    members = tuple(member(index) for index in range(5))
    output = aggregate_classification_chunk(
        prepared(members),
        stock(
            (
                result(members[0], "9"),
                result(members[1], "3"),
                result(members[2], "-3"),
            )
        ),
        ("D",),
    )

    assert isinstance(output, ClassificationBaseChunkOutput)
    base = output.period_bases[0]
    assert base.total_member_count == 5
    assert base.valid_member_count == 3
    assert canonical_decimal(base.coverage) == "0.6"
    assert canonical_decimal(base.mean_rs) == "3"  # type: ignore[arg-type]
    assert canonical_decimal(base.median_rs) == "3"  # type: ignore[arg-type]
    assert base.positive_count == 2
    assert canonical_decimal(base.strong_breadth) == (
        "0.6666666666666666666666666666666667"
    )
    assert tuple(item.rs for item in base.top_members) == (
        Decimal(9),
        Decimal(3),
        Decimal(-3),
    )
    assert tuple(item.rs for item in base.bottom_members) == (
        Decimal(-3),
        Decimal(3),
        Decimal(9),
    )
    assert base.eligibility == "ELIGIBLE"
    assert base.eligibility_reason is None


def test_sample_count_precedes_coverage_as_primary_ineligibility_reason() -> None:
    members = tuple(member(index) for index in range(5))
    output = aggregate_classification_chunk(
        prepared(members),
        stock((result(members[0], "1"), result(members[1], "-1"))),
        ("D",),
    )
    assert isinstance(output, ClassificationBaseChunkOutput)

    base = output.period_bases[0]
    assert base.valid_member_count == 2
    assert base.coverage == Decimal("0.4")
    assert base.eligibility == "INSUFFICIENT_SAMPLE"
    assert base.eligibility_reason == "VALID_MEMBER_COUNT_LT_3"


def test_coverage_below_60_percent_is_ineligible_after_sample_gate() -> None:
    members = tuple(member(index) for index in range(6))
    output = aggregate_classification_chunk(
        prepared(members),
        stock(tuple(result(members[index], str(index)) for index in range(3))),
        ("D",),
    )
    assert isinstance(output, ClassificationBaseChunkOutput)

    base = output.period_bases[0]
    assert base.coverage == Decimal("0.5")
    assert base.eligibility == "INSUFFICIENT_COVERAGE"
    assert base.eligibility_reason == "COVERAGE_LT_0_60"


def test_empty_classification_range_preserves_zero_base_statistics() -> None:
    members = tuple(member(index) for index in range(3))
    output = aggregate_classification_chunk(prepared(members), stock(()), ("D",))
    assert isinstance(output, ClassificationBaseChunkOutput)

    base = output.period_bases[0]
    assert base.coverage == Decimal(0)
    assert base.mean_rs is None
    assert base.median_rs is None
    assert base.strong_breadth is None
    assert base.positive_count == 0
    assert base.top_members == ()
    assert base.bottom_members == ()


def test_even_median_and_top_bottom_ties_use_member_ordinal() -> None:
    members = tuple(member(index) for index in range(6))
    values = ("5", "5", "4", "3", "2", "1")
    output = aggregate_classification_chunk(
        prepared(members),
        stock(tuple(result(item, value) for item, value in zip(members, values))),
        ("D",),
    )
    assert isinstance(output, ClassificationBaseChunkOutput)

    base = output.period_bases[0]
    assert base.median_rs == Decimal("3.5")
    assert tuple(item.member_ordinal for item in base.top_members) == (0, 1, 2, 3, 4)
    assert tuple(item.member_ordinal for item in base.bottom_members) == (5, 4, 3, 2, 0)


def test_v3_partial_ties_use_average_rank_without_name_tiebreak() -> None:
    members = tuple(
        member(index, classification)
        for index, classification in enumerate(("A",) * 3 + ("B",) * 3 + ("C",) * 3)
    )
    values = ("10", "10", "10", "10", "10", "10", "-5", "0", "5")
    prepared_input = prepared(members)
    stock_input = stock(
        tuple(result(item, value) for item, value in zip(members, values))
    )
    bases = aggregate_classification_chunk(
        prepared_input,
        stock_input,
        ("A", "B", "C"),
    )
    assert isinstance(bases, ClassificationBaseChunkOutput)

    output = finalize_run_calculation(prepared_input, stock_input, (bases,))

    assert isinstance(output, RunCalculationOutput)
    scores = {
        item.classification_snapshot_key: item.period_score
        for item in output.classification_period_results
    }
    assert scores == {"A": Decimal(75), "B": Decimal(75), "C": Decimal(0)}


def test_eligible_classifications_fewer_than_three_have_no_fake_score() -> None:
    members = tuple(
        member(index, classification)
        for index, classification in enumerate(("A",) * 3 + ("B",) * 3)
    )
    prepared_input = prepared(members)
    stock_input = stock(tuple(result(item, "1") for item in members))
    bases = aggregate_classification_chunk(prepared_input, stock_input, ("A", "B"))
    assert isinstance(bases, ClassificationBaseChunkOutput)

    output = finalize_run_calculation(prepared_input, stock_input, (bases,))

    assert isinstance(output, RunCalculationOutput)
    for period in output.classification_period_results:
        assert period.period_score is None
        assert period.score_unavailable_reason == "COMPARABLE_CLASSIFICATIONS_LT_3"
    for overall in output.classification_results:
        assert overall.composite_score is None


def test_all_equal_metrics_receive_neutral_50_percentiles() -> None:
    members = tuple(
        member(index, classification)
        for index, classification in enumerate(("A",) * 3 + ("B",) * 3 + ("C",) * 3)
    )
    prepared_input = prepared(members)
    stock_input = stock(tuple(result(item, "1") for item in members))
    bases = aggregate_classification_chunk(
        prepared_input,
        stock_input,
        ("A", "B", "C"),
    )
    assert isinstance(bases, ClassificationBaseChunkOutput)

    output = finalize_run_calculation(prepared_input, stock_input, (bases,))

    assert isinstance(output, RunCalculationOutput)
    assert {
        (
            item.median_percentile,
            item.breadth_percentile,
            item.period_score,
        )
        for item in output.classification_period_results
    } == {(Decimal(50), Decimal(50), Decimal(50))}


def period(
    resolved: ResolvedRange,
    *,
    score: Decimal | None,
    median: Decimal | None,
) -> ClassificationPeriodResult:
    return ClassificationPeriodResult(
        classification_snapshot_key="C",
        classification_name="Cloud",
        classification_normalized_name="cloud",
        run_range_id=resolved.run_range_id,
        range_key=resolved.key,
        range_label=resolved.label,
        range_kind=resolved.kind,
        range_ordinal=resolved.ordinal,
        total_member_count=3,
        valid_member_count=3,
        coverage=Decimal(1),
        mean_rs=median,
        median_rs=median,
        positive_count=3,
        strong_breadth=Decimal(1),
        top_members=(),
        bottom_members=(),
        eligibility="ELIGIBLE",
        eligibility_reason=None,
        median_percentile=score,
        breadth_percentile=score,
        period_score=score,
        score_unavailable_reason=None if score is not None else "UNAVAILABLE",
    )


def weighted_ranges() -> tuple[ResolvedRange, ...]:
    specs = (
        ("3M", 0, date(2026, 4, 23), Decimal("1.00"), "0.2898550724637681159420289855072464"),
        ("6M", 1, date(2026, 1, 23), Decimal("1.15"), "0.3333333333333333333333333333333333"),
        ("1Y", 2, date(2025, 7, 23), Decimal("1.30"), "0.3768115942028985507246376811594203"),
    )
    return tuple(
        ResolvedRange(
            f"r{ordinal}",
            key,
            key,
            f"PRESET_{key}",
            ordinal,
            start,
            date(2026, 7, 23),
            start,
            date(2026, 7, 23),
            Decimal(100),
            Decimal(110),
            base,
            Decimal(weight),
        )
        for key, ordinal, start, base, weight in specs
    )


def test_v7_uses_frozen_residual_weights_and_sequential_decimal_sum() -> None:
    ranges = weighted_ranges()
    composite, status, reason = calculate_composite_and_status(
        tuple(
            period(resolved, score=score, median=median)
            for resolved, score, median in zip(
                ranges,
                (Decimal(60), Decimal(70), Decimal(80)),
                (Decimal(2), Decimal(3), Decimal(4)),
            )
        ),
        ranges,
    )

    assert canonical_decimal(composite) == (  # type: ignore[arg-type]
        "70.86956521739130434782608695652173"
    )
    assert status == "SUSTAINED_STRONG"
    assert reason is None


def test_missing_one_period_score_does_not_renormalize_remaining_periods() -> None:
    ranges = weighted_ranges()
    periods = (
        period(ranges[0], score=Decimal(60), median=Decimal(2)),
        period(ranges[1], score=None, median=Decimal(3)),
        period(ranges[2], score=Decimal(80), median=Decimal(4)),
    )

    composite, status, reason = calculate_composite_and_status(periods, ranges)

    assert composite is None
    assert status == "SUSTAINED_STRONG"
    assert reason == "RANGE_SCORE_UNAVAILABLE:6M:UNAVAILABLE"


def test_status_distinguishes_recent_change_tied_span_and_missing_data() -> None:
    ranges = weighted_ranges()
    _, strengthening, _ = calculate_composite_and_status(
        (
            period(ranges[0], score=Decimal(50), median=Decimal(1)),
            period(ranges[1], score=Decimal(50), median=Decimal(0)),
            period(ranges[2], score=Decimal(50), median=Decimal(-1)),
        ),
        ranges,
    )
    assert strengthening == "RECENTLY_STRENGTHENING"

    tied_ranges = (
        ranges[0],
        ResolvedRange(
            "rx",
            "CUSTOM",
            "CUSTOM",
            "CUSTOM",
            1,
            date(2026, 4, 23),
            date(2026, 7, 23),
            date(2026, 4, 23),
            date(2026, 7, 23),
            Decimal(100),
            Decimal(110),
            Decimal("1.00"),
            Decimal("0.5"),
        ),
    )
    _, tied, _ = calculate_composite_and_status(
        (
            period(tied_ranges[0], score=Decimal(50), median=Decimal(1)),
            period(tied_ranges[1], score=Decimal(50), median=Decimal(-1)),
        ),
        tied_ranges,
    )
    assert tied == "DIVERGENT_TIED_SPAN"

    _, insufficient, _ = calculate_composite_and_status(
        (
            period(ranges[0], score=Decimal(50), median=Decimal(1)),
            period(ranges[1], score=Decimal(50), median=None),
            period(ranges[2], score=Decimal(50), median=Decimal(-1)),
        ),
        ranges,
    )
    assert insufficient == "INSUFFICIENT_DATA"
