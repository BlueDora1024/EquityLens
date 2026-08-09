"""Provider-independent request estimates for analysis preflight."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_COLD_REQUEST_BUDGET = 50


@dataclass(frozen=True, slots=True)
class RequestBudget:
    total_tasks: int
    cache_hits: int
    cold_requests: int
    cold_limit: int = DEFAULT_COLD_REQUEST_BUDGET

    def __post_init__(self) -> None:
        if (
            self.total_tasks < 0
            or not 0 <= self.cache_hits <= self.total_tasks
            or self.cold_requests != self.total_tasks - self.cache_hits
            or self.cold_limit < 1
        ):
            raise ValueError("invalid request budget")

    @property
    def over_budget(self) -> bool:
        return self.cold_requests > self.cold_limit


def estimate_rs(
    *,
    member_count: int,
    range_count: int,
    cache_hits: int,
    cold_limit: int = DEFAULT_COLD_REQUEST_BUDGET,
) -> RequestBudget:
    """Estimate one envelope per member plus one benchmark."""

    total = member_count + 1
    if member_count < 0 or range_count < 1 or not 0 <= cache_hits <= total:
        raise ValueError("invalid RS budget input")
    return RequestBudget(total, cache_hits, total - cache_hits, cold_limit)


def estimate_multi_period(
    *,
    member_count: int,
    period_count: int,
    cache_hits: int,
    extra_requests: int = 0,
    cold_limit: int = DEFAULT_COLD_REQUEST_BUDGET,
) -> RequestBudget:
    """Estimate one provider task per member and candle period."""

    if member_count < 0 or period_count < 1 or extra_requests < 0:
        raise ValueError("invalid multi-period budget input")
    total = member_count * period_count + extra_requests
    if not 0 <= cache_hits <= total:
        raise ValueError("invalid multi-period budget input")
    return RequestBudget(total, cache_hits, total - cache_hits, cold_limit)
