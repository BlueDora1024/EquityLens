from __future__ import annotations

from stock_toolbox.analyses.extreme_deviation.domain.consensus import (
    ConsensusKind,
    build_consensus,
)
from stock_toolbox.analyses.extreme_deviation.domain.scoring import (
    Confidence,
    PeriodDirection,
    PeriodScore,
)
from stock_toolbox.core.market_data.models import CandleInterval


def _score(interval: CandleInterval, value: int) -> PeriodScore:
    direction = (
        PeriodDirection.BUY
        if value < -29
        else PeriodDirection.SELL
        if value > 29
        else PeriodDirection.NEUTRAL
    )
    return PeriodScore(
        interval,
        value,
        "",
        direction,
        Confidence.FULL,
        abs(value) if value < 0 else 0,
        max(0, value),
        0.0,
        0.0,
        0.5,
        None,
    )


def _conflict(interval: CandleInterval, attention: int) -> PeriodScore:
    return PeriodScore(
        interval,
        0,
        "周期内冲突",
        PeriodDirection.CONFLICT,
        Confidence.FULL,
        attention,
        attention,
        95.0,
        95.0,
        0.5,
        None,
        attention_score=attention,
    )


def test_two_buy_periods_produce_buy_resonance_without_opposite_cancellation() -> None:
    result = build_consensus(
        (
            _score(CandleInterval.MIN_30, -70),
            _score(CandleInterval.DAY, -50),
            _score(CandleInterval.WEEK, 10),
        )
    )

    assert result.kind is ConsensusKind.BUY_RESONANCE
    assert result.score < -50


def test_material_opposing_weights_produce_period_divergence() -> None:
    result = build_consensus(
        (
            _score(CandleInterval.MIN_30, -70),
            _score(CandleInterval.MIN_60, -60),
            _score(CandleInterval.WEEK, 80),
        )
    )

    assert result.kind is ConsensusKind.PERIOD_DIVERGENCE
    assert result.score == 0
    assert result.attention_score == 80


def test_one_directional_period_is_not_called_resonance() -> None:
    result = build_consensus(
        (
            _score(CandleInterval.MIN_30, -70),
            _score(CandleInterval.DAY, 10),
        )
    )

    assert result.kind is ConsensusKind.NEUTRAL
    assert result.score == 0


def test_single_daily_or_weekly_extreme_is_preserved() -> None:
    daily = build_consensus((_score(CandleInterval.DAY, -88),))
    weekly = build_consensus((_score(CandleInterval.WEEK, 95),))

    assert daily.kind is ConsensusKind.SINGLE_PERIOD_EXTREME
    assert daily.score == -88
    assert daily.attention_score == 88
    assert daily.active_intervals == (CandleInterval.DAY,)
    assert weekly.kind is ConsensusKind.SINGLE_PERIOD_EXTREME
    assert weekly.score == 95
    assert weekly.attention_score == 95


def test_single_short_period_does_not_become_a_long_period_extreme() -> None:
    result = build_consensus((_score(CandleInterval.MIN_60, -95),))

    assert result.kind is ConsensusKind.NEUTRAL
    assert result.score == 0
    assert result.attention_score == 0


def test_period_internal_conflict_is_not_hidden_by_another_direction() -> None:
    result = build_consensus(
        (
            _conflict(CandleInterval.DAY, 86),
            _score(CandleInterval.MIN_30, -70),
        )
    )

    assert result.kind is ConsensusKind.PERIOD_DIVERGENCE
    assert result.score == 0
    assert result.attention_score == 86
    assert result.active_intervals == (
        CandleInterval.MIN_30,
        CandleInterval.DAY,
    )
