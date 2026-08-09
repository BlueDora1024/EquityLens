"""Deterministic user-facing semantics for turning-point evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from stock_toolbox.core.market_data.models import CandleInterval

RECENT_BULLISH_DIVERGENCE = "RECENT_BULLISH_DIVERGENCE"
MULTI_SWING_BULLISH_DIVERGENCE = "MULTI_SWING_BULLISH_DIVERGENCE"
CONFIRMED_BULLISH_DIVERGENCE = "CONFIRMED_BULLISH_DIVERGENCE"
CD_LEFT_ENTRY = "CD_LEFT_ENTRY"

_INTERVAL_SCORES = {
    CandleInterval.MIN_30: 5,
    CandleInterval.MIN_60: 10,
    CandleInterval.MIN_120: 25,
    CandleInterval.MIN_240: 35,
    CandleInterval.DAY: 45,
    CandleInterval.WEEK: 55,
}
_INTERVAL_LABELS = {
    CandleInterval.MIN_30: "30 分钟",
    CandleInterval.MIN_60: "1 小时",
    CandleInterval.MIN_120: "2 小时",
    CandleInterval.MIN_240: "4 小时",
    CandleInterval.DAY: "日线",
    CandleInterval.WEEK: "周线",
}
_SIGNAL_LABELS = {
    "AAA": "近期底背离",
    "BBB": "跨波段底背离",
    "AAA+BBB": "双重底背离",
    RECENT_BULLISH_DIVERGENCE: "近期底背离",
    MULTI_SWING_BULLISH_DIVERGENCE: "跨波段底背离",
    CONFIRMED_BULLISH_DIVERGENCE: "双重底背离",
    CD_LEFT_ENTRY: "CD",
}
_LEGACY_SIGNAL_CODES = {
    "AAA": RECENT_BULLISH_DIVERGENCE,
    "BBB": MULTI_SWING_BULLISH_DIVERGENCE,
    "AAA+BBB": CONFIRMED_BULLISH_DIVERGENCE,
}

_NEW_YORK = ZoneInfo("America/New_York")
_RESONANCE_RULES = (
    (CandleInterval.MIN_30, CandleInterval.MIN_60, 5),
    (CandleInterval.MIN_60, CandleInterval.MIN_120, 10),
    (CandleInterval.MIN_120, CandleInterval.MIN_240, 20),
    (CandleInterval.MIN_240, CandleInterval.DAY, 15),
    (CandleInterval.DAY, CandleInterval.WEEK, 20),
)


@dataclass(frozen=True, slots=True)
class AttentionEvidence:
    """One matched period with its user-facing CD completion time."""

    interval: CandleInterval
    signal_at: datetime
    right_confirmed: bool = False

    def __post_init__(self) -> None:
        if self.signal_at.tzinfo is None:
            raise ValueError("signal_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AttentionScore:
    base_points: int
    resonance_points: int
    confirmation_points: int
    total: int
    resonance_pairs: tuple[str, ...] = ()


def interval_label(interval: CandleInterval) -> str:
    return _INTERVAL_LABELS[interval]


def signal_label(signal_code: str | None) -> str:
    if not signal_code:
        return "未识别"
    normalized = normalize_signal_code(signal_code)
    return _SIGNAL_LABELS.get(normalized or "", "底背离")


def normalize_signal_code(signal_code: str | None) -> str | None:
    if not signal_code:
        return None
    return _LEGACY_SIGNAL_CODES.get(signal_code, signal_code)


def attention_score(intervals: Iterable[CandleInterval]) -> int:
    unique = tuple(dict.fromkeys(intervals))
    if not unique:
        return 0
    return min(100, sum(_INTERVAL_SCORES[item] for item in unique))


def legacy_attention_score(intervals: Iterable[CandleInterval]) -> int:
    """Keep pre-v6 histories readable without silently changing their priority."""
    legacy_weights = {
        CandleInterval.MIN_30: 5,
        CandleInterval.MIN_60: 8,
        CandleInterval.MIN_120: 12,
        CandleInterval.MIN_240: 18,
        CandleInterval.DAY: 25,
        CandleInterval.WEEK: 32,
    }
    unique = tuple(dict.fromkeys(intervals))
    if not unique:
        return 0
    base = sum(legacy_weights[item] for item in unique)
    return min(100, round(base * (1.0 + 0.05 * (len(unique) - 1))))


def attention_score_for_evidence(
    evidence: Iterable[AttentionEvidence],
) -> AttentionScore:
    """Score matched periods only when adjacent signals are time-aligned."""
    latest_by_interval: dict[CandleInterval, AttentionEvidence] = {}
    for item in evidence:
        previous = latest_by_interval.get(item.interval)
        if previous is None or item.signal_at > previous.signal_at:
            latest_by_interval[item.interval] = item
    unique = tuple(latest_by_interval.values())
    base_points = attention_score(item.interval for item in unique)
    resonance_points = 0
    resonance_pairs: list[str] = []
    for lower, higher, bonus in _RESONANCE_RULES:
        first = latest_by_interval.get(lower)
        second = latest_by_interval.get(higher)
        if first is None or second is None:
            continue
        if _signals_align(lower, higher, first.signal_at, second.signal_at):
            resonance_points += bonus
            resonance_pairs.append(f"{interval_label(lower)} + {interval_label(higher)}")
    confirmation_points = 10 if any(item.right_confirmed for item in unique) else 0
    return AttentionScore(
        base_points=base_points,
        resonance_points=resonance_points,
        confirmation_points=confirmation_points,
        total=min(100, base_points + resonance_points + confirmation_points),
        resonance_pairs=tuple(resonance_pairs),
    )


def attention_level(score: int) -> str:
    if score <= 0:
        return "未命中"
    if score < 20:
        return "短线提示"
    if score < 40:
        return "观察"
    if score < 60:
        return "重点观察"
    if score < 80:
        return "强烈关注"
    return "超级共振"


def attention_conclusion(
    intervals: Iterable[CandleInterval],
    signal_codes: Iterable[str],
    *,
    score: int | None = None,
) -> str:
    unique = tuple(dict.fromkeys(intervals))
    resolved_score = attention_score(unique) if score is None else score
    if not unique:
        return "所选周期均未命中，暂不列入复盘关注。"
    ordered = sorted(unique, key=lambda item: _INTERVAL_SCORES[item], reverse=True)
    period_text = _join_chinese(tuple(interval_label(item) for item in ordered))
    period_phrase = (
        f"{period_text}共同命中"
        if len(ordered) > 1
        else f"{period_text}命中"
    )
    labels = tuple(dict.fromkeys(signal_label(item) for item in signal_codes))
    signal_phrase = f"，包含{_join_chinese(labels)}" if labels else ""
    has_longer_evidence = any(
        item in {CandleInterval.MIN_240, CandleInterval.DAY, CandleInterval.WEEK}
        for item in unique
    )
    if len(unique) >= 2 and has_longer_evidence:
        evidence = "中长周期证据较完整"
    elif len(unique) >= 2:
        evidence = "多个短周期形成共振"
    elif has_longer_evidence:
        evidence = "已有中长周期信号，仍需后续确认"
    else:
        evidence = "仅有短周期信号，噪音相对较高"
    return (
        f"{period_phrase}{signal_phrase}；{evidence}，"
        f"列为{attention_level(resolved_score)}。"
    )


def _join_chinese(values: tuple[str, ...]) -> str:
    if len(values) <= 1:
        return values[0] if values else ""
    return "、".join(values[:-1]) + "和" + values[-1]


def _signals_align(
    lower: CandleInterval,
    higher: CandleInterval,
    first: datetime,
    second: datetime,
) -> bool:
    difference = abs(first - second)
    pair = (lower, higher)
    if pair == (CandleInterval.MIN_30, CandleInterval.MIN_60):
        return difference <= timedelta(hours=2)
    if pair == (CandleInterval.MIN_60, CandleInterval.MIN_120):
        return difference <= timedelta(hours=4)
    if pair == (CandleInterval.MIN_120, CandleInterval.MIN_240):
        return _business_days_apart(first, second) <= 1
    if pair == (CandleInterval.MIN_240, CandleInterval.DAY):
        return _business_days_apart(first, second) <= 2
    if pair == (CandleInterval.DAY, CandleInterval.WEEK):
        return _business_days_apart(first, second) <= 10
    return False


def _business_days_apart(first: datetime, second: datetime) -> int:
    start, end = sorted(
        (first.astimezone(_NEW_YORK).date(), second.astimezone(_NEW_YORK).date())
    )
    days = 0
    while start < end:
        start += timedelta(days=1)
        if start.weekday() < 5:
            days += 1
    return days
