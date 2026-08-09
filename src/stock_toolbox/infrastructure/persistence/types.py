"""Strict SQLite boundary conversions."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from stock_toolbox.analyses.rs_strength.domain.numeric import canonical_decimal
from stock_toolbox.infrastructure.persistence.errors import PersistenceDataError


def canonical_instant(value: datetime) -> str:
    """Convert an aware instant to the exact persisted UTC representation."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PersistenceDataError("Instant must include a timezone")
    try:
        utc_value = value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (OverflowError, ValueError) as error:
        raise PersistenceDataError("Instant is invalid") from error


def parse_canonical_instant(value: object) -> datetime:
    """Parse only the exact 27-byte UTC instant form."""

    if (
        not isinstance(value, str)
        or len(value) != 27
        or value[10] != "T"
        or value[19] != "."
        or value[26] != "Z"
    ):
        raise PersistenceDataError("Stored instant is not canonical")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=UTC
        )
    except ValueError as error:
        raise PersistenceDataError("Stored instant is invalid") from error
    if canonical_instant(parsed) != value:
        raise PersistenceDataError("Stored instant is not canonical")
    return parsed


def canonical_date(value: date) -> str:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise PersistenceDataError("Date value is invalid")
    return value.isoformat()


def parse_canonical_date(value: object) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise PersistenceDataError("Stored date is not canonical")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise PersistenceDataError("Stored date is invalid") from error
    if parsed.isoformat() != value:
        raise PersistenceDataError("Stored date is not canonical")
    return parsed


def canonical_decimal_text(value: Decimal) -> str:
    try:
        return canonical_decimal(value)
    except (TypeError, ValueError) as error:
        raise PersistenceDataError("Decimal value is invalid") from error


def parse_canonical_decimal(value: object) -> Decimal:
    if not isinstance(value, str):
        raise PersistenceDataError("Stored Decimal must be text")
    try:
        parsed = Decimal(value)
        canonical = canonical_decimal(parsed)
    except (ArithmeticError, ValueError) as error:
        raise PersistenceDataError("Stored Decimal is invalid") from error
    if value != canonical:
        raise PersistenceDataError("Stored Decimal is not canonical")
    return parsed


def parse_uuid4(value: object) -> UUID:
    if not isinstance(value, str) or len(value) != 36:
        raise PersistenceDataError("Stored ID is not a canonical UUID4")
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError) as error:
        raise PersistenceDataError("Stored ID is invalid") from error
    if parsed.version != 4 or str(parsed) != value:
        raise PersistenceDataError("Stored ID is not a canonical UUID4")
    return parsed


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise PersistenceDataError("JSON value is invalid") from error


def parse_canonical_json(value: object) -> Any:
    if not isinstance(value, str):
        raise PersistenceDataError("Stored JSON must be text")
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, RecursionError) as error:
        raise PersistenceDataError("Stored JSON is invalid") from error
    if canonical_json(parsed) != value:
        raise PersistenceDataError("Stored JSON is not canonical")
    return parsed


def parse_enum[EnumT: Enum](enum_type: type[EnumT], value: object) -> EnumT:
    if not isinstance(value, str):
        raise PersistenceDataError("Stored enum must be text")
    try:
        return enum_type(value)
    except ValueError as error:
        raise PersistenceDataError("Stored enum value is unknown") from error
