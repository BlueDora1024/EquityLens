from __future__ import annotations

from datetime import UTC, datetime

from stock_toolbox.desktop_qml.time_display import display_datetime


def test_displays_utc_timestamp_in_beijing_time() -> None:
    value = datetime(2026, 7, 30, 1, 15, tzinfo=UTC)

    assert display_datetime(value, "Asia/Shanghai") == "2026-07-30 09:15"
    assert (
        display_datetime("2026-07-30T01:15:00Z", "Asia/Shanghai")
        == "2026-07-30 09:15"
    )


def test_keeps_non_datetime_values_safe() -> None:
    assert display_datetime(None, "Asia/Shanghai") == "—"
