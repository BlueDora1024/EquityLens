from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from stock_toolbox.core.market_data.models import DailySeriesProgress
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.core.operations.registry import (
    OperationControl,
    OperationRegistry,
)
from stock_toolbox.core.securities.models import StoredClassification
from stock_toolbox.infrastructure.virtual.ai import VirtualAI
from stock_toolbox.infrastructure.virtual.provider import (
    VirtualProvider,
    VirtualProviderFault,
)


def control() -> OperationControl:
    registry = OperationRegistry(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC)
    )
    registry.reserve("op-1", "key", "test")
    context = registry.begin_reserved("op-1")
    assert context is not None
    return context.operation_control


def test_virtual_profiles_cover_common_ambiguous_excluded_and_missing() -> None:
    provider = VirtualProvider()

    result = provider.get_security_profiles(
        ("NVDA.US", "IREN.US", "TQQQ.US", "MISSING.US"),
        operation_control=control(),
    )

    by_symbol = {item.symbol: item for item in result.profiles}
    assert by_symbol["NVDA.US"].asset_hints[0].normalized_type == "COMMON_STOCK"
    assert by_symbol["IREN.US"].asset_hints[0].reliability == "ambiguous"
    assert by_symbol["TQQQ.US"].asset_hints[0].normalized_type == "LEVERAGED_ETF"
    assert result.errors[0].symbol == "MISSING.US"
    assert provider.external_call_count == 4


def test_virtual_bars_are_deterministic_sorted_and_single_logical_result() -> None:
    provider = VirtualProvider()

    first = provider.get_daily_series(
        ("SPY.US", "NVDA.US"),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=control(),
    )
    second = provider.get_daily_series(
        ("SPY.US", "NVDA.US"),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=control(),
    )

    assert first == second
    assert len(first.series_by_symbol["SPY.US"].points) > 140
    assert first.series_by_symbol["SPY.US"].points[0].date < first.series_by_symbol["SPY.US"].points[-1].date
    assert all(
        point.close > Decimal(0)
        for series in first.series_by_symbol.values()
        for point in series.points
    )
    assert provider.external_call_count == 4


def test_virtual_provider_does_not_advertise_retired_250d_quant() -> None:
    assert "turning-risk-250d-v1" not in VirtualProvider.quant_script_versions


def test_scattered_rate_limits_do_not_open_one_run_circuit() -> None:
    provider = VirtualProvider(
        fault_plan=(
            VirtualProviderFault(
                "daily",
                ("rate_limited", "ok"),
                "AAPL.US",
            ),
            VirtualProviderFault(
                "daily",
                ("rate_limited",),
                "AMD.US",
            ),
        )
    )

    run_control = control()
    recovered = provider.get_daily_series(
        ("AAPL.US",),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=run_control,
    )
    stopped = provider.get_daily_series(
        ("AMD.US",),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=run_control,
    )
    skipped = provider.get_daily_series(
        ("NVDA.US",),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=run_control,
    )
    next_run = provider.get_daily_series(
        ("NVDA.US",),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=control(),
    )

    assert "AAPL.US" in recovered.series_by_symbol
    assert "AMD.US" in stopped.series_by_symbol
    assert "NVDA.US" in skipped.series_by_symbol
    assert provider.attempted_symbols == (
        "AAPL.US",
        "AAPL.US",
        "AMD.US",
        "AMD.US",
        "NVDA.US",
        "NVDA.US",
    )
    assert provider.unexecuted_symbols == ()
    assert "NVDA.US" in next_run.series_by_symbol
    assert provider.external_call_count == 6


@pytest.mark.parametrize(
    ("events", "failure_code"),
    (
        (
            ("authentication_failed",),
            FailureCode.AUTHENTICATION_FAILED,
        ),
        (
            ("quota_exhausted",),
            FailureCode.QUOTA_EXHAUSTED,
        ),
    ),
)
def test_circuit_open_feedback_keeps_the_triggering_failure(
    events: tuple[str, ...],
    failure_code: FailureCode,
) -> None:
    provider = VirtualProvider(
        fault_plan=(
            VirtualProviderFault("daily", events, "AAPL.US"),
        )
    )
    progress: list[DailySeriesProgress] = []

    provider.get_daily_series(
        ("AAPL.US", "AMD.US"),
        date(2026, 1, 1),
        date(2026, 7, 24),
        operation_control=control(),
        progress=progress.append,
    )

    assert progress[-1].current_symbol == "AMD.US"
    assert progress[-1].feedback is not None
    assert progress[-1].feedback.failure_code is failure_code


def test_virtual_ai_prefers_existing_global_classification_identity() -> None:
    provider = VirtualProvider()
    profile = provider.get_security_profiles(
        ("IREN.US",),
        operation_control=control(),
    ).profiles[0]
    existing = (
        StoredClassification(
            "existing-ai",
            "AI 数据中心",
            "ai 数据中心",
        ),
    )

    result = VirtualAI().analyze_company(
        profile,
        existing,
        operation_control=control(),
    )

    assert result.eligible
    assert len(result.classifications) <= 3
    assert result.classifications[0].existing_classification_id == "existing-ai"
