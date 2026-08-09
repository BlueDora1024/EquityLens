"""Matched-only market-value annotations for turning-point results."""

from __future__ import annotations

SMALL_MARKET_VALUE_USD = 2_000_000_000


def build_risk_annotation(
    market_value_usd: int | None,
) -> tuple[str, ...]:
    if market_value_usd is None:
        return ("MARKET_VALUE_UNKNOWN",)
    if market_value_usd < SMALL_MARKET_VALUE_USD:
        return ("SMALL_MARKET_CAP",)
    return ()
