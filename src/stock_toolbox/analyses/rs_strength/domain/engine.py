"""Public staged entry points for ``rs-algorithm-v1``.

There is intentionally no alternate ``evaluate`` path: callers compose these
seven stages, optionally chunking the three member/classification stages.
"""

from stock_toolbox.analyses.rs_strength.domain.classifications import (
    aggregate_classification_chunk,
    finalize_run_calculation,
)
from stock_toolbox.analyses.rs_strength.domain.members import (
    calculate_member_chunk,
    complete_stock_calculation,
    complete_validation,
    normalize_member_chunk,
)
from stock_toolbox.analyses.rs_strength.domain.models import (
    CalculationFatalIssue,
    RunCalculationInput,
    RunCalculationOutput,
)
from stock_toolbox.analyses.rs_strength.domain.validation import resolve_benchmark_and_ranges


def calculate_run(
    input: RunCalculationInput,
) -> RunCalculationOutput | CalculationFatalIssue:
    """Execute the canonical seven stages serially for application callers."""

    resolved = resolve_benchmark_and_ranges(input)
    if isinstance(resolved, CalculationFatalIssue):
        return resolved
    member_ordinals = tuple(
        sorted(member.ordinal for member in input.members)
    )
    normalized = normalize_member_chunk(input, resolved, member_ordinals)
    if isinstance(normalized, CalculationFatalIssue):
        return normalized
    prepared = complete_validation(input, resolved, (normalized,))
    if isinstance(prepared, CalculationFatalIssue):
        return prepared
    calculated = calculate_member_chunk(prepared, member_ordinals)
    if isinstance(calculated, CalculationFatalIssue):
        return calculated
    stocks = complete_stock_calculation(prepared, (calculated,))
    if isinstance(stocks, CalculationFatalIssue):
        return stocks
    classification_keys = tuple(
        sorted(
            {
                member.classification_snapshot_key
                for member in input.members
            }
        )
    )
    aggregated = aggregate_classification_chunk(
        prepared,
        stocks,
        classification_keys,
    )
    if isinstance(aggregated, CalculationFatalIssue):
        return aggregated
    return finalize_run_calculation(prepared, stocks, (aggregated,))

__all__ = [
    "aggregate_classification_chunk",
    "calculate_member_chunk",
    "calculate_run",
    "complete_stock_calculation",
    "complete_validation",
    "finalize_run_calculation",
    "normalize_member_chunk",
    "resolve_benchmark_and_ranges",
]
