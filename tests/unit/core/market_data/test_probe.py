from __future__ import annotations

from datetime import date

from stock_toolbox.core.market_data.probe import (
    probe_window,
    resolve_boundaries,
    shift_weekdays,
)


def test_shift_weekdays_skips_saturday_and_sunday() -> None:
    assert shift_weekdays(date(2026, 7, 27), -4) == date(2026, 7, 21)
    assert shift_weekdays(date(2026, 7, 31), 4) == date(2026, 8, 6)


def test_probe_expands_both_sides_and_caps_the_end() -> None:
    probe = probe_window(
        date(2026, 7, 27),
        date(2026, 7, 31),
        cap=date(2026, 8, 3),
    )

    assert probe.requested_start == date(2026, 7, 27)
    assert probe.requested_end == date(2026, 7, 31)
    assert probe.fetch_start == date(2026, 7, 21)
    assert probe.fetch_end == date(2026, 8, 3)


def test_resolve_boundaries_uses_only_dates_inside_the_requested_range() -> None:
    resolved = resolve_boundaries(
        date(2026, 7, 25),
        date(2026, 7, 28),
        available=(
            date(2026, 7, 24),
            date(2026, 7, 27),
            date(2026, 7, 29),
        ),
    )

    assert resolved.requested_start == date(2026, 7, 25)
    assert resolved.requested_end == date(2026, 7, 28)
    assert resolved.actual_start == date(2026, 7, 27)
    assert resolved.actual_end == date(2026, 7, 27)


def test_resolve_boundaries_reports_an_empty_requested_range() -> None:
    resolved = resolve_boundaries(
        date(2026, 7, 25),
        date(2026, 7, 26),
        available=(date(2026, 7, 24), date(2026, 7, 27)),
    )

    assert resolved.actual_start is None
    assert resolved.actual_end is None
