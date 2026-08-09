"""Shared historical-date rules for every desktop analysis."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo

from stock_toolbox.core.market_data.probe import shift_weekdays

MAX_BOUNDARY_BUFFER_WEEKDAYS = 4


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _timezone(name: str) -> tzinfo:
    if name == "system":
        return datetime.now().astimezone().tzinfo or UTC
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        return ZoneInfo("Asia/Shanghai")


def display_today(
    timezone_name: str,
    instant: datetime | None = None,
) -> date:
    value = instant or datetime.now(UTC)
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(_timezone(timezone_name)).date()


def maximum_historical_date(
    timezone_name: str,
    instant: datetime | None = None,
) -> date:
    return display_today(timezone_name, instant) - timedelta(days=1)


def validate_historical_date(selected: date, today: date) -> bool:
    return selected < today


def boundary_within_buffer(
    requested: date,
    actual: date,
    *,
    side: Literal["start", "end"],
) -> bool:
    if side == "start":
        return requested <= actual <= shift_weekdays(
            requested,
            MAX_BOUNDARY_BUFFER_WEEKDAYS,
        )
    return shift_weekdays(
        requested,
        -MAX_BOUNDARY_BUFFER_WEEKDAYS,
    ) <= actual <= requested
