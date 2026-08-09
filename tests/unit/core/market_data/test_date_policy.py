from __future__ import annotations

from datetime import UTC, date, datetime

from stock_toolbox.core.market_data.date_policy import (
    MAX_BOUNDARY_BUFFER_WEEKDAYS,
    boundary_within_buffer,
    display_today,
    maximum_historical_date,
    parse_iso_date,
    validate_historical_date,
)


def test_parse_iso_date_rejects_invalid_values_without_raising() -> None:
    assert parse_iso_date("2026-07-24") == date(2026, 7, 24)
    assert parse_iso_date("not-a-date") is None


def test_display_today_uses_selected_timezone() -> None:
    instant = datetime(2026, 7, 29, 17, 0, tzinfo=UTC)

    assert display_today("Asia/Shanghai", instant) == date(2026, 7, 30)
    assert display_today("America/New_York", instant) == date(2026, 7, 29)
    assert maximum_historical_date("Asia/Shanghai", instant) == date(2026, 7, 29)


def test_historical_date_must_be_strictly_before_today() -> None:
    today = date(2026, 7, 30)

    assert validate_historical_date(date(2026, 7, 29), today)
    assert not validate_historical_date(today, today)
    assert not validate_historical_date(date(2026, 7, 31), today)


def test_boundary_buffer_accepts_at_most_four_workdays_inward() -> None:
    requested = date(2026, 7, 20)

    assert MAX_BOUNDARY_BUFFER_WEEKDAYS == 4
    assert boundary_within_buffer(
        requested,
        date(2026, 7, 24),
        side="start",
    )
    assert not boundary_within_buffer(
        requested,
        date(2026, 7, 27),
        side="start",
    )
    assert boundary_within_buffer(
        requested,
        date(2026, 7, 14),
        side="end",
    )
    assert not boundary_within_buffer(
        requested,
        date(2026, 7, 13),
        side="end",
    )
