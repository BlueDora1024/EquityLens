"""Convert persisted instants for display without changing analysis time."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo


def _timezone(name: str) -> tzinfo:
    if name == "system":
        return datetime.now().astimezone().tzinfo or UTC
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        return ZoneInfo("Asia/Shanghai")


def display_datetime(value: object, timezone_name: str) -> str:
    if isinstance(value, str):
        raw = value
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return raw or "—"
    if not isinstance(value, datetime):
        return "—" if value is None else str(value)
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(_timezone(timezone_name)).strftime("%Y-%m-%d %H:%M")
