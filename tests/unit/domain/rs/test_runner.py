import pytest

from stock_toolbox.analyses.rs_strength.domain.engine import calculate_run
from tests.fixtures.rs_benchmark_v1 import benchmark_input, run_benchmark

pytestmark = pytest.mark.fast


def test_canonical_serial_runner_matches_explicit_staged_composition() -> None:
    input = benchmark_input()

    assert calculate_run(input) == run_benchmark(input)
