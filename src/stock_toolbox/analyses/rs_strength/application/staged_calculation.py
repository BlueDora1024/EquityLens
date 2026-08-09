"""Progress-aware composition of the canonical RS domain stages."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from stock_toolbox.analyses.rs_strength.application.models import RunProgress
from stock_toolbox.analyses.rs_strength.domain.engine import (
    aggregate_classification_chunk,
    calculate_member_chunk,
    complete_stock_calculation,
    complete_validation,
    finalize_run_calculation,
    normalize_member_chunk,
    resolve_benchmark_and_ranges,
)
from stock_toolbox.analyses.rs_strength.domain.models import (
    CalculationFatalIssue,
    RunCalculationInput,
    RunCalculationOutput,
)
from stock_toolbox.core.operations.registry import OperationControl


def _chunks[T](values: Sequence[T], size: int) -> tuple[tuple[T, ...], ...]:
    if size < 1:
        raise ValueError("chunk size must be positive")
    return tuple(
        tuple(values[offset : offset + size])
        for offset in range(0, len(values), size)
    )


def calculate_run_staged(
    calculation_input: RunCalculationInput,
    operation_control: OperationControl,
    progress: Callable[[RunProgress], None],
    *,
    member_chunk_size: int = 50,
    classification_chunk_size: int = 10,
) -> RunCalculationOutput | CalculationFatalIssue | None:
    """Run the canonical algorithm in chunks; ``None`` means canceled."""

    resolved = resolve_benchmark_and_ranges(calculation_input)
    if isinstance(resolved, CalculationFatalIssue):
        return resolved
    member_ordinals = tuple(
        sorted(member.ordinal for member in calculation_input.members)
    )
    ordinal_to_symbol = {
        member.ordinal: member.symbol for member in calculation_input.members
    }
    member_chunks = _chunks(member_ordinals, member_chunk_size)

    normalized_chunks = []
    completed = 0
    progress(RunProgress("VALIDATING", 0, len(member_ordinals)))
    for ordinals in member_chunks:
        if operation_control.cancellation_requested():
            return None
        normalized = normalize_member_chunk(calculation_input, resolved, ordinals)
        if isinstance(normalized, CalculationFatalIssue):
            return normalized
        normalized_chunks.append(normalized)
        completed += len(ordinals)
        progress(
            RunProgress(
                "VALIDATING",
                completed,
                len(member_ordinals),
                ordinal_to_symbol[ordinals[-1]],
            )
        )
    prepared = complete_validation(
        calculation_input,
        resolved,
        tuple(normalized_chunks),
    )
    if isinstance(prepared, CalculationFatalIssue):
        return prepared

    calculation_chunks = []
    completed = 0
    progress(RunProgress("CALCULATING", 0, len(member_ordinals)))
    for ordinals in member_chunks:
        if operation_control.cancellation_requested():
            return None
        calculated = calculate_member_chunk(prepared, ordinals)
        if isinstance(calculated, CalculationFatalIssue):
            return calculated
        calculation_chunks.append(calculated)
        completed += len(ordinals)
        progress(
            RunProgress(
                "CALCULATING",
                completed,
                len(member_ordinals),
                ordinal_to_symbol[ordinals[-1]],
            )
        )
    stocks = complete_stock_calculation(prepared, tuple(calculation_chunks))
    if isinstance(stocks, CalculationFatalIssue):
        return stocks
    progress(
        RunProgress(
            "CALCULATING",
            len(member_ordinals),
            len(member_ordinals),
            ordinal_to_symbol[member_ordinals[-1]] if member_ordinals else None,
            stocks.valid_member_count,
            stocks.failed_member_count,
        )
    )

    classification_keys = tuple(
        sorted(
            {
                member.classification_snapshot_key
                for member in calculation_input.members
            }
        )
    )
    classification_chunks = _chunks(
        classification_keys,
        classification_chunk_size,
    )
    base_chunks = []
    completed = 0
    progress(RunProgress("AGGREGATING", 0, len(classification_keys)))
    for keys in classification_chunks:
        if operation_control.cancellation_requested():
            return None
        aggregated = aggregate_classification_chunk(prepared, stocks, keys)
        if isinstance(aggregated, CalculationFatalIssue):
            return aggregated
        base_chunks.append(aggregated)
        completed += len(keys)
        progress(
            RunProgress(
                "AGGREGATING",
                completed,
                len(classification_keys),
                f"{completed} 个分类",
            )
        )
    return finalize_run_calculation(prepared, stocks, tuple(base_chunks))
