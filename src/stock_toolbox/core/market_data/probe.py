"""Small date probes for markets where a complete holiday calendar is unavailable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class DateProbeWindow:
    requested_start: date
    requested_end: date
    fetch_start: date
    fetch_end: date


@dataclass(frozen=True, slots=True)
class ResolvedDateBoundaries:
    requested_start: date
    requested_end: date
    actual_start: date | None
    actual_end: date | None


def shift_weekdays(value: date, amount: int) -> date:
    step = 1 if amount >= 0 else -1
    remaining = abs(amount)
    current = value
    while remaining:
        current += timedelta(days=step)
        if current.weekday() < 5:
            remaining -= 1
    return current


def probe_window(
    start: date,
    end: date,
    *,
    cap: date,
) -> DateProbeWindow:
    if start > end:
        raise ValueError("probe start must not exceed end")
    return DateProbeWindow(
        requested_start=start,
        requested_end=end,
        fetch_start=shift_weekdays(start, -4),
        fetch_end=min(shift_weekdays(end, 4), cap),
    )


def resolve_boundaries(
    start: date,
    end: date,
    *,
    available: tuple[date, ...],
) -> ResolvedDateBoundaries:
    within = tuple(value for value in available if start <= value <= end)
    return ResolvedDateBoundaries(
        requested_start=start,
        requested_end=end,
        actual_start=within[0] if within else None,
        actual_end=within[-1] if within else None,
    )
