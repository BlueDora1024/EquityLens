"""Normalize raw pressure against the same symbol and interval history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import log

from stock_toolbox.analyses.extreme_deviation.domain.models import IndicatorPoint
from stock_toolbox.core.market_data.models import CandleInterval


class Confidence(StrEnum):
    FULL = "FULL"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"


class PeriodDirection(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"
    CONFLICT = "CONFLICT"


_STRUCTURAL_DEVIATION_FLOORS = {
    CandleInterval.MIN_30: 0.025,
    CandleInterval.MIN_60: 0.03,
    CandleInterval.DAY: 0.04,
    CandleInterval.WEEK: 0.05,
}
_STRUCTURAL_DEVIATION_GAIN = 17.0
_MIN_SCORE_HISTORY = 30
_FULL_CONFIDENCE_HISTORY = 100


@dataclass(frozen=True, slots=True)
class PeriodScore:
    interval: CandleInterval
    score: int | None
    label: str
    direction: PeriodDirection
    confidence: Confidence
    buy_severity: int
    sell_severity: int
    buy_percentile: float
    sell_percentile: float
    range_position: float
    latest_at: datetime | None
    buy_deviation: float = 0.0
    sell_deviation: float = 0.0
    buy_trigger_age: int | None = None
    sell_trigger_age: int | None = None
    attention_score: int = 0


def label_for_score(score: int) -> str:
    if not -100 <= score <= 100:
        raise ValueError("score must be between -100 and 100")
    if score <= -80:
        return "超级买入观察"
    if score <= -60:
        return "买入观察"
    if score <= -30:
        return "偏买入"
    if score <= 29:
        return "中性"
    if score <= 59:
        return "偏卖出"
    if score <= 79:
        return "卖出观察"
    return "超级卖出观察"


def score_latest(
    interval: CandleInterval,
    candle_count: int,
    points: tuple[IndicatorPoint, ...],
) -> PeriodScore:
    if candle_count < _MIN_SCORE_HISTORY or len(points) < _MIN_SCORE_HISTORY:
        return PeriodScore(
            interval,
            None,
            "数据不足",
            PeriodDirection.NEUTRAL,
            Confidence.INSUFFICIENT,
            0,
            0,
            0.0,
            0.0,
            points[-1].range_position if points else 0.5,
            points[-1].timestamp if points else None,
        )
    confidence = (
        Confidence.FULL
        if candle_count >= _FULL_CONFIDENCE_HISTORY
        else Confidence.LOW
    )
    history = points[-100:]
    current = history[-1]
    buy_percentile = _percentile(tuple(item.buy_raw for item in history), current.buy_raw)
    sell_percentile = _percentile(tuple(item.sell_raw for item in history), current.sell_raw)
    buy_severity = _severity(
        current.buy_raw,
        buy_percentile,
        (1.0 - current.range_position) * 100.0,
        current.buy_deviation,
        current.buy_trigger_age,
        _STRUCTURAL_DEVIATION_FLOORS[interval],
    )
    sell_severity = _severity(
        current.sell_raw,
        sell_percentile,
        current.range_position * 100.0,
        current.sell_deviation,
        current.sell_trigger_age,
        _STRUCTURAL_DEVIATION_FLOORS[interval],
    )
    if confidence is Confidence.LOW:
        buy_severity = min(79, buy_severity)
        sell_severity = min(79, sell_severity)

    if buy_severity >= 60 and sell_severity >= 60:
        score = 0
        direction = PeriodDirection.CONFLICT
        label = "周期内冲突"
    elif buy_severity > sell_severity and buy_severity >= 30:
        score = -buy_severity
        direction = PeriodDirection.BUY
        label = label_for_score(score)
    elif sell_severity > buy_severity and sell_severity >= 30:
        score = sell_severity
        direction = PeriodDirection.SELL
        label = label_for_score(score)
    else:
        difference = sell_severity - buy_severity
        score = max(-29, min(29, difference))
        direction = PeriodDirection.NEUTRAL
        label = "中性"

    return PeriodScore(
        interval,
        score,
        label,
        direction,
        confidence,
        buy_severity,
        sell_severity,
        buy_percentile,
        sell_percentile,
        current.range_position,
        current.timestamp,
        current.buy_deviation,
        current.sell_deviation,
        current.buy_trigger_age,
        current.sell_trigger_age,
        max(buy_severity, sell_severity),
    )


def score_series(
    interval: CandleInterval,
    candle_count: int,
    points: tuple[IndicatorPoint, ...],
    *,
    retain_last: int = 100,
) -> tuple[PeriodScore, ...]:
    """Return frozen normalized scores for the latest visible chart window."""
    if retain_last < 1 or len(points) < _MIN_SCORE_HISTORY:
        return ()
    first_index = max(_MIN_SCORE_HISTORY - 1, len(points) - retain_last)
    return tuple(
        score_latest(
            interval,
            min(candle_count, index + 1),
            points[max(0, index - 99) : index + 1],
        )
        for index in range(first_index, len(points))
    )


def pressure_contrast_series(
    buy_pressure: tuple[float, ...],
    sell_pressure: tuple[float, ...],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Map original pressure to a calm baseline with prominent outliers.

    This is presentation-only: signal timestamps and saved raw pressure stay
    untouched.  Each side is normalized independently so buy and sell pulses
    remain visible even when their numeric ranges differ substantially.
    """
    if len(buy_pressure) != len(sell_pressure):
        raise ValueError("pressure series must be aligned")
    return (
        _pressure_side_contrast(buy_pressure),
        _pressure_side_contrast(sell_pressure),
    )


def _pressure_side_contrast(values: tuple[float, ...]) -> tuple[int, ...]:
    positives = tuple(value for value in values if value > 0.0)
    if not positives:
        return tuple(0 for _ in values)
    baseline = 0.0 if len(positives) == 1 else _float_median(positives)
    dead_zone = max(1e-12, baseline * 0.08)
    excesses = tuple(max(0.0, value - baseline - dead_zone) for value in values)
    maximum = max(excesses, default=0.0)
    if maximum <= 0.0:
        return tuple(0 for _ in values)
    return tuple(
        0 if excess <= 0.0 else round(100.0 * (excess / maximum) ** 0.65)
        for excess in excesses
    )


def _percentile(values: tuple[float, ...], current: float) -> float:
    if not values:
        return 0.0
    below = sum(value < current for value in values)
    equal = sum(value == current for value in values)
    return (below + equal * 0.5) / len(values) * 100.0


def _float_median(values: tuple[float, ...]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _severity(
    raw: float,
    percentile: float,
    position_score: float,
    deviation: float,
    trigger_age: int | None,
    structural_floor: float,
) -> int:
    structural = _structural_severity(deviation, structural_floor)
    if raw <= 0.0:
        return structural
    freshness = 0.0 if trigger_age is None else max(0.0, 100.0 - float(trigger_age) * 15.0)
    value = (
        percentile * 0.6
        + position_score * 0.2
        + min(100.0, deviation * 500.0) * 0.1
        + freshness * 0.1
    )
    if trigger_age is None:
        value = min(value, 29.0)
    elif percentile < 60.0:
        value = min(value, 59.0)
    elif not (percentile >= 90.0 and position_score >= 80.0 and trigger_age <= 2):
        value = min(value, 79.0)
    return max(structural, max(0, min(100, round(value))))


def _structural_severity(deviation: float, floor: float) -> int:
    """Keep a material anchor gap visible after the brief pressure pulse fades."""
    if deviation < floor:
        return 0
    return min(
        95,
        max(
            30,
            round(
                30
                + _STRUCTURAL_DEVIATION_GAIN
                * log(deviation / floor)
            ),
        ),
    )
