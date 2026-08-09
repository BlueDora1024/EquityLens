"""Packaged deterministic 600-member RS benchmark scenario."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from stock_toolbox.analyses.rs_strength.domain.canonical import benchmark_canonical_bytes
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
    ALGORITHM_VERSION,
    CalculationFatalIssue,
    CalculationMember,
    PricePoint,
    PriceSeries,
    RequestedRange,
    ResolvedBenchmarkRanges,
    RunCalculationInput,
    RunCalculationOutput,
    StockCalculationOutput,
)

BENCHMARK_VERSION = "synthetic-spy-v1"
EXPECTED_BYTES = 792434
EXPECTED_SHA256 = "6ad2505299e01cc3b78d605982059b2917ea88b30c430d171d3a05fca05386a9"
MEMBER_COUNT = 600
CLASSIFICATION_COUNT = 20
RANGE_COUNT = 3

_FIXED_CLOSURES = {
    date.fromisoformat(value)
    for value in (
        "2025-09-01",
        "2025-11-27",
        "2025-12-25",
        "2026-01-01",
        "2026-01-19",
        "2026-04-03",
        "2026-05-25",
        "2026-06-19",
        "2026-07-03",
    )
}


@dataclass(frozen=True, slots=True)
class FrozenBenchmarkResult:
    output: RunCalculationOutput
    session_count: int
    canonical_bytes: int
    canonical_sha256: str


def sessions() -> tuple[date, ...]:
    current = date(2025, 7, 24)
    end = date(2026, 7, 23)
    output = []
    while current <= end:
        if current.weekday() < 5 and current not in _FIXED_CLOSURES:
            output.append(current)
        current += timedelta(days=1)
    if len(output) != 252:
        raise RuntimeError("frozen benchmark session count changed")
    return tuple(output)


def _price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def benchmark_input(*, reverse: bool = False) -> RunCalculationInput:
    trading_sessions = sessions()
    ranges: tuple[RequestedRange, ...] = (
        RequestedRange(
            "00000000-0000-4000-8000-000000000001",
            "3M",
            "3M",
            "PRESET_3M",
            0,
            date(2026, 4, 23),
            date(2026, 7, 23),
        ),
        RequestedRange(
            "00000000-0000-4000-8000-000000000002",
            "6M",
            "6M",
            "PRESET_6M",
            1,
            date(2026, 1, 23),
            date(2026, 7, 23),
        ),
        RequestedRange(
            "00000000-0000-4000-8000-000000000003",
            "1Y",
            "1Y",
            "PRESET_1Y",
            2,
            date(2025, 7, 23),
            date(2026, 7, 23),
        ),
    )
    members = tuple(
        CalculationMember(
            f"10000000-0000-4000-8000-{ordinal + 1:012d}",
            ordinal,
            f"S{ordinal:03d}.US",
            f"C{ordinal % CLASSIFICATION_COUNT:02d}",
            f"C{ordinal % CLASSIFICATION_COUNT:02d}",
            f"c{ordinal % CLASSIFICATION_COUNT:02d}",
        )
        for ordinal in range(MEMBER_COUNT)
    )
    benchmark_points = tuple(
        PricePoint(day, _price(Decimal(400) + Decimal("0.25") * ordinal))
        for ordinal, day in enumerate(trading_sessions)
    )
    series = {"SPY.US": PriceSeries("SPY.US", benchmark_points)}
    for member in members:
        base = Decimal(50) + Decimal("0.10") * member.ordinal
        slope = Decimal("0.05") + Decimal("0.01") * (member.ordinal % 17)
        points = tuple(
            PricePoint(day, _price(base + slope * session_ordinal))
            for session_ordinal, day in enumerate(trading_sessions)
        )
        series[member.symbol] = PriceSeries(member.symbol, points)
    if reverse:
        ranges = tuple(reversed(ranges))
        members = tuple(reversed(members))
        series = {
            symbol: PriceSeries(item.symbol, tuple(reversed(item.points)))
            for symbol, item in reversed(tuple(series.items()))
        }
    return RunCalculationInput(
        algorithm_version=ALGORITHM_VERSION,
        benchmark_symbol="SPY.US",
        requested_ranges=ranges,
        members=members,
        series_by_symbol=series,
        member_data_issues=(),
    )


def run_benchmark(
    input_data: RunCalculationInput,
    *,
    member_chunk_size: int = 100,
    classification_chunk_size: int = 5,
    reverse_chunks: bool = False,
) -> RunCalculationOutput:
    resolved = resolve_benchmark_and_ranges(input_data)
    if not isinstance(resolved, ResolvedBenchmarkRanges):
        raise TypeError(f"benchmark range resolution failed: {resolved.code}")
    member_ordinals = sorted(member.ordinal for member in input_data.members)
    member_chunks = [
        tuple(member_ordinals[index : index + member_chunk_size])
        for index in range(0, len(member_ordinals), member_chunk_size)
    ]
    normalization_chunks = [
        normalize_member_chunk(input_data, resolved, chunk)
        for chunk in member_chunks
    ]
    if any(isinstance(chunk, CalculationFatalIssue) for chunk in normalization_chunks):
        raise RuntimeError("benchmark normalization failed")
    if reverse_chunks:
        normalization_chunks.reverse()
    prepared = complete_validation(
        input_data,
        resolved,
        tuple(normalization_chunks),  # type: ignore[arg-type]
    )
    if isinstance(prepared, CalculationFatalIssue):
        raise TypeError(f"benchmark validation failed: {prepared.code}")
    calculation_chunks = [
        calculate_member_chunk(prepared, chunk) for chunk in member_chunks
    ]
    if any(isinstance(chunk, CalculationFatalIssue) for chunk in calculation_chunks):
        raise RuntimeError("benchmark stock calculation failed")
    if reverse_chunks:
        calculation_chunks.reverse()
    stock = complete_stock_calculation(
        prepared,
        tuple(calculation_chunks),  # type: ignore[arg-type]
    )
    if not isinstance(stock, StockCalculationOutput):
        raise TypeError(f"benchmark stock merge failed: {stock.code}")
    classification_keys = sorted(
        {member.classification_snapshot_key for member in input_data.members}
    )
    classification_chunks = [
        tuple(classification_keys[index : index + classification_chunk_size])
        for index in range(0, len(classification_keys), classification_chunk_size)
    ]
    aggregation_chunks = [
        aggregate_classification_chunk(prepared, stock, chunk)
        for chunk in classification_chunks
    ]
    if any(isinstance(chunk, CalculationFatalIssue) for chunk in aggregation_chunks):
        raise RuntimeError("benchmark classification aggregation failed")
    if reverse_chunks:
        aggregation_chunks.reverse()
    output = finalize_run_calculation(
        prepared,
        stock,
        tuple(aggregation_chunks),  # type: ignore[arg-type]
    )
    if not isinstance(output, RunCalculationOutput):
        raise TypeError(f"benchmark finalization failed: {output.code}")
    return output


def run_frozen_benchmark() -> FrozenBenchmarkResult:
    output = run_benchmark(benchmark_input())
    session_count = len(sessions())
    canonical = benchmark_canonical_bytes(
        output,
        benchmark_version=BENCHMARK_VERSION,
        session_count=session_count,
        member_count=MEMBER_COUNT,
        classification_count=CLASSIFICATION_COUNT,
    )
    digest = hashlib.sha256(canonical).hexdigest()
    if len(canonical) != EXPECTED_BYTES or digest != EXPECTED_SHA256:
        raise RuntimeError("frozen RS benchmark golden mismatch")
    return FrozenBenchmarkResult(output, session_count, len(canonical), digest)
