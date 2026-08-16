"""Small shared rules for truthful desktop progress presentation."""

from __future__ import annotations


def monotonic_stage_progress(
    current: float,
    *,
    stage_index: int,
    stage_count: int,
    completed: int,
    total: int,
) -> float:
    """Advance staged progress without regressing or claiming completion early."""
    if stage_count <= 0:
        return max(0.0, min(float(current), 0.995))
    fraction = completed / total if total > 0 else 0.0
    fraction = max(0.0, min(float(fraction), 1.0))
    raw = (max(0, stage_index) + fraction) / stage_count
    return max(0.0, min(max(float(current), raw), 0.995))
