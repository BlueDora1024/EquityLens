"""Classification aggregation and cross-period scoring."""

from __future__ import annotations

from decimal import Decimal

from stock_toolbox.analyses.rs_strength.domain.models import (
    CalculationFatalIssue,
    CalculationMember,
    ClassificationBaseChunkOutput,
    ClassificationPeriodBase,
    ClassificationPeriodResult,
    ClassificationStrengthResult,
    PreparedCalculation,
    RankedMemberRS,
    ResolvedRange,
    RunCalculationOutput,
    StockCalculationOutput,
    StockRSResult,
)
from stock_toolbox.analyses.rs_strength.domain.numeric import local_rs_context


def _fatal(code: str) -> CalculationFatalIssue:
    return CalculationFatalIssue(
        stage="AGGREGATE",
        code=code,
        range_key=None,
        reason_parameters=(),
    )


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def aggregate_classification_chunk(
    prepared: PreparedCalculation,
    stock: StockCalculationOutput,
    classification_keys: tuple[str, ...],
) -> ClassificationBaseChunkOutput | CalculationFatalIssue:
    """Produce base statistics for selected classifications over every range."""

    identities: dict[str, tuple[str, str]] = {}
    members_by_classification: dict[str, list[CalculationMember]] = {}
    member_by_ordinal: dict[int, CalculationMember] = {}
    for member in prepared.members:
        member_by_ordinal[member.ordinal] = member
        identities.setdefault(
            member.classification_snapshot_key,
            (
                member.classification_name,
                member.classification_normalized_name,
            ),
        )
        members_by_classification.setdefault(
            member.classification_snapshot_key,
            [],
        ).append(member)
    if (
        len(classification_keys) != len(set(classification_keys))
        or not set(classification_keys) <= set(identities)
    ):
        return _fatal("CLASSIFICATION_CHUNK_KEY_INVALID")

    range_by_ordinal = {item.ordinal: item for item in prepared.ranges}
    results_by_classification_and_range: dict[
        tuple[str, int],
        list[StockRSResult],
    ] = {}
    result_keys: set[tuple[int, int]] = set()
    for result in stock.stock_results:
        resolved_member = member_by_ordinal.get(result.member_ordinal)
        resolved = range_by_ordinal.get(result.range_ordinal)
        if (
            resolved_member is None
            or resolved is None
            or result.run_member_id != resolved_member.run_member_id
            or result.symbol != resolved_member.symbol
            or result.run_range_id != resolved.run_range_id
        ):
            return _fatal("STOCK_RESULT_REFERENCE_INVALID")
        result_key = (result.member_ordinal, result.range_ordinal)
        if result_key in result_keys:
            return _fatal("STOCK_RESULT_DUPLICATE")
        result_keys.add(result_key)
        results_by_classification_and_range.setdefault(
            (
                resolved_member.classification_snapshot_key,
                result.range_ordinal,
            ),
            [],
        ).append(result)

    ordered_keys = tuple(
        sorted(
            classification_keys,
            key=lambda key: (identities[key][1], key),
        )
    )
    bases = []
    with local_rs_context():
        for resolved in prepared.ranges:
            for classification_key in ordered_keys:
                name, normalized_name = identities[classification_key]
                classification_members = members_by_classification[
                    classification_key
                ]
                results = results_by_classification_and_range.get(
                    (classification_key, resolved.ordinal),
                    [],
                )
                values = [result.rs for result in results]
                total_count = len(classification_members)
                valid_count = len(values)
                coverage = Decimal(valid_count) / Decimal(total_count)
                if values:
                    mean = sum(values, Decimal(0)) / Decimal(valid_count)
                    median = _median(values)
                    positive_count = sum(value > 0 for value in values)
                    breadth = Decimal(positive_count) / Decimal(valid_count)
                else:
                    mean = None
                    median = None
                    positive_count = 0
                    breadth = None
                ranked = [
                    RankedMemberRS(
                        result.run_member_id,
                        result.member_ordinal,
                        result.symbol,
                        result.rs,
                    )
                    for result in results
                ]
                top = tuple(
                    sorted(
                        ranked,
                        key=lambda item: (
                            -item.rs,
                            item.member_ordinal,
                            item.symbol,
                            item.run_member_id,
                        ),
                    )[:5]
                )
                bottom = tuple(
                    sorted(
                        ranked,
                        key=lambda item: (
                            item.rs,
                            item.member_ordinal,
                            item.symbol,
                            item.run_member_id,
                        ),
                    )[:5]
                )
                if valid_count < 3:
                    eligibility = "INSUFFICIENT_SAMPLE"
                    eligibility_reason = "VALID_MEMBER_COUNT_LT_3"
                elif coverage < Decimal("0.60"):
                    eligibility = "INSUFFICIENT_COVERAGE"
                    eligibility_reason = "COVERAGE_LT_0_60"
                else:
                    eligibility = "ELIGIBLE"
                    eligibility_reason = None
                bases.append(
                    ClassificationPeriodBase(
                        classification_snapshot_key=classification_key,
                        classification_name=name,
                        classification_normalized_name=normalized_name,
                        run_range_id=resolved.run_range_id,
                        range_key=resolved.key,
                        range_label=resolved.label,
                        range_kind=resolved.kind,
                        range_ordinal=resolved.ordinal,
                        total_member_count=total_count,
                        valid_member_count=valid_count,
                        coverage=coverage,
                        mean_rs=mean,
                        median_rs=median,
                        positive_count=positive_count,
                        strong_breadth=breadth,
                        top_members=top,
                        bottom_members=bottom,
                        eligibility=eligibility,
                        eligibility_reason=eligibility_reason,
                    )
                )
    return ClassificationBaseChunkOutput(
        classification_keys=ordered_keys,
        period_bases=tuple(bases),
    )


def _percentile(value: Decimal, values: tuple[Decimal, ...]) -> Decimal:
    if all(candidate == values[0] for candidate in values):
        return Decimal(50)
    lower = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    average_rank = Decimal(lower) + (Decimal(equal) + Decimal(1)) / Decimal(2)
    return (
        (average_rank - Decimal(1))
        / Decimal(len(values) - 1)
        * Decimal(100)
    )


def _period_result(
    base: ClassificationPeriodBase,
    *,
    median_percentile: Decimal | None,
    breadth_percentile: Decimal | None,
    period_score: Decimal | None,
    score_unavailable_reason: str | None,
) -> ClassificationPeriodResult:
    return ClassificationPeriodResult(
        classification_snapshot_key=base.classification_snapshot_key,
        classification_name=base.classification_name,
        classification_normalized_name=base.classification_normalized_name,
        run_range_id=base.run_range_id,
        range_key=base.range_key,
        range_label=base.range_label,
        range_kind=base.range_kind,
        range_ordinal=base.range_ordinal,
        total_member_count=base.total_member_count,
        valid_member_count=base.valid_member_count,
        coverage=base.coverage,
        mean_rs=base.mean_rs,
        median_rs=base.median_rs,
        positive_count=base.positive_count,
        strong_breadth=base.strong_breadth,
        top_members=base.top_members,
        bottom_members=base.bottom_members,
        eligibility=base.eligibility,
        eligibility_reason=base.eligibility_reason,
        median_percentile=median_percentile,
        breadth_percentile=breadth_percentile,
        period_score=period_score,
        score_unavailable_reason=score_unavailable_reason,
    )


def calculate_composite_and_status(
    periods: tuple[ClassificationPeriodResult, ...],
    ranges: tuple[ResolvedRange, ...],
) -> tuple[Decimal | None, str, str | None]:
    """Calculate one classification's exact composite and multi-period state."""

    range_by_ordinal = {item.ordinal: item for item in ranges}
    ordered = tuple(sorted(periods, key=lambda item: item.range_ordinal))
    if (
        len(ordered) != len(ranges)
        or {item.range_ordinal for item in ordered} != set(range_by_ordinal)
    ):
        raise ValueError("period results must cover every range exactly once")
    missing_scores = [
        (
            item.range_key,
            item.score_unavailable_reason
            or item.eligibility_reason
            or "UNAVAILABLE",
        )
        for item in ordered
        if item.period_score is None
    ]
    with local_rs_context():
        if missing_scores:
            composite = None
            reason = ";".join(
                f"RANGE_SCORE_UNAVAILABLE:{key}:{code}"
                for key, code in missing_scores
            )
        else:
            composite = Decimal(0)
            for item in ordered:
                score = item.period_score
                if score is None:
                    raise AssertionError("period score coverage changed")
                composite += score * range_by_ordinal[
                    item.range_ordinal
                ].normalized_weight
            reason = None

    if len(ordered) == 1:
        return composite, "NOT_APPLICABLE", reason
    medians = [item.median_rs for item in ordered]
    if any(value is None for value in medians):
        return composite, "INSUFFICIENT_DATA", reason
    concrete_medians = [value for value in medians if value is not None]
    if all(value > 0 for value in concrete_medians):
        return composite, "SUSTAINED_STRONG", reason
    if all(value < 0 for value in concrete_medians):
        return composite, "SUSTAINED_WEAK", reason

    spans = {
        item.range_ordinal: (
            range_by_ordinal[item.range_ordinal].requested_end_date
            - range_by_ordinal[item.range_ordinal].requested_start_date
        ).days
        for item in ordered
    }
    minimum = min(spans.values())
    maximum = max(spans.values())
    shortest = [ordinal for ordinal, span in spans.items() if span == minimum]
    longest = [ordinal for ordinal, span in spans.items() if span == maximum]
    if len(shortest) != 1 or len(longest) != 1:
        return composite, "DIVERGENT_TIED_SPAN", reason
    median_by_ordinal = {
        item.range_ordinal: item.median_rs for item in ordered
    }
    shortest_median = median_by_ordinal[shortest[0]]
    longest_median = median_by_ordinal[longest[0]]
    if shortest_median is None or longest_median is None:
        raise AssertionError("median coverage changed")
    if shortest_median > 0 and longest_median < 0:
        return composite, "RECENTLY_STRENGTHENING", reason
    if shortest_median < 0 and longest_median > 0:
        return composite, "RECENTLY_WEAKENING", reason
    return composite, "DIVERGENT", reason


def finalize_run_calculation(
    prepared: PreparedCalculation,
    stock: StockCalculationOutput,
    chunks: tuple[ClassificationBaseChunkOutput, ...],
) -> RunCalculationOutput | CalculationFatalIssue:
    """Score complete classification chunks and form the final pure output."""

    identities = {
        member.classification_snapshot_key: (
            member.classification_name,
            member.classification_normalized_name,
        )
        for member in prepared.members
    }
    expected_keys = set(identities)
    chunk_keys = [
        key
        for chunk in chunks
        for key in chunk.classification_keys
    ]
    if (
        set(chunk_keys) != expected_keys
        or len(chunk_keys) != len(set(chunk_keys))
    ):
        return _fatal("CLASSIFICATION_CHUNK_COVERAGE_INVALID")
    bases = [
        base
        for chunk in chunks
        for base in chunk.period_bases
    ]
    base_keys = [
        (base.classification_snapshot_key, base.range_ordinal)
        for base in bases
    ]
    expected_base_keys = {
        (classification_key, resolved.ordinal)
        for classification_key in expected_keys
        for resolved in prepared.ranges
    }
    if set(base_keys) != expected_base_keys or len(base_keys) != len(set(base_keys)):
        return _fatal("CLASSIFICATION_BASE_COVERAGE_INVALID")

    period_results: list[ClassificationPeriodResult] = []
    with local_rs_context():
        for resolved in prepared.ranges:
            range_bases = [
                base
                for base in bases
                if base.range_ordinal == resolved.ordinal
            ]
            range_bases.sort(
                key=lambda item: (
                    item.classification_normalized_name,
                    item.classification_snapshot_key,
                )
            )
            eligible = [
                base for base in range_bases if base.eligibility == "ELIGIBLE"
            ]
            if len(eligible) < 3:
                for base in range_bases:
                    score_reason = (
                        "COMPARABLE_CLASSIFICATIONS_LT_3"
                        if base.eligibility == "ELIGIBLE"
                        else None
                    )
                    period_results.append(
                        _period_result(
                            base,
                            median_percentile=None,
                            breadth_percentile=None,
                            period_score=None,
                            score_unavailable_reason=score_reason,
                        )
                    )
                continue
            medians = tuple(
                base.median_rs
                for base in eligible
                if base.median_rs is not None
            )
            breadths = tuple(
                base.strong_breadth
                for base in eligible
                if base.strong_breadth is not None
            )
            if len(medians) != len(eligible) or len(breadths) != len(eligible):
                return _fatal("ELIGIBLE_CLASSIFICATION_METRIC_MISSING")
            for base in range_bases:
                if base.eligibility != "ELIGIBLE":
                    period_results.append(
                        _period_result(
                            base,
                            median_percentile=None,
                            breadth_percentile=None,
                            period_score=None,
                            score_unavailable_reason=None,
                        )
                    )
                    continue
                if base.median_rs is None or base.strong_breadth is None:
                    return _fatal("ELIGIBLE_CLASSIFICATION_METRIC_MISSING")
                median_percentile = _percentile(base.median_rs, medians)
                breadth_percentile = _percentile(
                    base.strong_breadth,
                    breadths,
                )
                score = (
                    median_percentile * Decimal("0.70")
                    + breadth_percentile * Decimal("0.30")
                )
                period_results.append(
                    _period_result(
                        base,
                        median_percentile=median_percentile,
                        breadth_percentile=breadth_percentile,
                        period_score=score,
                        score_unavailable_reason=None,
                    )
                )

    overall = []
    for classification_key, (name, normalized_name) in identities.items():
        classification_periods = tuple(
            item
            for item in period_results
            if item.classification_snapshot_key == classification_key
        )
        try:
            composite, status, reason = calculate_composite_and_status(
                classification_periods,
                prepared.ranges,
            )
        except (ArithmeticError, ValueError):
            return _fatal("CLASSIFICATION_FINALIZATION_FAILED")
        overall.append(
            ClassificationStrengthResult(
                classification_snapshot_key=classification_key,
                classification_name=name,
                classification_normalized_name=normalized_name,
                period_results=classification_periods,
                composite_score=composite,
                status=status,
                reason=reason,
            )
        )
    overall.sort(
        key=lambda item: (
            item.composite_score is None,
            (
                -item.composite_score
                if item.composite_score is not None
                else Decimal(0)
            ),
            item.classification_normalized_name,
            item.classification_snapshot_key,
        )
    )
    return RunCalculationOutput(
        algorithm_version=prepared.algorithm_version,
        resolved_ranges=prepared.ranges,
        stock_results=stock.stock_results,
        classification_period_results=tuple(period_results),
        classification_results=tuple(overall),
        failure_candidates=stock.failure_candidates,
        valid_member_count=stock.valid_member_count,
        failed_member_count=stock.failed_member_count,
        failed_member_range_count=stock.failed_member_range_count,
    )
