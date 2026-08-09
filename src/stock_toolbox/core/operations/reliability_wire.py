"""Stable JSON payload codec for analysis reliability at worker boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from stock_toolbox.core.operations.failure_policy import AnalysisReliability


def reliability_payload(
    value: AnalysisReliability | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "succeeded_tasks": value.succeeded_tasks,
        "failed_tasks": value.failed_tasks,
        "unexecuted_tasks": value.unexecuted_tasks,
        "success_rate": str(value.success_rate),
        "circuit_opened": value.circuit_opened,
        "primary_failure_code": value.primary_failure_code,
    }


def reliability_from_payload(raw: object) -> AnalysisReliability | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        return AnalysisReliability(
            int(raw["succeeded_tasks"]),
            int(raw["failed_tasks"]),
            int(raw["unexecuted_tasks"]),
            Decimal(str(raw["success_rate"])),
            bool(raw["circuit_opened"]),
            str(raw.get("primary_failure_code") or "") or None,
        )
    except (KeyError, TypeError, ValueError):
        return None

