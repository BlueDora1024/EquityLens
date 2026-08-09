"""Deterministic turning-point signal backtest used by the developer CLI."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from stock_toolbox.analyses.turning_point.domain.engine import (
    MINIMUM_BARS,
    TurningPointEngine,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    ScreeningDecision,
    TurningPointTradeSide,
)
from stock_toolbox.core.market_data.models import (
    CandleInterval,
    MarketCandle,
)

_WINDOW = 220


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    signal_at: datetime
    entry_at: datetime
    exit_at: datetime
    entry_price: float
    return_5: float
    return_10: float
    mfe: float
    mae: float
    won: bool


@dataclass(frozen=True, slots=True)
class BacktestEvaluation:
    trades: tuple[BacktestTrade, ...]
    skipped_overlap: int
    unsettled: int

    @property
    def wins(self) -> int:
        return sum(item.won for item in self.trades)

    @property
    def win_rate(self) -> float | None:
        return self.wins / len(self.trades) if self.trades else None

    @property
    def average_return_5(self) -> float | None:
        return _average(item.return_5 for item in self.trades)

    @property
    def average_return_10(self) -> float | None:
        return _average(item.return_10 for item in self.trades)

    @property
    def average_mfe(self) -> float | None:
        return _average(item.mfe for item in self.trades)

    @property
    def average_mae(self) -> float | None:
        return _average(item.mae for item in self.trades)


@dataclass(frozen=True, slots=True)
class BacktestCell:
    symbol: str
    interval: CandleInterval
    trade_side: TurningPointTradeSide
    candle_count: int
    evaluation: BacktestEvaluation


@dataclass(frozen=True, slots=True)
class TurningPointBacktest:
    provider_id: str
    provider_display_name: str
    requested_end_date: date
    requested_count: int
    cells: tuple[BacktestCell, ...]
    errors: tuple[tuple[str, str, str], ...]


def detect_signal_indexes(
    candles: tuple[MarketCandle, ...],
    trade_side: TurningPointTradeSide,
) -> tuple[int, ...]:
    """Replay the production 220-bar decision window without look-ahead."""
    engine = TurningPointEngine()
    indexes: list[int] = []
    seen: set[tuple[object, object]] = set()
    for end_index in range(MINIMUM_BARS - 1, len(candles)):
        start = max(0, end_index - _WINDOW + 1)
        result = engine.screen(
            "",
            candles[start : end_index + 1],
            trade_side,
        )
        if result.decision is not ScreeningDecision.MATCHED:
            continue
        identity = (result.signal_at, result.crossed_at)
        if identity in seen:
            continue
        seen.add(identity)
        indexes.append(end_index)
    return tuple(indexes)


def evaluate_signal_indexes(
    candles: tuple[MarketCandle, ...],
    signal_indexes: tuple[int, ...],
) -> BacktestEvaluation:
    """Next-open entry, fifth/tenth close returns, no overlapping trades."""
    trades: list[BacktestTrade] = []
    skipped_overlap = 0
    unsettled = 0
    previous_exit = -1
    for signal_index in signal_indexes:
        entry_index = signal_index + 1
        exit_index = signal_index + 10
        if entry_index <= previous_exit:
            skipped_overlap += 1
            continue
        if exit_index >= len(candles):
            unsettled += 1
            continue
        entry = float(candles[entry_index].open)
        fifth = float(candles[signal_index + 5].close)
        tenth = float(candles[exit_index].close)
        holding = candles[entry_index : exit_index + 1]
        trades.append(
            BacktestTrade(
                candles[signal_index].timestamp,
                candles[entry_index].timestamp,
                candles[exit_index].timestamp,
                entry,
                fifth / entry - 1.0,
                tenth / entry - 1.0,
                max(float(item.high) for item in holding) / entry - 1.0,
                min(float(item.low) for item in holding) / entry - 1.0,
                tenth > entry,
            )
        )
        previous_exit = exit_index
    return BacktestEvaluation(tuple(trades), skipped_overlap, unsettled)


def backtest_candles(
    symbol: str,
    interval: CandleInterval,
    candles: tuple[MarketCandle, ...],
    trade_sides: tuple[TurningPointTradeSide, ...],
) -> tuple[BacktestCell, ...]:
    return tuple(
        BacktestCell(
            symbol,
            interval,
            trade_side,
            len(candles),
            evaluate_signal_indexes(
                candles,
                detect_signal_indexes(candles, trade_side),
            ),
        )
        for trade_side in trade_sides
    )


def _average(values: Iterable[float]) -> float | None:
    collected = tuple(values)
    return sum(collected) / len(collected) if collected else None
