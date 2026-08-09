"""Member normalization, RS calculation, and stable failure collation."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from decimal import Decimal, DecimalException

from stock_toolbox.analyses.rs_strength.domain.models import (
    CalculationFailureCandidate,
    CalculationFailureDraft,
    CalculationFatalIssue,
    CalculationMember,
    MemberCalculationChunkOutput,
    MemberNormalizationChunkOutput,
    PreparedCalculation,
    ResolvedBenchmarkRanges,
    RunCalculationInput,
    StockCalculationOutput,
    StockRSResult,
)
from stock_toolbox.analyses.rs_strength.domain.numeric import local_rs_context
from stock_toolbox.analyses.rs_strength.domain.validation import normalize_price_series


def _fatal(
    code: str,
    *,
    stage: str = "VALIDATE",
    **parameters: str,
) -> CalculationFatalIssue:
    return CalculationFatalIssue(
        stage=stage,  # type: ignore[arg-type]
        code=code,
        range_key=None,
        reason_parameters=tuple(parameters.items()),
    )


def _validate_requested_ordinals(
    members: tuple[CalculationMember, ...],
    requested: tuple[int, ...],
) -> CalculationFatalIssue | None:
    expected = {member.ordinal for member in members}
    if len(requested) != len(set(requested)) or not set(requested) <= expected:
        return _fatal("MEMBER_CHUNK_ORDINAL_INVALID")
    return None


def normalize_member_chunk(
    input: RunCalculationInput,
    resolved: ResolvedBenchmarkRanges,
    member_ordinals: tuple[int, ...],
) -> MemberNormalizationChunkOutput | CalculationFatalIssue:
    """Normalize exactly the requested member series or its fetch issue."""

    if input.algorithm_version != resolved.algorithm_version:
        return _fatal("ALGORITHM_VERSION_MISMATCH")
    invalid = _validate_requested_ordinals(input.members, member_ordinals)
    if invalid is not None:
        return invalid
    members = {member.ordinal: member for member in input.members}
    issue_counts = Counter(issue.member_ordinal for issue in input.member_data_issues)
    issues = {issue.member_ordinal: issue for issue in input.member_data_issues}
    normalized = {}
    failures: list[CalculationFailureDraft] = []
    for ordinal in sorted(member_ordinals):
        member = members[ordinal]
        issue = issues.get(ordinal)
        series = input.series_by_symbol.get(member.symbol)
        if issue_counts[ordinal] > 1:
            return _fatal("MEMBER_DATA_ISSUE_DUPLICATE")
        if issue is not None and issue.symbol != member.symbol:
            return _fatal("MEMBER_DATA_ISSUE_SYMBOL_MISMATCH")
        if issue is not None and series is not None:
            return _fatal("MEMBER_DATA_SOURCE_CONFLICT")
        if issue is not None:
            failures.append(
                CalculationFailureDraft(
                    scope="MEMBER",
                    member_ordinal=ordinal,
                    symbol=member.symbol,
                    range_key=None,
                    range_ordinal=None,
                    stage="FETCH",
                    code=issue.code,
                    reason_parameters=issue.reason_parameters,
                )
            )
            continue
        if series is None:
            return _fatal(
                "MEMBER_DATA_SOURCE_MISSING",
                member_ordinal=str(ordinal),
            )
        if series.symbol != member.symbol:
            failures.append(
                CalculationFailureDraft(
                    scope="MEMBER",
                    member_ordinal=ordinal,
                    symbol=member.symbol,
                    range_key=None,
                    range_ordinal=None,
                    stage="VALIDATE",
                    code="MEMBER_SYMBOL_MISMATCH",
                    reason_parameters=(),
                )
            )
            continue
        try:
            normalized[member.symbol] = normalize_price_series(series)
        except (ArithmeticError, TypeError, ValueError):
            failures.append(
                CalculationFailureDraft(
                    scope="MEMBER",
                    member_ordinal=ordinal,
                    symbol=member.symbol,
                    range_key=None,
                    range_ordinal=None,
                    stage="VALIDATE",
                    code="MEMBER_SERIES_INVALID",
                    reason_parameters=(),
                )
            )
    return MemberNormalizationChunkOutput(
        member_ordinals=tuple(sorted(member_ordinals)),
        normalized_series_by_symbol=normalized,
        failure_drafts=tuple(failures),
    )


def _classification_snapshot_issue(
    members: tuple[CalculationMember, ...],
) -> CalculationFatalIssue | None:
    by_key: dict[str, tuple[str, str]] = {}
    by_normalized: dict[str, str] = {}
    for member in members:
        identity = (
            member.classification_name,
            member.classification_normalized_name,
        )
        existing = by_key.setdefault(member.classification_snapshot_key, identity)
        if existing != identity:
            return _fatal("CLASSIFICATION_SNAPSHOT_CONFLICT")
        existing_key = by_normalized.setdefault(
            member.classification_normalized_name,
            member.classification_snapshot_key,
        )
        if existing_key != member.classification_snapshot_key:
            return _fatal("CLASSIFICATION_NORMALIZED_NAME_COLLISION")
    return None


def complete_validation(
    input: RunCalculationInput,
    resolved: ResolvedBenchmarkRanges,
    chunks: tuple[MemberNormalizationChunkOutput, ...],
) -> PreparedCalculation | CalculationFatalIssue:
    """Verify chunk coverage and freeze normalized members in stable order."""

    expected = sorted(member.ordinal for member in input.members)
    actual = [
        ordinal
        for chunk in chunks
        for ordinal in chunk.member_ordinals
    ]
    if sorted(actual) != expected or len(actual) != len(set(actual)):
        return _fatal("MEMBER_CHUNK_COVERAGE_INVALID")
    snapshot_issue = _classification_snapshot_issue(input.members)
    if snapshot_issue is not None:
        return snapshot_issue
    series = {}
    failures: list[CalculationFailureDraft] = []
    for chunk in chunks:
        for symbol, normalized in chunk.normalized_series_by_symbol.items():
            if symbol in series:
                return _fatal("MEMBER_NORMALIZED_SERIES_DUPLICATE")
            series[symbol] = normalized
        failures.extend(chunk.failure_drafts)
    return PreparedCalculation(
        algorithm_version=input.algorithm_version,
        benchmark_symbol=input.benchmark_symbol,
        ranges=resolved.ranges,
        members=tuple(
            sorted(
                input.members,
                key=lambda member: (
                    member.ordinal,
                    member.symbol,
                    member.run_member_id,
                ),
            )
        ),
        normalized_series_by_symbol=series,
        initial_failure_drafts=tuple(failures),
    )


def calculate_member_chunk(
    prepared: PreparedCalculation,
    member_ordinals: tuple[int, ...],
) -> MemberCalculationChunkOutput | CalculationFatalIssue:
    """Calculate all selected ranges for exactly the requested members."""

    invalid = _validate_requested_ordinals(prepared.members, member_ordinals)
    if invalid is not None:
        return replace(invalid, stage="CALCULATE")
    members = {member.ordinal: member for member in prepared.members}
    results: list[StockRSResult] = []
    failures: list[CalculationFailureDraft] = []
    with local_rs_context():
        for ordinal in sorted(member_ordinals):
            member = members[ordinal]
            series = prepared.normalized_series_by_symbol.get(member.symbol)
            if series is None:
                continue
            closes = {point.date: point.close for point in series.points}
            for resolved in prepared.ranges:
                start_close = closes.get(resolved.actual_start_date)
                end_close = closes.get(resolved.actual_end_date)
                if start_close is None or end_close is None:
                    if start_close is None and end_close is None:
                        code = "MISSING_COMMON_BOUNDARY_CLOSES"
                    elif start_close is None:
                        code = "MISSING_COMMON_START_CLOSE"
                    else:
                        code = "MISSING_COMMON_END_CLOSE"
                    failures.append(
                        CalculationFailureDraft(
                            scope="MEMBER_RANGE",
                            member_ordinal=member.ordinal,
                            symbol=member.symbol,
                            range_key=resolved.key,
                            range_ordinal=resolved.ordinal,
                            stage="CALCULATE",
                            code=code,
                            reason_parameters=(),
                        )
                    )
                    continue
                try:
                    stock_return = end_close / start_close - Decimal(1)
                    benchmark_return = (
                        resolved.benchmark_end_close
                        / resolved.benchmark_start_close
                        - Decimal(1)
                    )
                    rs = (stock_return - benchmark_return) * Decimal(100)
                    if not all(
                        value.is_finite()
                        for value in (stock_return, benchmark_return, rs)
                    ):
                        raise ArithmeticError
                except (ArithmeticError, DecimalException):
                    return _fatal(
                        "MEMBER_DECIMAL_CALCULATION_FAILED",
                        stage="CALCULATE",
                        member_ordinal=str(member.ordinal),
                    )
                results.append(
                    StockRSResult(
                        run_member_id=member.run_member_id,
                        member_ordinal=member.ordinal,
                        symbol=member.symbol,
                        run_range_id=resolved.run_range_id,
                        range_key=resolved.key,
                        range_label=resolved.label,
                        range_kind=resolved.kind,
                        range_ordinal=resolved.ordinal,
                        stock_start_close=start_close,
                        stock_end_close=end_close,
                        benchmark_start_close=resolved.benchmark_start_close,
                        benchmark_end_close=resolved.benchmark_end_close,
                        stock_return=stock_return,
                        benchmark_return=benchmark_return,
                        rs=rs,
                    )
                )
    return MemberCalculationChunkOutput(
        member_ordinals=tuple(sorted(member_ordinals)),
        stock_results=tuple(results),
        failure_drafts=tuple(failures),
    )


def _failure_sort_key(
    failure: CalculationFailureDraft,
) -> tuple[object, ...]:
    range_ordinal = (
        2**63 - 1 if failure.range_ordinal is None else failure.range_ordinal
    )
    return (
        failure.member_ordinal,
        range_ordinal,
        failure.stage,
        failure.code,
        failure.reason_parameters,
    )


def complete_stock_calculation(
    prepared: PreparedCalculation,
    chunks: tuple[MemberCalculationChunkOutput, ...],
) -> StockCalculationOutput | CalculationFatalIssue:
    """Merge member chunks and assign stable failure candidate ordinals."""

    expected = sorted(member.ordinal for member in prepared.members)
    actual = [
        ordinal
        for chunk in chunks
        for ordinal in chunk.member_ordinals
    ]
    if sorted(actual) != expected or len(actual) != len(set(actual)):
        return _fatal("MEMBER_CALCULATION_CHUNK_COVERAGE_INVALID", stage="CALCULATE")
    results = [
        result
        for chunk in chunks
        for result in chunk.stock_results
    ]
    results.sort(key=lambda item: (item.member_ordinal, item.range_ordinal))
    result_keys = [
        (result.member_ordinal, result.range_ordinal) for result in results
    ]
    if len(result_keys) != len(set(result_keys)):
        return _fatal("STOCK_RESULT_DUPLICATE", stage="CALCULATE")

    drafts = list(prepared.initial_failure_drafts)
    drafts.extend(
        failure
        for chunk in chunks
        for failure in chunk.failure_drafts
    )
    source_keys = [
        (
            draft.member_ordinal,
            draft.range_ordinal,
            draft.stage,
            draft.code,
        )
        for draft in drafts
    ]
    if len(source_keys) != len(set(source_keys)):
        return _fatal("FAILURE_DRAFT_DUPLICATE", stage="CALCULATE")
    drafts.sort(key=_failure_sort_key)
    candidates = tuple(
        CalculationFailureCandidate(
            scope=draft.scope,
            member_ordinal=draft.member_ordinal,
            symbol=draft.symbol,
            range_key=draft.range_key,
            range_ordinal=draft.range_ordinal,
            stage=draft.stage,
            code=draft.code,
            reason_parameters=draft.reason_parameters,
            fatal=False,
            stable_ordinal=ordinal,
        )
        for ordinal, draft in enumerate(drafts)
    )

    failed_members = {failure.member_ordinal for failure in candidates}
    range_count = len(prepared.ranges)
    result_counts = Counter(result.member_ordinal for result in results)
    for member in prepared.members:
        count = result_counts[member.ordinal]
        if member.ordinal in failed_members:
            continue
        if count != range_count:
            return _fatal("MEMBER_RESULT_COVERAGE_INVALID", stage="CALCULATE")
    return StockCalculationOutput(
        stock_results=tuple(results),
        failure_candidates=candidates,
        valid_member_count=len(prepared.members) - len(failed_members),
        failed_member_count=len(failed_members),
        failed_member_range_count=sum(
            failure.scope == "MEMBER_RANGE" for failure in candidates
        ),
    )
