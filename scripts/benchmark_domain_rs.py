#!/usr/bin/env python3
"""Measure the frozen in-memory 600-member RS benchmark."""

from __future__ import annotations

import hashlib
import platform
from statistics import median
from time import perf_counter

from stock_toolbox.analyses.rs_strength.domain.canonical import benchmark_canonical_bytes
from tests.fixtures.rs_benchmark_v1 import benchmark_input, run_benchmark

EXPECTED_BYTES = 792434
EXPECTED_SHA256 = "6ad2505299e01cc3b78d605982059b2917ea88b30c430d171d3a05fca05386a9"


def main() -> None:
    input = benchmark_input()
    durations = []
    for _ in range(30):
        started = perf_counter()
        output = run_benchmark(input)
        durations.append(perf_counter() - started)
        content = benchmark_canonical_bytes(
            output,
            benchmark_version="synthetic-spy-v1",
            session_count=252,
            member_count=600,
            classification_count=20,
        )
        if len(content) != EXPECTED_BYTES:
            raise SystemExit("benchmark canonical byte count changed")
        if hashlib.sha256(content).hexdigest() != EXPECTED_SHA256:
            raise SystemExit("benchmark canonical SHA-256 changed")
    print(f"host={platform.platform()} machine={platform.machine()}")
    print(
        "runs=30 "
        f"median_seconds={median(durations):.6f} "
        f"min_seconds={min(durations):.6f} "
        f"max_seconds={max(durations):.6f}"
    )


if __name__ == "__main__":
    main()
