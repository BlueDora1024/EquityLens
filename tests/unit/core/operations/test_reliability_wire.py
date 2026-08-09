from __future__ import annotations

from decimal import Decimal

from stock_toolbox.core.operations.failure_policy import AnalysisReliability
from stock_toolbox.core.operations.reliability_wire import (
    reliability_from_payload,
    reliability_payload,
)


def test_reliability_wire_round_trip_preserves_primary_failure() -> None:
    source = AnalysisReliability(
        0,
        372,
        0,
        Decimal(0),
        False,
        "quota_exhausted",
    )

    assert reliability_from_payload(reliability_payload(source)) == source


def test_reliability_wire_rejects_incomplete_payload() -> None:
    assert reliability_from_payload({"failed_tasks": 1}) is None

