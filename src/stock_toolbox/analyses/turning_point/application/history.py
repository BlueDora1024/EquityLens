"""Backward-compatible projection of turning-point history payloads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, cast

from stock_toolbox.analyses.turning_point.domain.attention import (
    attention_conclusion,
    attention_level,
    interval_label,
    legacy_attention_score,
    normalize_signal_code,
    signal_label,
)
from stock_toolbox.core.market_data.models import CandleInterval


def project_turning_point_history(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    request = payload.get("request", {})
    request = request if isinstance(request, Mapping) else {}
    trade_side = str(request.get("trade_side", "RIGHT_CONFIRMED"))
    trade_side_label = (
        "左侧 · CD"
        if trade_side == "LEFT_CD"
        else "右侧 · 均线确认"
    )
    selected_intervals = _selected_intervals(payload)
    rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    failure_count = 0
    raw_results = payload.get("results", [])
    if not isinstance(raw_results, (list, tuple)):
        raw_results = []
    for raw_result in raw_results:
        if not isinstance(raw_result, Mapping):
            continue
        periods = _period_results(raw_result, selected_intervals)
        failure_count += sum(
            item["decision"] == "FAILED" for item in periods
        )
        matched = tuple(
            item for item in periods if item["decision"] == "MATCHED"
        )
        if not matched:
            unmatched.append(
                {
                    "symbol": str(raw_result.get("symbol", "")),
                    "company_name": str(raw_result.get("company_name", "")),
                    "classification_name": str(
                        raw_result.get("classification_name", "未分类")
                        or "未分类"
                    ),
                    "status": str(raw_result.get("status", "READY")),
                    "period_results": periods,
                }
            )
            continue
        matched_intervals = tuple(
            CandleInterval(str(item["interval"])) for item in matched
        )
        signal_codes = tuple(
            str(item["signal_kind"])
            for item in matched
            if item.get("signal_kind")
        )
        frozen_breakdown = _frozen_breakdown(raw_result, payload)
        score = (
            int(cast(str | int | float, frozen_breakdown["total"]))
            if frozen_breakdown is not None
            else legacy_attention_score(matched_intervals)
        )
        rows.append(
            {
                "symbol": str(raw_result.get("symbol", "")),
                "company_name": str(
                    raw_result.get("company_name", "")
                ),
                "classification_name": str(
                    raw_result.get("classification_name", "未分类")
                    or "未分类"
                ),
                "matched_intervals": [
                    item.value for item in matched_intervals
                ],
                "matched_period_labels": [
                    interval_label(item) for item in matched_intervals
                ],
                "signal_labels": list(
                    dict.fromkeys(signal_label(item) for item in signal_codes)
                ),
                "attention_score": score,
                "attention_level": attention_level(score),
                "score_breakdown": frozen_breakdown,
                "conclusion": attention_conclusion(
                    matched_intervals,
                    signal_codes,
                    score=score,
                ),
                "status": str(raw_result.get("status", "READY")),
                "market_value_usd": _optional_int(
                    raw_result.get("market_value_usd")
                ),
                "risk_flags": _risk_flags(raw_result.get("risk_flags")),
                "period_results": periods,
            }
        )
    rows.sort(
        key=lambda item: (
            -int(item["attention_score"]),
            str(item["symbol"]),
        )
    )
    return {
        "trade_side": trade_side,
        "trade_side_label": trade_side_label,
        "selected_intervals": [
            interval.value for interval in selected_intervals
        ],
        "total_count": len(raw_results),
        "matched_count": len(rows),
        "unmatched_count": len(unmatched),
        "failure_count": failure_count,
        "rows": rows,
        "unmatched": unmatched,
    }


def _selected_intervals(
    payload: Mapping[str, Any],
) -> tuple[CandleInterval, ...]:
    request = payload.get("request", {})
    request = request if isinstance(request, Mapping) else {}
    raw_intervals = request.get("intervals")
    if not isinstance(raw_intervals, (list, tuple)):
        raw_interval = request.get("interval")
        raw_intervals = [raw_interval] if raw_interval else []
    selected: list[CandleInterval] = []
    for raw in raw_intervals:
        try:
            interval = CandleInterval(str(raw))
        except ValueError:
            continue
        if interval not in selected:
            selected.append(interval)
    return tuple(selected)


def _period_results(
    result: Mapping[str, Any],
    selected_intervals: tuple[CandleInterval, ...],
) -> list[dict[str, Any]]:
    raw_periods = result.get("period_results")
    if isinstance(raw_periods, (list, tuple)):
        candidates = raw_periods
    else:
        interval = selected_intervals[0] if selected_intervals else None
        candidates = [{**result, "interval": interval.value if interval else ""}]
    periods: list[dict[str, Any]] = []
    for raw_period in candidates:
        if not isinstance(raw_period, Mapping):
            continue
        try:
            interval = CandleInterval(str(raw_period.get("interval", "")))
        except ValueError:
            continue
        code = normalize_signal_code(
            str(raw_period["signal_kind"])
            if raw_period.get("signal_kind")
            else None
        )
        periods.append(
            {
                "interval": interval.value,
                "interval_label": interval_label(interval),
                "decision": str(raw_period.get("decision", "")),
                "reason": str(raw_period.get("reason", "")),
                "reason_label": _reason_label(
                    str(raw_period.get("reason", "")),
                    str(raw_period.get("decision", "")),
                ),
                "signal_kind": code,
                "signal_label": signal_label(code) if code else "",
                "signal_at": _bar_end_timestamp(
                    raw_period.get("signal_at"), interval
                ),
                "enhanced_at": _bar_end_timestamp(
                    raw_period.get("enhanced_at"), interval
                ),
                "crossed_at": _bar_end_timestamp(
                    raw_period.get("crossed_at"), interval
                ),
                "last_price": raw_period.get("last_price"),
                "volume_ratio": raw_period.get("volume_ratio"),
                "quality_score": raw_period.get("quality_score"),
            }
        )
    return periods


_INTRADAY_BAR_LENGTH = {
    CandleInterval.MIN_30: timedelta(minutes=30),
    CandleInterval.MIN_60: timedelta(minutes=60),
    CandleInterval.MIN_120: timedelta(minutes=120),
    CandleInterval.MIN_240: timedelta(minutes=240),
}


def _bar_end_timestamp(value: object, interval: CandleInterval) -> object:
    """Project provider bar-start timestamps to user-facing close times."""
    delta = _INTRADAY_BAR_LENGTH.get(interval)
    if value is None or delta is None:
        return value
    if isinstance(value, datetime):
        return value + delta
    if not isinstance(value, str):
        return value
    try:
        shifted = datetime.fromisoformat(value) + delta
    except ValueError:
        return value
    return shifted.isoformat()


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _risk_flags(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        str(item)
        for item in value
        if item in {"SMALL_MARKET_CAP", "MARKET_VALUE_UNKNOWN"}
    ]


def _reason_label(reason: str, decision: str) -> str:
    if decision == "MATCHED":
        return "已命中"
    labels = {
        "NO_CD_SIGNAL": "没有出现 CD 底背离信号",
        "signal_not_met": "没有出现 CD 底背离信号",
        "CD_AWAITING_CONFIRMATION": "已有 CD，尚未向上站上确认均线",
        "cross_not_met": "已有 CD，尚未向上站上确认均线",
        "CROSS_WITHOUT_DIVERGENCE": "价格上穿均线，但此前没有 CD 底背离",
        "TREND_FILTER_NOT_MET": "CD 出现时尚未处于均线弱势结构",
        "trend_not_met": "CD 出现时尚未处于均线弱势结构",
        "SIGNAL_EXPIRED": "CD 与均线确认间隔过长，信号已过期",
        "insufficient_bars": "历史 K 线不足，无法可靠判断",
        "insufficient_quant_history": "历史 K 线不足，无法可靠判断",
        "malformed_data": "行情数据不完整",
        "malformed_quant_response": "行情数据不完整",
        "market_value_filter": "未通过旧版市值筛选",
    }
    if reason in labels:
        return labels[reason]
    if decision == "FAILED":
        return "行情数据暂不可用"
    return "当前周期未满足筛选条件"


def _frozen_breakdown(
    result: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, object] | None:
    raw = result.get("attention_breakdown")
    if not isinstance(raw, Mapping):
        return None
    expected = ("base_points", "resonance_points", "confirmation_points", "total")
    if any(isinstance(raw.get(key), bool) or not isinstance(raw.get(key), int) for key in expected):
        return None
    raw_pairs = raw.get("resonance_pairs", ())
    pairs = (
        [str(item) for item in raw_pairs]
        if isinstance(raw_pairs, (list, tuple))
        else []
    )
    version = str(payload.get("algorithm_version", "turning-point-v7"))
    return {
        "base_points": int(raw["base_points"]),
        "resonance_points": int(raw["resonance_points"]),
        "confirmation_points": int(raw["confirmation_points"]),
        "total": int(raw["total"]),
        "resonance_pairs": pairs,
        "version": version,
    }
