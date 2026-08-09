"""Frozen numeric primitives for ``rs-algorithm-v1``."""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import date
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

RS_CONTEXT = Context(
    prec=34,
    rounding=ROUND_HALF_EVEN,
    Emin=-6143,
    Emax=6144,
    capitals=1,
    clamp=0,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)


def local_rs_context() -> AbstractContextManager[Context]:
    """Return an isolated copy of the frozen calculation context."""

    return localcontext(RS_CONTEXT)


def validate_decimal(value: object) -> Decimal:
    """Return a finite Decimal without accepting a float conversion boundary."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("value must be a finite Decimal")
    return value


def validate_close(value: object) -> Decimal:
    """Return a valid ordinary close price."""

    close = validate_decimal(value)
    if close <= 0:
        raise ValueError("close must be greater than zero")
    return close


def canonical_decimal(value: Decimal) -> str:
    """Serialize a finite Decimal in the frozen non-exponent form."""

    finite = validate_decimal(value)
    if finite == 0:
        return "0"
    result = format(finite, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result


def add_calendar_months(value: date, months: int) -> date:
    """Advance a date by whole calendar months, clamping to month end."""

    if months < 0:
        raise ValueError("months must not be negative")
    absolute_month = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(absolute_month, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_calendar_year(value: date) -> date:
    """Advance a date by one calendar year, clamping a leap day."""

    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, month=2, day=28)


def base_weight(requested_start: date, requested_end: date) -> Decimal:
    """Select the frozen base weight from the requested calendar span."""

    if requested_end < requested_start:
        raise ValueError("requested end must not precede start")
    if requested_end <= add_calendar_months(requested_start, 3):
        return Decimal("1.00")
    if requested_end <= add_calendar_months(requested_start, 6):
        return Decimal("1.15")
    if requested_end <= add_calendar_year(requested_start):
        return Decimal("1.30")
    return Decimal("1.45")


def normalize_weights(weights: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Normalize positive weights, assigning the final value as a residual."""

    if not weights:
        raise ValueError("at least one weight is required")
    validated = tuple(validate_decimal(weight) for weight in weights)
    if any(weight <= 0 for weight in validated):
        raise ValueError("weights must be greater than zero")
    if len(validated) == 1:
        return (Decimal(1),)

    with local_rs_context():
        total = sum(validated, Decimal(0))
        normalized = [weight / total for weight in validated[:-1]]
        final = Decimal(1) - sum(normalized, Decimal(0))
        if final <= 0:
            raise ArithmeticError("residual normalized weight is not positive")
        normalized.append(final)
        return tuple(normalized)
