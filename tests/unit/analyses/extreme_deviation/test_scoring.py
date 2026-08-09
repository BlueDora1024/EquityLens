from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stock_toolbox.analyses.extreme_deviation.domain.models import IndicatorPoint
from stock_toolbox.analyses.extreme_deviation.domain.scoring import (
    Confidence,
    PeriodDirection,
    label_for_score,
    pressure_contrast_series,
    score_latest,
    score_series,
)
from stock_toolbox.core.market_data.models import CandleInterval


def _points(
    *,
    buy_current: float,
    sell_current: float,
    position: float,
    buy_age: int | None = 0,
    sell_age: int | None = 0,
    buy_deviation: float | None = None,
    sell_deviation: float | None = None,
) -> tuple[IndicatorPoint, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    output = []
    for index in range(100):
        output.append(
            IndicatorPoint(
                start + timedelta(days=index),
                100.0,
                150.0,
                75.0,
                buy_current if index == 99 else 1.0,
                sell_current if index == 99 else 1.0,
                position,
                buy_deviation
                if buy_deviation is not None
                else (0.20 if buy_current > 1 else 0.0),
                sell_deviation
                if sell_deviation is not None
                else (0.20 if sell_current > 1 else 0.0),
                buy_age,
                sell_age,
            )
        )
    return tuple(output)


@pytest.mark.parametrize(
    ("score", "label"),
    (
        (-100, "超级买入观察"),
        (-80, "超级买入观察"),
        (-79, "买入观察"),
        (-60, "买入观察"),
        (-59, "偏买入"),
        (-30, "偏买入"),
        (-29, "中性"),
        (29, "中性"),
        (30, "偏卖出"),
        (59, "偏卖出"),
        (60, "卖出观察"),
        (79, "卖出观察"),
        (80, "超级卖出观察"),
        (100, "超级卖出观察"),
    ),
)
def test_score_labels_have_closed_non_overlapping_boundaries(
    score: int,
    label: str,
) -> None:
    assert label_for_score(score) == label


def test_full_sample_can_produce_super_buy_observation() -> None:
    result = score_latest(
        CandleInterval.DAY,
        650,
        _points(buy_current=100.0, sell_current=1.0, position=0.02, sell_age=None),
    )

    assert result.confidence is Confidence.FULL
    assert result.direction is PeriodDirection.BUY
    assert result.score <= -80
    assert result.label == "超级买入观察"


def test_less_than_100_bars_is_low_confidence_but_still_actionable() -> None:
    result = score_latest(
        CandleInterval.DAY,
        62,
        _points(
            buy_current=100.0,
            sell_current=1.0,
            position=0.02,
            sell_age=None,
        )[-62:],
    )

    assert result.confidence is Confidence.LOW
    assert result.score == -79
    assert result.label == "买入观察"


def test_less_than_30_bars_produces_no_score() -> None:
    result = score_latest(
        CandleInterval.DAY,
        29,
        _points(buy_current=100.0, sell_current=1.0, position=0.02)[-29:],
    )

    assert result.confidence is Confidence.INSUFFICIENT
    assert result.score is None


def test_strong_buy_and_sell_pressure_is_reported_as_period_conflict() -> None:
    result = score_latest(
        CandleInterval.MIN_30,
        650,
        _points(buy_current=100.0, sell_current=100.0, position=0.5),
    )

    assert result.direction is PeriodDirection.CONFLICT
    assert result.score == 0
    assert result.label == "周期内冲突"
    assert result.attention_score >= 60


def test_older_live_pressure_decays_without_falling_directly_to_neutral() -> None:
    result = score_latest(
        CandleInterval.DAY,
        100,
        _points(
            buy_current=100.0,
            sell_current=1.0,
            position=0.02,
            buy_age=6,
            sell_age=None,
        ),
    )

    assert result.direction is PeriodDirection.BUY
    assert result.score == -79


def test_daily_structural_deviation_uses_a_lower_period_specific_floor() -> None:
    result = score_latest(
        CandleInterval.DAY,
        100,
        _points(
            buy_current=0.0,
            sell_current=0.0,
            position=0.2,
            buy_age=20,
            sell_age=20,
            buy_deviation=0.045,
            sell_deviation=0.0,
        ),
    )

    assert result.direction is PeriodDirection.BUY
    assert result.score is not None and result.score <= -30


def test_structural_sell_deviation_remains_scored_after_pressure_pulse_decays() -> None:
    result = score_latest(
        CandleInterval.DAY,
        650,
        _points(
            buy_current=0.0,
            sell_current=0.0,
            position=0.74,
            buy_age=25,
            sell_age=5,
            buy_deviation=0.0,
            sell_deviation=0.60,
        ),
    )

    assert result.direction is PeriodDirection.SELL
    assert result.score is not None
    assert 60 <= result.score <= 79
    assert result.label == "卖出观察"


def test_structural_deviation_populates_the_frozen_chart_score_series() -> None:
    points = _points(
        buy_current=0.0,
        sell_current=0.0,
        position=0.74,
        buy_age=25,
        sell_age=5,
        buy_deviation=0.0,
        sell_deviation=0.60,
    ) * 2

    scores = score_series(CandleInterval.DAY, 650, points)

    assert scores
    assert all(item.score is not None and item.score >= 60 for item in scores)


def test_raw_pressure_contrast_preserves_signal_side_and_amplifies_outlier() -> None:
    buy, sell = pressure_contrast_series(
        (2.0, 2.1, 2.0, 48.0, 0.0),
        (0.0, 0.0, 0.0, 0.0, 36.0),
    )

    assert buy[:3] == (0, 0, 0)
    assert buy[3] == 100
    assert sell[-1] == 100


def test_score_series_freezes_latest_one_hundred_normalized_points() -> None:
    points = _points(
        buy_current=100.0,
        sell_current=1.0,
        position=0.02,
        sell_age=None,
    ) * 2

    scores = score_series(CandleInterval.DAY, 650, points)

    assert len(scores) == 100
    assert scores[-1] == score_latest(CandleInterval.DAY, 650, points)
