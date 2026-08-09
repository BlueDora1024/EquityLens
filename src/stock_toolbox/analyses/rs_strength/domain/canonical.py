"""Identity-stripped canonical serialization for RS algorithm outputs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from stock_toolbox.analyses.rs_strength.domain.models import (
    ClassificationPeriodResult,
    RankedMemberRS,
    RunCalculationOutput,
)
from stock_toolbox.analyses.rs_strength.domain.numeric import canonical_decimal


def _decimal(value: Any) -> str | None:
    if value is None:
        return None
    return canonical_decimal(value)


def _ranked(item: RankedMemberRS) -> dict[str, Any]:
    return {
        "member_ordinal": item.member_ordinal,
        "symbol": item.symbol,
        "rs": canonical_decimal(item.rs),
    }


def _period(item: ClassificationPeriodResult) -> dict[str, Any]:
    return {
        "classification_name": item.classification_name,
        "classification_normalized_name": item.classification_normalized_name,
        "range_key": item.range_key,
        "range_kind": item.range_kind,
        "range_ordinal": item.range_ordinal,
        "total_member_count": item.total_member_count,
        "valid_member_count": item.valid_member_count,
        "coverage": canonical_decimal(item.coverage),
        "mean_rs": _decimal(item.mean_rs),
        "median_rs": _decimal(item.median_rs),
        "positive_count": item.positive_count,
        "strong_breadth": _decimal(item.strong_breadth),
        "top_members": [_ranked(member) for member in item.top_members],
        "bottom_members": [_ranked(member) for member in item.bottom_members],
        "eligibility": item.eligibility,
        "eligibility_reason": item.eligibility_reason,
        "median_percentile": _decimal(item.median_percentile),
        "breadth_percentile": _decimal(item.breadth_percentile),
        "period_score": _decimal(item.period_score),
        "score_unavailable_reason": item.score_unavailable_reason,
    }


def algorithm_payload(output: RunCalculationOutput) -> dict[str, Any]:
    """Create the versioned canonical primitive tree without runtime IDs."""

    ranges = sorted(
        output.resolved_ranges,
        key=lambda item: (item.ordinal, item.key, item.run_range_id),
    )
    stocks = sorted(
        output.stock_results,
        key=lambda item: (
            item.member_ordinal,
            item.range_ordinal,
            item.symbol,
        ),
    )
    periods = sorted(
        output.classification_period_results,
        key=lambda item: (
            item.range_ordinal,
            item.classification_normalized_name,
            item.classification_snapshot_key,
        ),
    )
    overall = sorted(
        output.classification_results,
        key=lambda item: (
            item.composite_score is None,
            (
                -item.composite_score
                if item.composite_score is not None
                else 0
            ),
            item.classification_normalized_name,
            item.classification_snapshot_key,
        ),
    )
    failures = sorted(
        output.failure_candidates,
        key=lambda item: item.stable_ordinal,
    )
    return {
        "schema": "rs-algorithm-output-v1",
        "algorithm_version": output.algorithm_version,
        "ranges": [
            {
                "range_key": item.key,
                "range_kind": item.kind,
                "range_ordinal": item.ordinal,
                "requested_start_date": item.requested_start_date.isoformat(),
                "requested_end_date": item.requested_end_date.isoformat(),
                "actual_start_date": item.actual_start_date.isoformat(),
                "actual_end_date": item.actual_end_date.isoformat(),
                "benchmark_start_close": canonical_decimal(
                    item.benchmark_start_close
                ),
                "benchmark_end_close": canonical_decimal(
                    item.benchmark_end_close
                ),
                "base_weight": canonical_decimal(item.base_weight),
                "normalized_weight": canonical_decimal(
                    item.normalized_weight
                ),
            }
            for item in ranges
        ],
        "stock_results": [
            {
                "member_ordinal": item.member_ordinal,
                "symbol": item.symbol,
                "range_key": item.range_key,
                "range_kind": item.range_kind,
                "range_ordinal": item.range_ordinal,
                "stock_start_close": canonical_decimal(
                    item.stock_start_close
                ),
                "stock_end_close": canonical_decimal(item.stock_end_close),
                "benchmark_start_close": canonical_decimal(
                    item.benchmark_start_close
                ),
                "benchmark_end_close": canonical_decimal(
                    item.benchmark_end_close
                ),
                "stock_return": canonical_decimal(item.stock_return),
                "benchmark_return": canonical_decimal(
                    item.benchmark_return
                ),
                "rs": canonical_decimal(item.rs),
                "unit": item.unit,
            }
            for item in stocks
        ],
        "classification_period_results": [_period(item) for item in periods],
        "classification_results": [
            {
                "name": item.classification_name,
                "normalized_name": item.classification_normalized_name,
                "composite_score": _decimal(item.composite_score),
                "status": item.status,
                "reason": item.reason,
            }
            for item in overall
        ],
        "failure_candidates": [
            {
                "stable_ordinal": item.stable_ordinal,
                "scope": item.scope,
                "member_ordinal": item.member_ordinal,
                "symbol": item.symbol,
                "range_key": item.range_key,
                "range_ordinal": item.range_ordinal,
                "stage": item.stage,
                "code": item.code,
                "reason_parameters": dict(item.reason_parameters),
                "fatal": item.fatal,
            }
            for item in failures
        ],
        "valid_member_count": output.valid_member_count,
        "failed_member_count": output.failed_member_count,
        "failed_member_range_count": output.failed_member_range_count,
    }


def algorithm_canonical_bytes(output: RunCalculationOutput) -> bytes:
    """Serialize an algorithm output using the frozen JSON byte rules."""

    return json.dumps(
        algorithm_payload(output),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def algorithm_sha256(output: RunCalculationOutput) -> str:
    """Return the canonical algorithm SHA-256 digest."""

    return hashlib.sha256(algorithm_canonical_bytes(output)).hexdigest()


def benchmark_payload(
    output: RunCalculationOutput,
    *,
    benchmark_version: str,
    session_count: int,
    member_count: int,
    classification_count: int,
) -> dict[str, Any]:
    """Project an engine output onto the frozen benchmark golden schema."""

    payload = algorithm_payload(output)
    periods_by_identity = {
        (
            item.range_ordinal,
            item.classification_normalized_name,
        ): item
        for item in output.classification_period_results
    }
    overall_by_identity = {
        item.classification_normalized_name: item
        for item in output.classification_results
    }
    benchmark_periods = []
    for item in payload["classification_period_results"]:
        period_source = periods_by_identity[
            (
                item["range_ordinal"],
                item["classification_normalized_name"],
            )
        ]
        benchmark_periods.append(
            {
                "classification_key": period_source.classification_snapshot_key,
                **item,
            }
        )
    benchmark_overall = []
    for item in payload["classification_results"]:
        overall_source = overall_by_identity[item["normalized_name"]]
        benchmark_overall.append(
            {
                "classification_key": overall_source.classification_snapshot_key,
                **item,
            }
        )
    return {
        "schema": "rs-benchmark-output-v1",
        "algorithm_version": output.algorithm_version,
        "benchmark_version": benchmark_version,
        "session_count": session_count,
        "member_count": member_count,
        "classification_count": classification_count,
        "ranges": payload["ranges"],
        "stock_results": payload["stock_results"],
        "classification_period_results": benchmark_periods,
        "classification_results": benchmark_overall,
        "failure_candidates": payload["failure_candidates"],
        "valid_member_count": output.valid_member_count,
        "failed_member_count": output.failed_member_count,
        "failed_member_range_count": output.failed_member_range_count,
    }


def benchmark_canonical_bytes(
    output: RunCalculationOutput,
    *,
    benchmark_version: str,
    session_count: int,
    member_count: int,
    classification_count: int,
) -> bytes:
    """Serialize the frozen benchmark projection."""

    return json.dumps(
        benchmark_payload(
            output,
            benchmark_version=benchmark_version,
            session_count=session_count,
            member_count=member_count,
            classification_count=classification_count,
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
