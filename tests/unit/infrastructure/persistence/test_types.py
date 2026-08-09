from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum

import pytest

from stock_toolbox.infrastructure.persistence.errors import PersistenceDataError
from stock_toolbox.infrastructure.persistence.types import (
    canonical_date,
    canonical_decimal_text,
    canonical_instant,
    canonical_json,
    parse_canonical_date,
    parse_canonical_decimal,
    parse_canonical_instant,
    parse_enum,
    parse_uuid4,
)


class ExampleState(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"


def test_instant_writer_normalizes_to_exact_utc_microsecond_form() -> None:
    source = datetime(
        2026,
        7,
        25,
        20,
        30,
        40,
        123456,
        tzinfo=timezone(timedelta(hours=8)),
    )

    assert canonical_instant(source) == "2026-07-25T12:30:40.123456Z"
    assert parse_canonical_instant("2026-07-25T12:30:40.123456Z") == datetime(
        2026,
        7,
        25,
        12,
        30,
        40,
        123456,
        tzinfo=UTC,
    )


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-25T12:30:40Z",
        "2026-07-25T12:30:40.12345Z",
        "2026-07-25T12:30:40.123456+00:00",
        "2026-07-25 12:30:40.123456Z",
        "2026-02-30T12:30:40.123456Z",
    ],
)
def test_instant_reader_rejects_noncanonical_or_invalid_text(value: str) -> None:
    with pytest.raises(PersistenceDataError):
        parse_canonical_instant(value)


def test_naive_instant_is_rejected() -> None:
    with pytest.raises(PersistenceDataError):
        canonical_instant(datetime(2026, 7, 25, 12, 30))  # noqa: DTZ001


def test_date_and_decimal_roundtrip_require_canonical_text() -> None:
    assert canonical_date(date(2026, 7, 25)) == "2026-07-25"
    assert parse_canonical_date("2026-07-25") == date(2026, 7, 25)
    assert canonical_decimal_text(Decimal("70.000")) == "70"
    assert parse_canonical_decimal("-0.125") == Decimal("-0.125")

    for invalid in ("2026-7-25", "2026-02-30"):
        with pytest.raises(PersistenceDataError):
            parse_canonical_date(invalid)
    for invalid in ("70.0", "1E+2", "NaN", "Infinity", "-0"):
        with pytest.raises(PersistenceDataError):
            parse_canonical_decimal(invalid)


def test_uuid4_parser_requires_canonical_lowercase_uuid4() -> None:
    value = "00000000-0000-4000-8000-000000000001"
    assert str(parse_uuid4(value)) == value

    for invalid in (
        "00000000-0000-3000-8000-000000000001",
        "00000000-0000-4000-8000-00000000000A",
        "not-a-uuid",
    ):
        with pytest.raises(PersistenceDataError):
            parse_uuid4(invalid)


def test_canonical_json_has_sorted_compact_keys_and_rejects_nan() -> None:
    assert canonical_json({"z": 1, "a": ["中", True]}) == (
        '{"a":["中",true],"z":1}'
    )

    with pytest.raises(PersistenceDataError):
        canonical_json({"bad": float("nan")})


def test_enum_parser_and_corrupt_json_use_stable_data_error() -> None:
    assert parse_enum(ExampleState, "READY") is ExampleState.READY
    with pytest.raises(PersistenceDataError) as enum_error:
        parse_enum(ExampleState, "UNKNOWN")
    assert enum_error.value.code == "persistence_data_error"

    with pytest.raises(PersistenceDataError):
        canonical_json(json.loads('{"value": 1e999}'))
