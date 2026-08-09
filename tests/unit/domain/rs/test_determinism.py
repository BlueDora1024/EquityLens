from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, getcontext, setcontext

from stock_toolbox.analyses.rs_strength.domain.canonical import (
    algorithm_canonical_bytes,
    algorithm_sha256,
)
from stock_toolbox.analyses.rs_strength.domain.models import (
    ClassificationPeriodResult,
    ClassificationStrengthResult,
    ResolvedRange,
    RunCalculationOutput,
    StockRSResult,
)


def output(identity_suffix: str) -> RunCalculationOutput:
    resolved = ResolvedRange(
        f"range-{identity_suffix}",
        "R1",
        "Range 1",
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
    )
    stock = StockRSResult(
        f"member-{identity_suffix}",
        0,
        "AAPL.US",
        resolved.run_range_id,
        "R1",
        "Range 1",
        "CUSTOM",
        0,
        Decimal(100),
        Decimal(125),
        Decimal(100),
        Decimal(110),
        Decimal("0.25"),
        Decimal("0.10"),
        Decimal(15),
    )
    period = ClassificationPeriodResult(
        "class-id-is-not-canonical",
        "AI",
        "ai",
        resolved.run_range_id,
        "R1",
        "Range 1",
        "CUSTOM",
        0,
        3,
        3,
        Decimal(1),
        Decimal(15),
        Decimal(15),
        3,
        Decimal(1),
        (),
        (),
        "ELIGIBLE",
        None,
        Decimal(50),
        Decimal(50),
        Decimal(50),
        None,
    )
    overall = ClassificationStrengthResult(
        "class-id-is-not-canonical",
        "AI",
        "ai",
        (period,),
        Decimal(50),
        "NOT_APPLICABLE",
        None,
    )
    return RunCalculationOutput(
        "rs-algorithm-v1",
        (resolved,),
        (stock,),
        (period,),
        (overall,),
        (),
        1,
        0,
        0,
    )


def test_algorithm_bytes_strip_all_run_member_range_and_classification_ids() -> None:
    first = algorithm_canonical_bytes(output("one"))
    second = algorithm_canonical_bytes(output("two"))

    assert first == second
    assert b"range-one" not in first
    assert b"member-one" not in first
    assert b"class-id-is-not-canonical" not in first
    assert first.endswith(b"}")
    assert not first.endswith(b"\n")


def test_algorithm_hash_is_stable_under_global_decimal_context_changes() -> None:
    original = getcontext().copy()
    try:
        getcontext().prec = 5
        first = algorithm_sha256(output("one"))
        getcontext().prec = 50
        second = algorithm_sha256(output("two"))
    finally:
        setcontext(original)

    assert first == second
    assert len(first) == 64


def test_canonical_projection_reapplies_frozen_business_sorting() -> None:
    base = output("one")
    second_stock = replace(
        base.stock_results[0],
        run_member_id="member-second",
        member_ordinal=1,
        symbol="MSFT.US",
    )
    ordered = replace(base, stock_results=(base.stock_results[0], second_stock))
    reversed_output = replace(
        base,
        stock_results=(second_stock, base.stock_results[0]),
    )

    assert algorithm_canonical_bytes(ordered) == algorithm_canonical_bytes(
        reversed_output
    )
