from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stock_toolbox.analyses.rs_strength.domain.models import (
    ALGORITHM_VERSION,
    CalculationFailureDraft,
    CalculationMember,
    MemberDataIssue,
    PricePoint,
    PriceSeries,
    RequestedRange,
    RunCalculationInput,
)


def point(day: int, close: str = "100") -> PricePoint:
    return PricePoint(date(2026, 1, day), Decimal(close))


def requested_range() -> RequestedRange:
    return RequestedRange(
        run_range_id="00000000-0000-4000-8000-000000000001",
        key="3M",
        label="近 3 个月",
        kind="PRESET_3M",
        ordinal=0,
        requested_start_date=date(2026, 1, 2),
        requested_end_date=date(2026, 4, 2),
    )


def member() -> CalculationMember:
    return CalculationMember(
        run_member_id="10000000-0000-4000-8000-000000000001",
        ordinal=0,
        symbol="AAPL.US",
        classification_snapshot_key="AI",
        classification_name="AI 基础设施",
        classification_normalized_name="ai-infrastructure",
    )


def test_price_series_copies_points_to_an_immutable_tuple() -> None:
    source = [point(2), point(3)]
    series = PriceSeries("AAPL.US", source)
    source.append(point(4))

    assert isinstance(series.points, tuple)
    assert tuple(item.date.day for item in series.points) == (2, 3)


def test_run_input_copies_and_freezes_the_series_mapping() -> None:
    benchmark = PriceSeries("SPY.US", [point(2), point(3, "101")])
    stock = PriceSeries("AAPL.US", [point(2), point(3, "102")])
    source = {"SPY.US": benchmark, "AAPL.US": stock}
    calculation = RunCalculationInput(
        algorithm_version=ALGORITHM_VERSION,
        benchmark_symbol="SPY.US",
        requested_ranges=(requested_range(),),
        members=(member(),),
        series_by_symbol=source,
        member_data_issues=(),
    )

    source.clear()

    assert tuple(calculation.series_by_symbol) == ("AAPL.US", "SPY.US")
    assert calculation.series_by_symbol["SPY.US"] is benchmark
    with pytest.raises(TypeError):
        calculation.series_by_symbol["MSFT.US"] = stock  # type: ignore[index]


@pytest.mark.parametrize(
    "replacement",
    [
        {"key": ""},
        {"label": ""},
        {"kind": "UNKNOWN"},
        {"ordinal": -1},
        {
            "requested_start_date": date(2026, 4, 3),
            "requested_end_date": date(2026, 4, 2),
        },
    ],
)
def test_requested_range_rejects_invalid_boundary_values(
    replacement: dict[str, object],
) -> None:
    values = {
        "run_range_id": "range-1",
        "key": "3M",
        "label": "近 3 个月",
        "kind": "PRESET_3M",
        "ordinal": 0,
        "requested_start_date": date(2026, 1, 2),
        "requested_end_date": date(2026, 4, 2),
    }
    values.update(replacement)

    with pytest.raises(ValueError):
        RequestedRange(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_member_id", ""),
        ("ordinal", -1),
        ("symbol", ""),
        ("classification_snapshot_key", ""),
        ("classification_name", ""),
        ("classification_normalized_name", ""),
    ],
)
def test_calculation_member_rejects_blank_identity_and_negative_ordinal(
    field: str,
    value: object,
) -> None:
    values = {
        "run_member_id": "member-1",
        "ordinal": 0,
        "symbol": "AAPL.US",
        "classification_snapshot_key": "AI",
        "classification_name": "AI",
        "classification_normalized_name": "ai",
    }
    values[field] = value

    with pytest.raises(ValueError):
        CalculationMember(**values)  # type: ignore[arg-type]


def test_issue_and_failure_parameters_are_sorted_copied_and_bounded() -> None:
    original = [["z", "last"], ["a", "first"]]
    issue = MemberDataIssue(
        member_ordinal=0,
        symbol="AAPL.US",
        stage="FETCH",
        code="TIMEOUT",
        reason_parameters=original,
    )
    original[0][1] = "changed"

    assert issue.reason_parameters == (("a", "first"), ("z", "last"))

    with pytest.raises(ValueError):
        CalculationFailureDraft(
            scope="MEMBER",
            member_ordinal=0,
            symbol="AAPL.US",
            range_key=None,
            range_ordinal=None,
            stage="FETCH",
            code="TIMEOUT",
            reason_parameters=(("same", "1"), ("same", "2")),
            fatal=False,
        )


def test_member_range_failure_requires_range_identity() -> None:
    with pytest.raises(ValueError):
        CalculationFailureDraft(
            scope="MEMBER_RANGE",
            member_ordinal=0,
            symbol="AAPL.US",
            range_key=None,
            range_ordinal=None,
            stage="CALCULATE",
            code="MISSING_COMMON_END_CLOSE",
            reason_parameters=(),
            fatal=False,
        )
