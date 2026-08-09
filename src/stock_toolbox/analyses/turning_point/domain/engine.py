"""Pure implementation of the recovered V13 turning-point algorithm."""

from __future__ import annotations

import math
from collections.abc import Sequence

from stock_toolbox.analyses.turning_point.domain.attention import (
    CD_LEFT_ENTRY,
    CONFIRMED_BULLISH_DIVERGENCE,
    MULTI_SWING_BULLISH_DIVERGENCE,
    RECENT_BULLISH_DIVERGENCE,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    ScreeningDecision,
    SymbolScreenResult,
    TurningPointTradeSide,
)
from stock_toolbox.core.market_data.models import CandleInterval, MarketCandle

MINIMUM_BARS = 119
SIGNAL_LOOKBACK = 30
MAX_SIGNAL_TO_CROSS_BARS = 20
_RECENT_WINDOW_BARS = {
    CandleInterval.MIN_30: 65,
    CandleInterval.MIN_60: 35,
    CandleInterval.MIN_120: 20,
    CandleInterval.MIN_240: 10,
    CandleInterval.DAY: 20,
    CandleInterval.WEEK: 8,
}


def recent_window_bars(interval: CandleInterval) -> int:
    return _RECENT_WINDOW_BARS[interval]


def ema(values: Sequence[float], span: int) -> tuple[float, ...]:
    """Match pandas ewm(span=span, adjust=False).mean() for finite inputs."""
    if not values:
        return ()
    alpha = 2.0 / (span + 1.0)
    output = [float(values[0])]
    for value in values[1:]:
        output.append(alpha * float(value) + (1.0 - alpha) * output[-1])
    return tuple(output)


class TurningPointEngine:
    def screen(
        self,
        symbol: str,
        candles: tuple[MarketCandle, ...],
        trade_side: TurningPointTradeSide = TurningPointTradeSide.RIGHT_CONFIRMED,
        *,
        signal_lookback: int = SIGNAL_LOOKBACK,
    ) -> SymbolScreenResult:
        if len(candles) < MINIMUM_BARS:
            return SymbolScreenResult(
                symbol, ScreeningDecision.FAILED, "insufficient_bars"
            )
        highs = tuple(float(item.high) for item in candles)
        closes = tuple(float(item.close) for item in candles)
        if any(not math.isfinite(value) or value <= 0 for value in (*highs, *closes)):
            return SymbolScreenResult(
                symbol, ScreeningDecision.FAILED, "malformed_data"
            )

        high_ema26 = ema(highs, 26)
        high_ema89 = ema(highs, 89)
        short = ema(closes, 12)
        long = ema(closes, 26)
        dif = tuple(
            left - right
            for left, right in zip(short, long, strict=True)
        )
        dea = ema(dif, 9)
        histogram = tuple(
            (left - right) * 2.0
            for left, right in zip(dif, dea, strict=True)
        )
        volumes = tuple(float(item.volume) for item in candles)
        ratio = _latest_volume_ratio(volumes)
        return self.screen_derived(
            symbol,
            tuple(item.timestamp for item in candles),
            highs,
            closes,
            high_ema26,
            high_ema89,
            dif,
            histogram,
            ratio,
            trade_side,
            signal_lookback=signal_lookback,
        )

    def screen_derived(
        self,
        symbol: str,
        timestamps: Sequence[object],
        highs: Sequence[float],
        closes: Sequence[float],
        high_ema26: Sequence[float],
        high_ema89: Sequence[float],
        dif: Sequence[float],
        histogram: Sequence[float],
        volume_ratio: float | None,
        trade_side: TurningPointTradeSide = TurningPointTradeSide.RIGHT_CONFIRMED,
        *,
        signal_lookback: int = SIGNAL_LOOKBACK,
    ) -> SymbolScreenResult:
        size = len(closes)
        series = (
            timestamps,
            highs,
            high_ema26,
            high_ema89,
            dif,
            histogram,
        )
        if size < MINIMUM_BARS:
            return SymbolScreenResult(
                symbol, ScreeningDecision.FAILED, "insufficient_bars"
            )
        if any(len(item) != size for item in series):
            return SymbolScreenResult(
                symbol, ScreeningDecision.FAILED, "malformed_data"
            )
        if any(
            not math.isfinite(float(value)) or float(value) <= 0
            for value in (*highs, *closes)
        ):
            return SymbolScreenResult(
                symbol, ScreeningDecision.FAILED, "malformed_data"
            )
        ccc, kinds = _divergence_state_from_macd(closes, dif, histogram)
        signal_start = max(1, size - signal_lookback)
        signal_indexes = tuple(
            index
            for index in ccc_start_indexes(ccc)
            if index >= signal_start
        )
        enhancement_indexes = left_cd_indexes(ccc, dif)
        if trade_side is TurningPointTradeSide.LEFT_CD:
            if not signal_indexes:
                return SymbolScreenResult(
                    symbol,
                    ScreeningDecision.NOT_MATCHED,
                    "NO_CD_SIGNAL",
                    last_price=float(closes[-1]),
                    volume_ratio=volume_ratio,
                )
            signal_index = signal_indexes[-1]
            enhanced_at = next(
                (
                    timestamps[index]
                    for index in enhancement_indexes
                    if index >= signal_index
                ),
                None,
            )
            return SymbolScreenResult(
                symbol=symbol,
                decision=ScreeningDecision.MATCHED,
                reason="matched",
                signal_kind=CD_LEFT_ENTRY,
                signal_at=timestamps[signal_index],  # type: ignore[arg-type]
                last_price=float(closes[-1]),
                volume_ratio=volume_ratio,
                quality_score=_left_quality_score(
                    size,
                    signal_index,
                    volume_ratio,
                    signal_lookback,
                ),
                enhanced_at=enhanced_at,  # type: ignore[arg-type]
            )
        cross_indexes = recent_cross_indexes(
            closes,
            high_ema26,
            lookback=signal_lookback,
        )
        if not signal_indexes:
            return SymbolScreenResult(
                symbol,
                ScreeningDecision.NOT_MATCHED,
                (
                    "CROSS_WITHOUT_DIVERGENCE"
                    if cross_indexes
                    else "NO_CD_SIGNAL"
                ),
                last_price=float(closes[-1]),
                volume_ratio=volume_ratio,
            )
        weak_trend_signals = tuple(
            index
            for index in signal_indexes
            if high_ema26[index] < high_ema89[index]
        )
        if not weak_trend_signals:
            return SymbolScreenResult(
                symbol,
                ScreeningDecision.NOT_MATCHED,
                "TREND_FILTER_NOT_MET",
                last_price=float(closes[-1]),
                volume_ratio=volume_ratio,
            )

        if not cross_indexes:
            return SymbolScreenResult(
                symbol,
                ScreeningDecision.NOT_MATCHED,
                "CD_AWAITING_CONFIRMATION",
                last_price=float(closes[-1]),
                volume_ratio=volume_ratio,
            )

        candidates: list[tuple[int, int, str]] = []
        for signal_index in weak_trend_signals:
            kind = _divergence_kind_for_cd(kinds, signal_index)
            for cross_index in cross_indexes:
                distance = cross_index - signal_index
                if 0 <= distance <= MAX_SIGNAL_TO_CROSS_BARS:
                    candidates.append((signal_index, cross_index, kind))
        if not candidates:
            return SymbolScreenResult(
                symbol,
                ScreeningDecision.NOT_MATCHED,
                "SIGNAL_EXPIRED",
                last_price=float(closes[-1]),
                volume_ratio=volume_ratio,
            )
        signal_index, cross_index, kind = max(
            candidates,
            key=lambda item: (item[0], -abs(item[1] - item[0]), item[1]),
        )
        enhanced_at = next(
            (
                timestamps[index]
                for index in enhancement_indexes
                if index >= signal_index
            ),
            None,
        )
        return SymbolScreenResult(
            symbol=symbol,
            decision=ScreeningDecision.MATCHED,
            reason="matched",
            signal_kind=kind,
            signal_at=timestamps[signal_index],  # type: ignore[arg-type]
            crossed_at=timestamps[cross_index],  # type: ignore[arg-type]
            last_price=float(closes[-1]),
            volume_ratio=volume_ratio,
            quality_score=_quality_score(
                size,
                signal_index,
                cross_index,
                volume_ratio,
                signal_lookback,
            ),
            enhanced_at=enhanced_at,  # type: ignore[arg-type]
        )


def _divergence_kind_for_cd(
    kinds: Sequence[str | None],
    signal_index: int,
) -> str:
    for index in range(signal_index, max(-1, signal_index - 30), -1):
        if kinds[index] is not None:
            return str(kinds[index])
    return CD_LEFT_ENTRY


def recent_cross_indexes(
    closes: Sequence[float],
    average: Sequence[float],
    *,
    lookback: int,
) -> tuple[int, ...]:
    """Return crosses from the last N complete bar-to-bar transitions."""
    if len(closes) != len(average) or lookback <= 0:
        raise ValueError("invalid cross window")
    start = max(1, len(closes) - lookback)
    return tuple(
        index
        for index in range(start, len(closes))
        if closes[index] > average[index]
        and closes[index - 1] < average[index - 1]
    )


def ccc_start_indexes(ccc: Sequence[bool]) -> tuple[int, ...]:
    return tuple(
        index
        for index, active in enumerate(ccc)
        if active and (index == 0 or not ccc[index - 1])
    )


def left_cd_indexes(
    ccc: Sequence[bool],
    dif: Sequence[float],
) -> tuple[int, ...]:
    """Return first JJJ bars, matching the original DXDX expression."""
    if len(ccc) != len(dif):
        raise ValueError("invalid CD series")
    jjj = tuple(
        index > 0
        and ccc[index - 1]
        and abs(dif[index - 1]) >= abs(dif[index]) * 1.01
        for index in range(len(dif))
    )
    return tuple(
        index
        for index, active in enumerate(jjj)
        if active and (index == 0 or not jjj[index - 1])
    )


def _signal_kinds(closes: Sequence[float]) -> tuple[str | None, ...]:
    short = ema(closes, 12)
    long = ema(closes, 26)
    dif = tuple(left - right for left, right in zip(short, long, strict=True))
    dea = ema(dif, 9)
    histogram = tuple(
        (left - right) * 2.0 for left, right in zip(dif, dea, strict=True)
    )
    return _signal_kinds_from_macd(closes, dif, histogram)


def _signal_kinds_from_macd(
    closes: Sequence[float],
    dif: Sequence[float],
    histogram: Sequence[float],
) -> tuple[str | None, ...]:
    return _divergence_state_from_macd(closes, dif, histogram)[1]


def _divergence_state_from_macd(
    closes: Sequence[float],
    dif: Sequence[float],
    histogram: Sequence[float],
) -> tuple[tuple[bool, ...], tuple[str | None, ...]]:
    negative_cross = tuple(
        index > 0
        and histogram[index - 1] >= 0
        and value < 0
        for index, value in enumerate(histogram)
    )
    positive_cross = tuple(
        index > 0
        and histogram[index - 1] <= 0
        and value > 0
        for index, value in enumerate(histogram)
    )
    n1 = _bars_since_last(negative_cross)
    mm1 = _bars_since_last(positive_cross)
    cc1 = _lowest_since_event(closes, n1)
    difl1 = _lowest_since_event(dif, n1)
    reference_offsets = tuple(distance + 1 for distance in mm1)
    cc2 = _dynamic_ref(cc1, reference_offsets)
    cc3 = _dynamic_ref(cc2, reference_offsets)
    difl2 = _dynamic_ref(difl1, reference_offsets)
    difl3 = _dynamic_ref(difl2, reference_offsets)
    ccc: list[bool] = []
    kinds: list[str | None] = []
    for index in range(len(closes)):
        prior_negative = index > 0 and histogram[index - 1] < 0
        previous_close = cc2[index]
        second_previous_close = cc3[index]
        previous_dif = difl2[index]
        second_previous_dif = difl3[index]
        aaa = (
            previous_close is not None
            and cc1[index] < previous_close
            and previous_dif is not None
            and difl1[index] > previous_dif
            and prior_negative
            and dif[index] < 0
        )
        bbb = (
            second_previous_close is not None
            and cc1[index] < second_previous_close
            and previous_dif is not None
            and second_previous_dif is not None
            and difl1[index] < previous_dif
            and difl1[index] > second_previous_dif
            and prior_negative
            and dif[index] < 0
        )
        active = bool(aaa or bbb)
        rising = active and (index == 0 or not ccc[index - 1])
        ccc.append(active)
        if not rising:
            kinds.append(None)
        elif aaa and bbb:
            kinds.append(CONFIRMED_BULLISH_DIVERGENCE)
        elif aaa:
            kinds.append(RECENT_BULLISH_DIVERGENCE)
        else:
            kinds.append(MULTI_SWING_BULLISH_DIVERGENCE)
    return tuple(ccc), tuple(kinds)


def _latest_volume_ratio(volumes: Sequence[float]) -> float | None:
    if len(volumes) < 20:
        return None
    average = sum(volumes[-20:]) / 20.0
    return None if average <= 0 else volumes[-1] / average


def _quality_score(
    size: int,
    signal_index: int,
    cross_index: int,
    volume_ratio: float | None,
    lookback: int,
) -> int:
    signal_freshness = max(
        0.0,
        1.0 - (size - 1 - signal_index) / lookback,
    )
    cross_freshness = max(
        0.0,
        1.0 - (size - 1 - cross_index) / lookback,
    )
    volume_quality = (
        0.5
        if volume_ratio is None
        else min(1.0, max(0.0, volume_ratio / 2.0))
    )
    return round(
        signal_freshness * 40.0
        + cross_freshness * 35.0
        + volume_quality * 25.0
    )


def _left_quality_score(
    size: int,
    signal_index: int,
    volume_ratio: float | None,
    lookback: int,
) -> int:
    signal_freshness = max(
        0.0,
        1.0 - (size - 1 - signal_index) / lookback,
    )
    volume_quality = (
        0.5
        if volume_ratio is None
        else min(1.0, max(0.0, volume_ratio / 2.0))
    )
    return round(signal_freshness * 75.0 + volume_quality * 25.0)


def _bars_since_last(events: Sequence[bool]) -> tuple[int, ...]:
    last_event: int | None = None
    output: list[int] = []
    for index, active in enumerate(events):
        if active:
            last_event = index
        output.append(
            index - last_event if last_event is not None else index + 1
        )
    return tuple(output)


def _lowest_since_event(
    values: Sequence[float],
    distances: Sequence[int],
) -> tuple[float, ...]:
    if len(values) != len(distances):
        raise ValueError("misaligned BARSLAST series")
    minimum = math.inf
    output: list[float] = []
    for value, distance in zip(values, distances, strict=True):
        minimum = float(value) if distance == 0 else min(minimum, float(value))
        output.append(minimum)
    return tuple(output)


def _dynamic_ref(
    values: Sequence[float | None],
    offsets: Sequence[int],
) -> tuple[float | None, ...]:
    if len(values) != len(offsets):
        raise ValueError("misaligned REF series")
    return tuple(
        values[index - offset] if index >= offset else None
        for index, offset in enumerate(offsets)
    )
