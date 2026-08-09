"""Formula primitives matching common Chinese chart-language semantics."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from itertools import pairwise
from typing import Literal

MAX_PRESSURE_RATIO = 1_000_000.0
MIN_DENOMINATOR = 1e-12


def ema(values: Sequence[float], span: int) -> tuple[float, ...]:
    if span <= 0:
        raise ValueError("EMA span must be positive")
    if not values:
        return ()
    alpha = 2.0 / (span + 1.0)
    previous = float(values[0])
    output = [previous]
    for value in values[1:]:
        previous = alpha * float(value) + (1.0 - alpha) * previous
        output.append(previous)
    return tuple(output)


def ema_optional(
    values: Sequence[float | None],
    span: int,
) -> tuple[float | None, ...]:
    if span <= 0:
        raise ValueError("EMA span must be positive")
    alpha = 2.0 / (span + 1.0)
    previous: float | None = None
    output: list[float | None] = []
    for value in values:
        if value is None:
            output.append(None)
            continue
        previous = (
            float(value) if previous is None else alpha * float(value) + (1.0 - alpha) * previous
        )
        output.append(previous)
    return tuple(output)


def cn_sma(
    values: Sequence[float],
    n: int,
    m: int,
) -> tuple[float, ...]:
    if n <= 0 or not 0 < m <= n:
        raise ValueError("SMA requires n > 0 and 0 < m <= n")
    if not values:
        return ()
    previous = float(values[0])
    output = [previous]
    for value in values[1:]:
        previous = (m * float(value) + (n - m) * previous) / n
        output.append(previous)
    return tuple(output)


def rolling_max(
    values: Sequence[float],
    window: int,
) -> tuple[float | None, ...]:
    return _rolling_extreme(values, window, largest=True)


def rolling_min(
    values: Sequence[float],
    window: int,
) -> tuple[float | None, ...]:
    return _rolling_extreme(values, window, largest=False)


def rolling_optional_max(
    values: Sequence[float | None],
    window: int,
) -> tuple[float | None, ...]:
    if window <= 0:
        raise ValueError("rolling window must be positive")
    output: list[float | None] = []
    for index in range(len(values)):
        current = values[max(0, index - window + 1) : index + 1]
        output.append(
            None if any(value is None for value in current) else max(current)  # type: ignore[type-var]
        )
    return tuple(output)


def directional_pressure(
    values: Sequence[float],
    side: Literal["buy", "sell"],
) -> tuple[float, ...]:
    """Return the original buy ratio or its corrected mathematical mirror."""

    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if not values:
        return ()
    absolute_moves = [0.0]
    denominator_moves = [0.0]
    for previous, current in pairwise(values):
        change = float(current) - float(previous)
        absolute_moves.append(abs(change))
        # Both original formulas divide by the smoothed positive movement of
        # the observed low/high series.  The side changes the input series,
        # not the sign of its denominator.
        denominator_moves.append(max(change, 0.0))
    numerator = cn_sma(absolute_moves, 3, 1)
    denominator = cn_sma(denominator_moves, 3, 1)
    output: list[float] = []
    for top, bottom in zip(numerator, denominator, strict=True):
        if top == 0.0 and bottom == 0.0:
            output.append(0.0)
            continue
        output.append(min(MAX_PRESSURE_RATIO, top / max(bottom, MIN_DENOMINATOR) * 100.0))
    return tuple(output)


def _rolling_extreme(
    values: Sequence[float],
    window: int,
    *,
    largest: bool,
) -> tuple[float | None, ...]:
    if window <= 0:
        raise ValueError("rolling window must be positive")
    queue: deque[int] = deque()
    output: list[float | None] = []
    for index, raw in enumerate(values):
        value = float(raw)
        while queue and queue[0] <= index - window:
            queue.popleft()
        while queue and (
            float(values[queue[-1]]) <= value if largest else float(values[queue[-1]]) >= value
        ):
            queue.pop()
        queue.append(index)
        # Chinese chart formulas evaluate HHV/LLV against all available bars
        # while a newly listed security has not filled the requested window.
        output.append(float(values[queue[0]]))
    return tuple(output)
