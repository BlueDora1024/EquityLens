from __future__ import annotations

import hashlib

from stock_toolbox.analyses.rs_strength.domain.canonical import benchmark_canonical_bytes
from tests.fixtures.rs_benchmark_v1 import benchmark_input, run_benchmark, sessions

EXPECTED_BYTES = 792434
EXPECTED_SHA256 = "6ad2505299e01cc3b78d605982059b2917ea88b30c430d171d3a05fca05386a9"


def canonical_content(*, reverse: bool = False, reverse_chunks: bool = False) -> bytes:
    output = run_benchmark(
        benchmark_input(reverse=reverse),
        member_chunk_size=73 if reverse else 100,
        classification_chunk_size=3 if reverse else 5,
        reverse_chunks=reverse_chunks,
    )
    return benchmark_canonical_bytes(
        output,
        benchmark_version="synthetic-spy-v1",
        session_count=len(sessions()),
        member_count=600,
        classification_count=20,
    )


def test_real_engine_matches_frozen_600_member_golden() -> None:
    content = canonical_content()

    assert len(content) == EXPECTED_BYTES
    assert hashlib.sha256(content).hexdigest() == EXPECTED_SHA256


def test_reversed_inputs_and_chunk_completion_match_same_golden() -> None:
    content = canonical_content(reverse=True, reverse_chunks=True)

    assert len(content) == EXPECTED_BYTES
    assert hashlib.sha256(content).hexdigest() == EXPECTED_SHA256
