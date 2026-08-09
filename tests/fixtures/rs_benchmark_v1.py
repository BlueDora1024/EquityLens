"""Compatibility exports for the packaged frozen RS benchmark builder."""

from stock_toolbox.devtools.rs_benchmark import (
    benchmark_input,
    run_benchmark,
    sessions,
)

__all__ = ["benchmark_input", "run_benchmark", "sessions"]
