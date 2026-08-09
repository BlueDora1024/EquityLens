from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal, localcontext

import pytest

from stock_toolbox.core.operations.failure_policy import (
    CircuitBreaker,
    FailureCode,
    RunTerminal,
    reliability_summary,
)


def test_breaker_opens_after_eight_consecutive_transport_failures() -> None:
    breaker = CircuitBreaker()
    for _ in range(7):
        assert not breaker.record(FailureCode.NETWORK_ERROR)
    assert breaker.record(FailureCode.NETWORK_ERROR)


def test_breaker_opens_on_sixteenth_same_failure_in_twenty_record_window() -> None:
    breaker = CircuitBreaker()
    records = (
        (FailureCode.TIMEOUT,) * 3
        + (FailureCode.DATA_UNAVAILABLE,)
        + (FailureCode.TIMEOUT,) * 4
        + (FailureCode.DATA_UNAVAILABLE,)
        + (FailureCode.TIMEOUT,) * 4
        + (FailureCode.DATA_UNAVAILABLE,)
        + (FailureCode.TIMEOUT,) * 4
        + (FailureCode.DATA_UNAVAILABLE, FailureCode.TIMEOUT)
    )

    for code in records[:-1]:
        assert not breaker.record(code)
    assert breaker.record(records[-1])


def test_breaker_does_not_combine_different_infrastructure_failures() -> None:
    breaker = CircuitBreaker()
    records = (FailureCode.TIMEOUT, FailureCode.NETWORK_ERROR, FailureCode.DATA_UNAVAILABLE) * 4
    records += (FailureCode.TIMEOUT, FailureCode.NETWORK_ERROR) * 4

    for code in records:
        assert not breaker.record(code)
    assert not breaker.open


def test_breaker_stays_open_after_subsequent_records() -> None:
    breaker = CircuitBreaker()
    for _ in range(8):
        breaker.record(FailureCode.NETWORK_ERROR)

    assert breaker.open
    assert breaker.record(FailureCode.DATA_UNAVAILABLE)


def test_failure_codes_have_stable_wire_values() -> None:
    assert tuple(code.value for code in FailureCode) == (
        "timeout",
        "network_error",
        "service_unavailable",
        "rate_limited",
        "quota_exhausted",
        "authentication_failed",
        "permission_denied",
        "malformed_response",
        "data_unavailable",
        "insufficient_data",
        "database_busy",
        "storage_unavailable",
        "database_corrupt",
        "memory_exhausted",
        "internal",
    )


@pytest.mark.parametrize(
    ("succeeded", "failed", "expected"),
    [(80, 20, "PARTIAL"), (79, 21, "FAILED"), (100, 0, "READY")],
)
def test_reliability_summary_uses_eighty_percent_gate(
    succeeded: int, failed: int, expected: str
) -> None:
    assert reliability_summary(succeeded, failed, 0).terminal.value == expected


def test_unexecuted_tasks_cannot_inflate_success_rate() -> None:
    summary = reliability_summary(80, 0, 20)
    assert summary.success_rate == Decimal("0.8")
    assert summary.terminal is RunTerminal.PARTIAL


def test_reliability_is_conservative_for_zero_total() -> None:
    summary = reliability_summary(0, 0, 0)

    assert summary.success_rate == Decimal(0)
    assert summary.terminal is RunTerminal.FAILED
    assert not summary.should_save


def test_reliability_threshold_is_independent_of_decimal_precision() -> None:
    expected = reliability_summary(79, 20, 0)

    with localcontext() as context:
        context.prec = 2
        summary = reliability_summary(79, 20, 0)

    assert summary.success_rate == expected.success_rate
    assert summary.terminal is RunTerminal.FAILED
    assert not summary.should_save


def test_reliability_summary_is_independent_of_decimal_rounding() -> None:
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_HALF_EVEN
        expected = reliability_summary(79, 20, 0)

    for rounding in (ROUND_DOWN, ROUND_UP):
        with localcontext() as context:
            context.prec = 2
            context.rounding = rounding
            summary = reliability_summary(79, 20, 0)

        assert summary == expected


def test_invalid_input_or_cancellation_prevents_saving() -> None:
    assert not reliability_summary(100, 0, 0, core_input_valid=False).should_save
    assert not reliability_summary(100, 0, 0, canceled=True).should_save


@pytest.mark.parametrize("counts", ((-1, 0, 0), (0, -1, 0), (0, 0, -1)))
def test_reliability_summary_rejects_negative_counts(
    counts: tuple[int, int, int],
) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        reliability_summary(*counts)
