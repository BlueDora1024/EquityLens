"""Weighted multi-period conclusion without misleading sign cancellation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stock_toolbox.analyses.extreme_deviation.domain.scoring import (
    PeriodDirection,
    PeriodScore,
)
from stock_toolbox.core.market_data.models import CandleInterval

INTERVAL_WEIGHTS: dict[CandleInterval, float] = {
    CandleInterval.MIN_30: 1.0,
    CandleInterval.MIN_60: 1.1,
    CandleInterval.DAY: 1.7,
    CandleInterval.WEEK: 2.0,
}


class ConsensusKind(StrEnum):
    BUY_RESONANCE = "BUY_RESONANCE"
    SELL_RESONANCE = "SELL_RESONANCE"
    PERIOD_DIVERGENCE = "PERIOD_DIVERGENCE"
    SINGLE_PERIOD_EXTREME = "SINGLE_PERIOD_EXTREME"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class MultiPeriodConsensus:
    kind: ConsensusKind
    score: int
    active_intervals: tuple[CandleInterval, ...]
    attention_score: int = 0


def build_consensus(
    scores: tuple[PeriodScore, ...],
) -> MultiPeriodConsensus:
    active = tuple(
        item
        for item in scores
        if item.score is not None
        and abs(item.score) >= 30
        and item.direction in {PeriodDirection.BUY, PeriodDirection.SELL}
    )
    conflicts = tuple(
        item
        for item in scores
        if item.direction is PeriodDirection.CONFLICT and item.attention_score >= 30
    )
    if conflicts:
        evidence = (*active, *conflicts)
        return MultiPeriodConsensus(
            ConsensusKind.PERIOD_DIVERGENCE,
            0,
            tuple(dict.fromkeys(item.interval for item in evidence)),
            max(
                max(abs(item.score or 0), item.attention_score)
                for item in evidence
            ),
        )
    if len(active) < 2:
        item = active[0] if active else None
        if (
            item is not None
            and item.interval in {CandleInterval.DAY, CandleInterval.WEEK}
            and abs(item.score or 0) >= 60
        ):
            magnitude = abs(item.score or 0)
            return MultiPeriodConsensus(
                ConsensusKind.SINGLE_PERIOD_EXTREME,
                item.score or 0,
                (item.interval,),
                magnitude,
            )
        return MultiPeriodConsensus(ConsensusKind.NEUTRAL, 0, (), 0)
    buy = tuple(item for item in active if item.direction is PeriodDirection.BUY)
    sell = tuple(item for item in active if item.direction is PeriodDirection.SELL)
    buy_weight = sum(INTERVAL_WEIGHTS[item.interval] for item in buy)
    sell_weight = sum(INTERVAL_WEIGHTS[item.interval] for item in sell)
    total_weight = buy_weight + sell_weight
    if (
        buy_weight
        and sell_weight
        and buy_weight / total_weight >= 0.30
        and sell_weight / total_weight >= 0.30
    ):
        return MultiPeriodConsensus(
            ConsensusKind.PERIOD_DIVERGENCE,
            0,
            tuple(item.interval for item in active),
            max(abs(item.score or 0) for item in active),
        )
    dominant = buy if buy_weight > sell_weight else sell
    if len(dominant) < 2:
        return MultiPeriodConsensus(ConsensusKind.NEUTRAL, 0, (), 0)
    weighted = sum(abs(item.score or 0) * INTERVAL_WEIGHTS[item.interval] for item in dominant)
    weight = sum(INTERVAL_WEIGHTS[item.interval] for item in dominant)
    magnitude = max(0, min(100, round(weighted / weight)))
    is_buy = dominant is buy
    return MultiPeriodConsensus(
        ConsensusKind.BUY_RESONANCE if is_buy else ConsensusKind.SELL_RESONANCE,
        -magnitude if is_buy else magnitude,
        tuple(item.interval for item in dominant),
        magnitude,
    )
