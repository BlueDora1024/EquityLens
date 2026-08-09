from __future__ import annotations

import pytest

from stock_toolbox.analyses.extreme_deviation.application.report import (
    DISCLAIMER,
    PROMPT_VERSION,
    build_report_payload,
    system_prompt,
)


def _history_payload() -> dict[str, object]:
    return {
        "algorithm_version": "extreme-deviation-v1",
        "watchlist_name": "Tech",
        "api_key": "must-not-leak",
        "raw_candles": [{"close": 1}],
        "results": [
            {
                "symbol": "IREN.US",
                "company_name": "IREN",
                "classification_name": "AI 数据中心",
                "consensus": {"kind": "BUY_RESONANCE", "score": -84},
                "periods": [
                    {
                        "interval": "1d",
                        "candle_count": 650,
                        "error_code": None,
                        "score": {
                            "score": -82,
                            "label": "超级买入观察",
                            "confidence": "FULL",
                            "buy_severity": 82,
                            "sell_severity": 8,
                            "buy_percentile": 97.5,
                            "sell_percentile": 42.0,
                            "range_position": 0.08,
                            "buy_deviation": 0.08,
                            "sell_deviation": 0.0,
                            "buy_trigger_age": 1,
                            "sell_trigger_age": None,
                            "latest_at": "2026-07-24T20:00:00+00:00",
                        },
                        "chart_points": [
                            {
                                "timestamp": "2026-07-20T20:00:00+00:00",
                                "open": 10,
                                "high": 11,
                                "low": 9,
                                "close": 10,
                                "score": -72,
                                "label": "买入观察",
                            },
                            {
                                "timestamp": "2026-07-21T20:00:00+00:00",
                                "open": 10,
                                "high": 12,
                                "low": 9,
                                "close": 11,
                                "score": -88,
                                "label": "超级买入观察",
                            },
                            {
                                "timestamp": "2026-07-22T20:00:00+00:00",
                                "open": 11,
                                "high": 12,
                                "low": 10,
                                "close": 11,
                                "score": -65,
                                "label": "买入观察",
                            },
                        ],
                    }
                ],
            },
            {
                "symbol": "NVDA.US",
                "company_name": "NVIDIA",
                "classification_name": "半导体",
                "consensus": {"kind": "NEUTRAL", "score": 0},
                "periods": [],
            },
        ],
    }


def test_report_payload_is_a_strict_selected_result_whitelist() -> None:
    payload = build_report_payload(_history_payload(), ("IREN.US",))
    rendered = repr(payload)

    assert payload["prompt_version"] == PROMPT_VERSION
    assert payload["results"][0]["symbol"] == "IREN.US"
    assert "NVDA.US" not in rendered
    assert "must-not-leak" not in rendered
    assert "raw_candles" not in rendered
    assert "api_key" not in rendered
    period = payload["results"][0]["periods"][0]
    assert payload["results"][0]["consensus"]["attention_score"] == 84
    assert period["attention_score"] == 82
    assert period["buy_severity"] == 82
    assert period["buy_percentile"] == 97.5
    assert period["range_position"] == 0.08
    assert period["recent_extremes"] == [
        {
            "timestamp": "2026-07-21T20:00:00+00:00",
            "score": -88,
            "label": "超级买入观察",
        }
    ]
    assert "open" not in rendered
    assert "high" not in rendered
    assert "low" not in rendered
    assert "close" not in rendered


def test_report_rejects_more_than_20_symbols() -> None:
    with pytest.raises(ValueError, match="20"):
        build_report_payload(
            _history_payload(),
            tuple(f"S{index}.US" for index in range(21)),
        )


def test_system_prompt_explains_one_security_with_recent_extremes() -> None:
    prompt = system_prompt()
    assert PROMPT_VERSION == "extreme-deviation-report-v2"
    assert "当前方向与关注强度" in prompt
    assert "最强周期及具体依据" in prompt
    assert "近期极值脉冲" in prompt
    assert "当前中性" in prompt
    assert "单个日线或周线" in prompt
    assert "不得修改评分" in prompt
    assert DISCLAIMER in prompt
