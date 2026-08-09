from __future__ import annotations

import pytest

from stock_toolbox.core.market_data.budget import (
    DEFAULT_COLD_REQUEST_BUDGET,
    RequestBudget,
    estimate_multi_period,
    estimate_rs,
)
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.market_data.request_plan import (
    plan_extreme_requests,
    plan_rs_requests,
    plan_turning_requests,
)


def test_rs_ranges_do_not_multiply_requests() -> None:
    estimate = estimate_rs(member_count=600, range_count=7, cache_hits=100)

    assert estimate.total_tasks == 601
    assert estimate.cold_requests == 501
    assert estimate.over_budget is True


def test_six_period_run_requires_confirmation() -> None:
    estimate = estimate_multi_period(
        member_count=600,
        period_count=6,
        cache_hits=0,
    )

    assert DEFAULT_COLD_REQUEST_BUDGET == 50
    assert estimate == RequestBudget(3_600, 0, 3_600, 50)
    assert estimate.over_budget is True


@pytest.mark.parametrize(
    ("member_count", "range_count", "cache_hits"),
    ((-1, 1, 0), (1, 0, 0), (1, 1, -1), (1, 1, 3)),
)
def test_rs_budget_rejects_impossible_counts(
    member_count: int,
    range_count: int,
    cache_hits: int,
) -> None:
    with pytest.raises(ValueError, match="budget"):
        estimate_rs(
            member_count=member_count,
            range_count=range_count,
            cache_hits=cache_hits,
        )


def test_multi_period_budget_includes_explicit_extra_requests() -> None:
    estimate = estimate_multi_period(
        member_count=600,
        period_count=3,
        cache_hits=800,
        extra_requests=6,
    )

    assert estimate.total_tasks == 1_806
    assert estimate.cold_requests == 1_006


def test_longbridge_turning_plan_counts_220_bar_pagination() -> None:
    plan = plan_turning_requests(
        "longbridge",
        member_count=600,
        intervals=(
            CandleInterval.MIN_30,
            CandleInterval.MIN_60,
            CandleInterval.MIN_120,
            CandleInterval.MIN_240,
            CandleInterval.DAY,
            CandleInterval.WEEK,
        ),
        quant_cache_hits=0,
    )

    assert plan.calculation_calls == 4_800
    assert plan.annotation_calls == 6
    assert plan.quota_checks == 0
    assert plan.provider_calls == 4_806
    assert plan.page_size == 200
    assert plan.requires_confirmation is True


def test_extreme_plan_counts_each_650_bar_longbridge_page() -> None:
    plan = plan_extreme_requests(
        "longbridge",
        member_count=1,
        intervals=(
            CandleInterval.MIN_30,
            CandleInterval.MIN_60,
            CandleInterval.DAY,
            CandleInterval.WEEK,
        ),
        cache_hits=0,
    )

    assert plan.calculation_calls == 16
    assert plan.provider_calls == 16
    assert plan.requires_confirmation is False


def test_futu_plan_exposes_serial_minimum_duration_and_quota_probe() -> None:
    plan = plan_turning_requests(
        "futu",
        member_count=600,
        intervals=(CandleInterval.MIN_30, CandleInterval.MIN_60),
        quant_cache_hits=0,
    )

    assert plan.calculation_calls == 1_200
    assert plan.annotation_calls == 2
    assert plan.quota_checks == 1
    assert plan.provider_calls == 1_203
    assert plan.minimum_seconds == 600.0
    assert plan.requires_confirmation is True


def test_yahoo_hourly_family_is_one_physical_batch() -> None:
    turning = plan_turning_requests(
        "yahoo",
        member_count=600,
        intervals=(
            CandleInterval.MIN_60,
            CandleInterval.MIN_120,
            CandleInterval.MIN_240,
        ),
        quant_cache_hits=0,
    )
    rs = plan_rs_requests("yahoo", member_count=600, cache_hits=0)

    assert turning.provider_calls == 1
    assert rs.provider_calls == 2
