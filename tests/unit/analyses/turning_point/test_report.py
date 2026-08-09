from stock_toolbox.analyses.turning_point.application.report import (
    DISCLAIMER,
    PROMPT_VERSION,
    build_report_payload,
    system_prompt,
)


def test_report_payload_uses_aggregated_frozen_evidence() -> None:
    payload = build_report_payload(
        {
            "algorithm_version": "turning-point-v2",
            "watchlist_name": "科技观察",
            "request": {
                "requested_end_date": "2026-07-24",
                "intervals": ["30m", "1d", "1w"],
            },
            "results": [
                {
                    "symbol": "IREN.US",
                    "company_name": "IREN",
                    "classification_name": "AI 数据中心",
                    "period_results": [
                        {
                            "interval": "30m",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_kind": "AAA",
                            "quality_score": 60,
                            "volume_ratio": 1.2,
                        },
                        {
                            "interval": "1d",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_kind": "CONFIRMED_BULLISH_DIVERGENCE",
                            "quality_score": 88,
                            "volume_ratio": 1.5,
                        },
                        {
                            "interval": "1w",
                            "decision": "FAILED",
                            "reason": "provider_error",
                        },
                    ],
                }
            ],
        }
    )

    assert payload["prompt_version"] == PROMPT_VERSION
    assert payload["summary"]["matched_count"] == 1
    assert payload["summary"]["failure_count"] == 1
    assert payload["results"][0]["attention_score"] == 32
    assert payload["results"][0]["matched_intervals"] == ["30m", "1d"]
    assert "AAA" not in str(payload)
    assert "BBB" not in str(payload)


def test_prompt_prioritizes_long_period_resonance_and_forbids_trade_advice() -> None:
    prompt = system_prompt()

    assert "日线和周线" in prompt
    assert "多周期" in prompt
    assert "全部所选周期" in prompt
    assert "不得重算" in prompt
    assert "目标价" in prompt
    assert "最值得复盘的前三只" in prompt
    assert "单个中长周期强信号" in prompt
    assert "右侧确认与信号新鲜度" in prompt
    assert DISCLAIMER in prompt


def test_prompt_explains_frozen_alignment_evidence_without_rescoring() -> None:
    prompt = system_prompt("RIGHT_CONFIRMED")

    assert "时间对齐" in prompt
    assert "评分拆解" in prompt
    assert "不重新评分" in prompt


def test_left_cd_report_explains_early_signal_without_claiming_reversal() -> None:
    payload = build_report_payload(
        {
            "request": {
                "requested_end_date": "2026-07-24",
                "intervals": ["1d"],
                "trade_side": "LEFT_CD",
            },
            "results": [
                {
                    "symbol": "IREN.US",
                    "period_results": [
                        {
                            "interval": "1d",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_kind": "CD_LEFT_ENTRY",
                        }
                    ],
                }
            ],
        }
    )

    assert payload["trade_side"] == "LEFT_CD"
    assert payload["trade_side_label"] == "左侧 · CD"
    assert "不代表已经反转" in system_prompt("LEFT_CD")
    assert "首次成立" in system_prompt("LEFT_CD")
    assert "增强确认" in system_prompt("LEFT_CD")
    assert "均线确认" in system_prompt("RIGHT_CONFIRMED")
    assert "20 根" in system_prompt("RIGHT_CONFIRMED")


def test_report_payload_describes_the_current_attention_weights() -> None:
    payload = build_report_payload(
        {
            "request": {"intervals": ["1w"], "trade_side": "RIGHT_CONFIRMED"},
            "results": [],
        }
    )

    assert PROMPT_VERSION == "turning-point-report-v6"
    assert payload["score_semantics"]["base_points"] == {
        "30m": 5,
        "1h": 10,
        "2h": 25,
        "4h": 35,
        "1d": 45,
        "1w": 55,
    }
    assert payload["score_semantics"]["right_confirmation"] == 10
