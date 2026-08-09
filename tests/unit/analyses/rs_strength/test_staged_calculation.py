from __future__ import annotations

from stock_toolbox.analyses.rs_strength.application.models import RunProgress
from stock_toolbox.analyses.rs_strength.application.staged_calculation import (
    calculate_run_staged,
)
from stock_toolbox.analyses.rs_strength.domain.engine import calculate_run
from tests.fixtures.rs_benchmark_v1 import benchmark_input


class Control:
    def __init__(self) -> None:
        self.canceled = False

    def cancellation_requested(self) -> bool:
        return self.canceled

    def try_enter_committing(self) -> bool:
        return not self.canceled


def test_staged_calculation_is_identical_to_canonical_serial_output() -> None:
    calculation_input = benchmark_input()
    progress: list[RunProgress] = []

    actual = calculate_run_staged(
        calculation_input,
        Control(),
        progress.append,
        member_chunk_size=2,
        classification_chunk_size=1,
    )

    assert actual == calculate_run(calculation_input)
    assert {event.stage for event in progress} == {
        "VALIDATING",
        "CALCULATING",
        "AGGREGATING",
    }
    assert all(event.completed <= event.total for event in progress)
    assert progress[-1].completed == progress[-1].total


def test_staged_calculation_stops_between_chunks_when_canceled() -> None:
    calculation_input = benchmark_input()
    control = Control()

    def cancel_after_first_chunk(event: RunProgress) -> None:
        if event.stage == "VALIDATING" and event.completed:
            control.canceled = True

    actual = calculate_run_staged(
        calculation_input,
        control,
        cancel_after_first_chunk,
        member_chunk_size=1,
        classification_chunk_size=1,
    )

    assert actual is None
