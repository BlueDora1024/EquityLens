from __future__ import annotations

from datetime import date
from decimal import Decimal, getcontext, setcontext

import pytest

from stock_toolbox.analyses.rs_strength.domain.numeric import (
    RS_CONTEXT,
    add_calendar_months,
    add_calendar_year,
    base_weight,
    canonical_decimal,
    normalize_weights,
    validate_close,
)


def test_context_is_the_frozen_34_digit_half_even_context() -> None:
    assert RS_CONTEXT.prec == 34
    assert RS_CONTEXT.rounding == "ROUND_HALF_EVEN"
    assert RS_CONTEXT.Emin == -6143
    assert RS_CONTEXT.Emax == 6144
    assert RS_CONTEXT.capitals == 1
    assert RS_CONTEXT.clamp == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("70.000"), "70"),
        (Decimal("-0.00"), "0"),
        (Decimal("1E+3"), "1000"),
        (Decimal("0.0012300"), "0.00123"),
        (Decimal("-12.3400"), "-12.34"),
    ],
)
def test_decimal_canonical_form(value: Decimal, expected: str) -> None:
    assert canonical_decimal(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal(0),
        Decimal(-1),
        1.5,
        "1.5",
    ],
)
def test_close_rejects_non_decimal_non_finite_and_non_positive_values(
    value: object,
) -> None:
    with pytest.raises(ValueError):
        validate_close(value)


def test_calendar_advancement_clamps_month_end_and_leap_day() -> None:
    assert add_calendar_months(date(2026, 1, 31), 3) == date(2026, 4, 30)
    assert add_calendar_months(date(2024, 11, 30), 3) == date(2025, 2, 28)
    assert add_calendar_year(date(2024, 2, 29)) == date(2025, 2, 28)


@pytest.mark.parametrize(
    ("end", "expected"),
    [
        (date(2026, 4, 29), Decimal("1.00")),
        (date(2026, 4, 30), Decimal("1.00")),
        (date(2026, 5, 1), Decimal("1.15")),
        (date(2026, 7, 31), Decimal("1.15")),
        (date(2026, 8, 1), Decimal("1.30")),
        (date(2027, 1, 31), Decimal("1.30")),
        (date(2027, 2, 1), Decimal("1.45")),
    ],
)
def test_base_weight_uses_requested_calendar_span(
    end: date,
    expected: Decimal,
) -> None:
    assert base_weight(date(2026, 1, 31), end) == expected


def test_invalid_requested_span_is_rejected() -> None:
    with pytest.raises(ValueError):
        base_weight(date(2026, 2, 1), date(2026, 1, 31))


def test_normalized_weights_use_residual_for_final_value() -> None:
    normalized = normalize_weights(
        (Decimal("1.00"), Decimal("1.15"), Decimal("1.30"))
    )

    assert tuple(map(canonical_decimal, normalized)) == (
        "0.2898550724637681159420289855072464",
        "0.3333333333333333333333333333333333",
        "0.3768115942028985507246376811594203",
    )
    assert sum(normalized, Decimal(0)) == Decimal(1)


def test_single_normalized_weight_is_exactly_one() -> None:
    assert normalize_weights((Decimal("1.45"),)) == (Decimal(1),)


def test_numeric_operations_ignore_process_global_decimal_context() -> None:
    original = getcontext().copy()
    try:
        getcontext().prec = 6
        getcontext().rounding = "ROUND_DOWN"
        first = normalize_weights(
            (Decimal("1.00"), Decimal("1.15"), Decimal("1.30"))
        )

        getcontext().prec = 50
        getcontext().rounding = "ROUND_UP"
        second = normalize_weights(
            (Decimal("1.00"), Decimal("1.15"), Decimal("1.30"))
        )
    finally:
        setcontext(original)

    assert first == second
