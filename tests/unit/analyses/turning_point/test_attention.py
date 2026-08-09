from datetime import datetime

from stock_toolbox.analyses.turning_point.domain.attention import (
    AttentionEvidence,
    attention_conclusion,
    attention_level,
    attention_score,
    attention_score_for_evidence,
    interval_label,
    normalize_signal_code,
    signal_label,
)
from stock_toolbox.core.market_data.models import CandleInterval


def test_attention_score_uses_period_weight_and_resonance() -> None:
    assert attention_score((CandleInterval.MIN_30,)) == 5
    assert attention_score((CandleInterval.MIN_60,)) == 10
    assert attention_score((CandleInterval.MIN_120,)) == 25
    assert attention_score((CandleInterval.MIN_240,)) == 35
    assert attention_score((CandleInterval.DAY,)) == 45
    assert attention_score((CandleInterval.WEEK,)) == 55
    assert attention_score((CandleInterval.DAY, CandleInterval.WEEK)) == 100
    assert attention_score(tuple(CandleInterval)) == 100


def test_aligned_two_hour_and_four_hour_signals_are_super_resonance() -> None:
    score = attention_score_for_evidence(
        (
            AttentionEvidence(
                CandleInterval.MIN_120,
                datetime.fromisoformat("2026-07-29T21:30:00+00:00"),
            ),
            AttentionEvidence(
                CandleInterval.MIN_240,
                datetime.fromisoformat("2026-07-30T01:30:00+00:00"),
            ),
        )
    )

    assert score.base_points == 60
    assert score.resonance_points == 20
    assert score.confirmation_points == 0
    assert score.total == 80
    assert attention_level(score.total) == "超级共振"


def test_far_apart_two_hour_and_four_hour_signals_do_not_get_bonus() -> None:
    score = attention_score_for_evidence(
        (
            AttentionEvidence(
                CandleInterval.MIN_120,
                datetime.fromisoformat("2026-07-01T21:30:00+00:00"),
            ),
            AttentionEvidence(
                CandleInterval.MIN_240,
                datetime.fromisoformat("2026-07-30T01:30:00+00:00"),
            ),
        )
    )

    assert score.base_points == 60
    assert score.resonance_points == 0
    assert score.total == 60


def test_right_side_confirmation_adds_ten_points_once() -> None:
    score = attention_score_for_evidence(
        (
            AttentionEvidence(
                CandleInterval.MIN_120,
                datetime.fromisoformat("2026-07-29T21:30:00+00:00"),
                right_confirmed=True,
            ),
            AttentionEvidence(
                CandleInterval.MIN_240,
                datetime.fromisoformat("2026-07-30T01:30:00+00:00"),
                right_confirmed=True,
            ),
        )
    )

    assert score.confirmation_points == 10
    assert score.total == 90


def test_single_weekly_right_confirmation_is_strong_attention() -> None:
    score = attention_score_for_evidence(
        (
            AttentionEvidence(
                CandleInterval.WEEK,
                datetime.fromisoformat("2026-07-31T20:00:00+00:00"),
                right_confirmed=True,
            ),
        )
    )

    assert score.base_points == 55
    assert score.confirmation_points == 10
    assert score.total == 65
    assert attention_level(score.total) == "强烈关注"


def test_attention_score_ignores_duplicate_periods() -> None:
    assert attention_score(
        (CandleInterval.DAY, CandleInterval.DAY, CandleInterval.MIN_30)
    ) == 50


def test_attention_levels_are_stable_at_every_boundary() -> None:
    assert attention_level(0) == "未命中"
    assert attention_level(1) == "短线提示"
    assert attention_level(19) == "短线提示"
    assert attention_level(20) == "观察"
    assert attention_level(39) == "观察"
    assert attention_level(40) == "重点观察"
    assert attention_level(59) == "重点观察"
    assert attention_level(60) == "强烈关注"
    assert attention_level(79) == "强烈关注"
    assert attention_level(80) == "超级共振"
    assert attention_level(100) == "超级共振"


def test_signal_and_interval_labels_hide_legacy_jargon() -> None:
    assert signal_label("AAA") == "近期底背离"
    assert signal_label("BBB") == "跨波段底背离"
    assert signal_label("AAA+BBB") == "双重底背离"
    assert signal_label("RECENT_BULLISH_DIVERGENCE") == "近期底背离"
    assert signal_label("MULTI_SWING_BULLISH_DIVERGENCE") == "跨波段底背离"
    assert signal_label("CONFIRMED_BULLISH_DIVERGENCE") == "双重底背离"
    assert signal_label("CD_LEFT_ENTRY") == "CD"
    assert normalize_signal_code("AAA") == "RECENT_BULLISH_DIVERGENCE"
    assert normalize_signal_code("BBB") == "MULTI_SWING_BULLISH_DIVERGENCE"
    assert normalize_signal_code("AAA+BBB") == "CONFIRMED_BULLISH_DIVERGENCE"
    assert interval_label(CandleInterval.MIN_240) == "4 小时"
    assert interval_label(CandleInterval.WEEK) == "周线"


def test_conclusion_is_local_deterministic_and_uses_attention_wording() -> None:
    conclusion = attention_conclusion(
        (
            CandleInterval.MIN_60,
            CandleInterval.MIN_240,
            CandleInterval.DAY,
        ),
        ("CONFIRMED_BULLISH_DIVERGENCE",),
    )

    assert conclusion == (
        "日线、4 小时和1 小时共同命中，包含双重底背离；"
        "中长周期证据较完整，列为超级共振。"
    )
    assert "买入" not in conclusion
    assert "AAA" not in conclusion
