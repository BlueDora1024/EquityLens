from __future__ import annotations

from types import MappingProxyType

import pytest

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
    DiagnosticStatus,
    NullDiagnosticLogger,
)


def test_event_keeps_ticker_and_copies_bounded_details() -> None:
    source: dict[str, object] = {"planned": 3}

    event = DiagnosticEvent(
        DiagnosticLevel.INFO,
        "rs_strength",
        "fetch_daily",
        DiagnosticStatus.STARTED,
        task_id="run-1",
        ticker="IREN.US",
        details=source,
    )
    source["planned"] = 9

    assert event.ticker == "IREN.US"
    assert event.details == {"planned": 3}
    assert isinstance(event.details, MappingProxyType)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("module", "RS Strength"),
        ("action", ""),
        ("task_id", "\n"),
        ("ticker", "IREN\n.US"),
    ),
)
def test_event_rejects_invalid_identifiers(field: str, value: str) -> None:
    values = {
        "module": "rs_strength",
        "action": "fetch_daily",
        "status": DiagnosticStatus.STARTED,
        "task_id": "run-1",
        "ticker": "IREN.US",
    }
    values[field] = value

    with pytest.raises(ValueError):
        DiagnosticEvent(DiagnosticLevel.INFO, **values)


def test_event_rejects_nested_or_unbounded_values() -> None:
    with pytest.raises(TypeError):
        DiagnosticEvent(
            DiagnosticLevel.INFO,
            "rs_strength",
            "run",
            DiagnosticStatus.STARTED,
            details={"rows": {"secret": "value"}},
        )


def test_null_logger_accepts_events_and_flushes() -> None:
    logger = NullDiagnosticLogger()
    event = DiagnosticEvent(
        DiagnosticLevel.INFO,
        "application",
        "startup",
        DiagnosticStatus.STARTED,
    )

    logger.emit(event)

    assert logger.flush() is True
    assert logger.close() is True
