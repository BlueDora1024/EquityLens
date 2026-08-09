"""Corrected buy/sell extreme-deviation indicator."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from stock_toolbox.analyses.extreme_deviation.domain.models import IndicatorPoint
from stock_toolbox.analyses.extreme_deviation.domain.primitives import (
    directional_pressure,
    ema_optional,
    rolling_max,
    rolling_min,
    rolling_optional_max,
)
from stock_toolbox.core.market_data.models import MarketCandle

LONG_WINDOWS = (500, 250, 90)
SMOOTHING = 21
TRIGGER_WINDOW = 30
FINAL_SMOOTHING = 3
ANCHOR_SCALE = 1.738
DEVIATION_SCALE = 1.35
GOLDEN_RATIO = 0.618


class ExtremeDeviationIndicator:
    def calculate(
        self,
        candles: tuple[MarketCandle, ...],
    ) -> tuple[IndicatorPoint, ...]:
        if len(candles) < TRIGGER_WINDOW:
            return ()
        if any(
            current.timestamp >= following.timestamp for current, following in pairwise(candles)
        ):
            raise ValueError("candles must be strictly ordered")

        highs = tuple(float(item.high) for item in candles)
        lows = tuple(float(item.low) for item in candles)
        closes = tuple(float(item.close) for item in candles)

        buy_highs = tuple(
            ema_optional(rolling_max(highs, window), SMOOTHING) for window in LONG_WINDOWS
        )
        buy_lows = tuple(
            ema_optional(rolling_min(lows, window), SMOOTHING) for window in LONG_WINDOWS
        )
        sell_lows = buy_lows
        sell_highs = buy_highs

        buy_anchor = _anchor(buy_lows, buy_highs)
        sell_anchor = _anchor(sell_lows, sell_highs)

        buy_ratio = directional_pressure(lows, "buy")
        sell_ratio = directional_pressure(highs, "sell")
        buy_instd = ema_optional(
            tuple(
                None
                if anchor is None
                else ratio * 10.0
                if close * DEVIATION_SCALE <= anchor
                else ratio / 10.0
                for close, anchor, ratio in zip(closes, buy_anchor, buy_ratio, strict=True)
            ),
            FINAL_SMOOTHING,
        )
        sell_instd = ema_optional(
            tuple(
                None
                if anchor is None
                else ratio * 10.0
                if close * 0.65 >= anchor
                else ratio / 10.0
                for close, anchor, ratio in zip(closes, sell_anchor, sell_ratio, strict=True)
            ),
            FINAL_SMOOTHING,
        )

        low_30 = rolling_min(lows, TRIGGER_WINDOW)
        high_30 = rolling_max(highs, TRIGGER_WINDOW)
        buy_memory = rolling_optional_max(buy_instd, TRIGGER_WINDOW)
        sell_memory = _rolling_optional_min(sell_instd, TRIGGER_WINDOW)
        buy_trigger = tuple(
            boundary is not None and low <= boundary
            for low, boundary in zip(lows, low_30, strict=True)
        )
        sell_trigger = tuple(
            boundary is not None and high >= boundary
            for high, boundary in zip(highs, high_30, strict=True)
        )
        buy_raw = _final_pressure(buy_instd, buy_memory, buy_trigger)
        sell_raw = _final_pressure(sell_instd, sell_memory, sell_trigger)
        buy_ages = _trigger_ages(buy_trigger)
        sell_ages = _trigger_ages(sell_trigger)

        points: list[IndicatorPoint] = []
        for index, candle in enumerate(candles):
            values = (
                buy_anchor[index],
                sell_anchor[index],
                buy_raw[index],
                sell_raw[index],
                low_30[index],
                high_30[index],
            )
            if any(value is None for value in values):
                continue
            current_buy_anchor = float(buy_anchor[index])  # type: ignore[arg-type]
            current_sell_anchor = float(sell_anchor[index])  # type: ignore[arg-type]
            current_low = float(low_30[index])  # type: ignore[arg-type]
            current_high = float(high_30[index])  # type: ignore[arg-type]
            width = current_high - current_low
            position = (
                0.5 if width <= 0.0 else min(1.0, max(0.0, (closes[index] - current_low) / width))
            )
            buy_threshold = closes[index] * DEVIATION_SCALE
            points.append(
                IndicatorPoint(
                    candle.timestamp,
                    closes[index],
                    current_buy_anchor,
                    current_sell_anchor,
                    float(buy_raw[index]),  # type: ignore[arg-type]
                    float(sell_raw[index]),  # type: ignore[arg-type]
                    position,
                    max(0.0, current_buy_anchor / buy_threshold - 1.0),
                    max(0.0, buy_threshold / current_sell_anchor - 1.0),
                    buy_ages[index],
                    sell_ages[index],
                )
            )
        return tuple(points)


def _anchor(
    lows: tuple[Sequence[float | None], ...],
    highs: tuple[Sequence[float | None], ...],
) -> tuple[float | None, ...]:
    inst7 = ema_optional(
        _weighted(lows, highs, (0.96, 0.96, 0.96), (0.558, 0.558, 0.558)),
        SMOOTHING,
    )
    inst8 = ema_optional(
        _weighted(lows, highs, (1.25, 1.23, 1.2), (0.55, 0.55, 0.65)),
        SMOOTHING,
    )
    inst9 = ema_optional(
        _weighted(lows, highs, (1.3, 1.3, 1.3), (0.68, 0.68, 0.68)),
        SMOOTHING,
    )
    combined: list[float | None] = []
    for first, second, third in zip(inst7, inst8, inst9, strict=True):
        combined.append(
            None
            if first is None or second is None or third is None
            else (first * 3.0 + second * 2.0 + third) / 6.0 * ANCHOR_SCALE
        )
    return ema_optional(combined, SMOOTHING)


def _weighted(
    lows: tuple[Sequence[float | None], ...],
    highs: tuple[Sequence[float | None], ...],
    low_weights: tuple[float, float, float],
    high_weights: tuple[float, float, float],
) -> tuple[float | None, ...]:
    output: list[float | None] = []
    for index in range(len(lows[0])):
        values = tuple(series[index] for series in (*lows, *highs))
        if any(value is None for value in values):
            output.append(None)
            continue
        present_values = tuple(value for value in values if value is not None)
        output.append(
            sum(
                value * weight
                for value, weight in zip(
                    present_values,
                    (*low_weights, *high_weights),
                    strict=True,
                )
            )
            / 6.0
        )
    return tuple(output)


def _final_pressure(
    instd: Sequence[float | None],
    memory: Sequence[float | None],
    triggers: Sequence[bool],
) -> tuple[float | None, ...]:
    raw: list[float | None] = []
    for current, strongest, trigger in zip(instd, memory, triggers, strict=True):
        raw.append(
            None
            if current is None or strongest is None
            else ((current + strongest * 2.0) / 2.0 if trigger else 0.0)
        )
    smoothed = ema_optional(raw, FINAL_SMOOTHING)
    return tuple(None if value is None else max(0.0, value / GOLDEN_RATIO) for value in smoothed)


def _trigger_ages(triggers: Sequence[bool]) -> tuple[int | None, ...]:
    last: int | None = None
    ages: list[int | None] = []
    for index, trigger in enumerate(triggers):
        if trigger:
            last = index
        ages.append(None if last is None else index - last)
    return tuple(ages)


def _rolling_optional_min(
    values: Sequence[float | None],
    window: int,
) -> tuple[float | None, ...]:
    output: list[float | None] = []
    for index in range(len(values)):
        current = values[max(0, index - window + 1) : index + 1]
        output.append(
            None
            if any(value is None for value in current)
            else min(value for value in current if value is not None)
        )
    return tuple(output)
