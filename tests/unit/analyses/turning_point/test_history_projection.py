from stock_toolbox.analyses.turning_point.application.history import (
    project_turning_point_history,
)


def test_projects_legacy_flat_history_without_developer_jargon() -> None:
    projected = project_turning_point_history(
        {
            "request": {"interval": "1d"},
            "results": [
                {
                    "symbol": "IREN.US",
                    "decision": "MATCHED",
                    "reason": "matched",
                    "signal_kind": "AAA+BBB",
                    "quality_score": 81,
                },
                {
                    "symbol": "NVDA.US",
                    "decision": "NOT_MATCHED",
                    "reason": "signal_not_met",
                },
            ],
        }
    )

    assert projected["selected_intervals"] == ["1d"]
    assert projected["trade_side"] == "RIGHT_CONFIRMED"
    assert projected["trade_side_label"] == "右侧 · 均线确认"
    assert projected["total_count"] == 2
    assert projected["matched_count"] == 1
    assert projected["unmatched_count"] == 1
    assert projected["failure_count"] == 0
    row = projected["rows"][0]
    assert row["symbol"] == "IREN.US"
    assert row["matched_intervals"] == ["1d"]
    assert row["signal_labels"] == ["双重底背离"]
    assert row["attention_score"] == 25
    assert row["attention_level"] == "观察"
    assert "AAA" not in str(projected)
    assert projected["unmatched"][0]["period_results"][0][
        "reason_label"
    ] == "没有出现 CD 底背离信号"


def test_projects_new_history_one_row_per_match_in_score_order() -> None:
    projected = project_turning_point_history(
        {
            "request": {"intervals": ["30m", "1d", "1w"]},
            "results": [
                {
                    "symbol": "AMD.US",
                    "company_name": "超威半导体",
                    "classification_name": "半导体",
                    "period_results": [
                        {
                            "interval": "30m",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_kind": "RECENT_BULLISH_DIVERGENCE",
                        },
                        {
                            "interval": "1d",
                            "decision": "NOT_MATCHED",
                            "reason": "signal_not_met",
                        },
                        {
                            "interval": "1w",
                            "decision": "FAILED",
                            "reason": "provider_error",
                        },
                    ],
                },
                {
                    "symbol": "IREN.US",
                    "company_name": "IREN",
                    "classification_name": "AI 数据中心",
                    "period_results": [
                        {
                            "interval": "30m",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_kind": "RECENT_BULLISH_DIVERGENCE",
                        },
                        {
                            "interval": "1d",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_kind": "CONFIRMED_BULLISH_DIVERGENCE",
                        },
                        {
                            "interval": "1w",
                            "decision": "NOT_MATCHED",
                            "reason": "signal_not_met",
                        },
                    ],
                },
            ],
        }
    )

    assert projected["matched_count"] == 2
    assert projected["failure_count"] == 1
    assert projected["unmatched_count"] == 0
    assert [row["symbol"] for row in projected["rows"]] == [
        "IREN.US",
        "AMD.US",
    ]
    assert projected["rows"][0]["matched_intervals"] == ["30m", "1d"]
    assert projected["rows"][0]["attention_score"] == 32
    assert projected["rows"][1]["attention_score"] == 5


def test_projects_frozen_v6_score_breakdown_without_recalculation() -> None:
    projected = project_turning_point_history(
        {
            "algorithm_version": "turning-point-v6",
            "request": {"intervals": ["120m", "240m"]},
            "results": [
                {
                    "symbol": "IREN.US",
                    "attention_score": 80,
                    "attention_level": "超级共振",
                    "attention_breakdown": {
                        "base_points": 56,
                        "resonance_points": 24,
                        "confirmation_points": 0,
                        "total": 80,
                        "resonance_pairs": ["2 小时 + 4 小时"],
                    },
                    "period_results": [
                        {
                            "interval": "120m",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_at": "2026-07-29T21:30:00+00:00",
                        },
                        {
                            "interval": "240m",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_at": "2026-07-30T01:30:00+00:00",
                        },
                    ],
                }
            ],
        }
    )

    row = projected["rows"][0]
    assert row["attention_score"] == 80
    assert row["attention_level"] == "超级共振"
    assert row["score_breakdown"] == {
        "base_points": 56,
        "resonance_points": 24,
        "confirmation_points": 0,
        "total": 80,
        "resonance_pairs": ["2 小时 + 4 小时"],
        "version": "turning-point-v6",
    }


def test_projects_left_cd_trade_side_and_signal() -> None:
    projected = project_turning_point_history(
        {
            "request": {
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

    assert projected["trade_side"] == "LEFT_CD"
    assert projected["trade_side_label"] == "左侧 · CD"
    assert projected["rows"][0]["signal_labels"] == ["CD"]


def test_projects_market_value_and_ignores_retired_250d_history_fields() -> None:
    projected = project_turning_point_history(
        {
            "request": {"intervals": ["1d"]},
            "results": [
                {
                    "symbol": "IREN.US",
                    "market_value_usd": 1_900_000_000,
                    "return_250d": -0.125,
                    "risk_flags": [
                        "SMALL_MARKET_CAP",
                        "WEAK_250D_RETURN",
                    ],
                    "risk_annotation_status": "READY",
                    "period_results": [
                        {
                            "interval": "1d",
                            "decision": "MATCHED",
                            "reason": "matched",
                        }
                    ],
                },
                {
                    "symbol": "AMD.US",
                    "period_results": [
                        {
                            "interval": "1d",
                            "decision": "MATCHED",
                            "reason": "matched",
                        }
                    ],
                },
            ],
        }
    )

    rows = {row["symbol"]: row for row in projected["rows"]}
    assert rows["IREN.US"]["market_value_usd"] == 1_900_000_000
    assert rows["IREN.US"]["risk_flags"] == ["SMALL_MARKET_CAP"]
    assert "return_250d" not in rows["IREN.US"]
    assert "risk_annotation_status" not in rows["IREN.US"]
    assert rows["AMD.US"]["market_value_usd"] is None
    assert rows["AMD.US"]["risk_flags"] == []


def test_projects_intraday_signal_timestamps_as_bar_end_times() -> None:
    projected = project_turning_point_history(
        {
            "request": {"intervals": ["30m"]},
            "results": [
                {
                    "symbol": "IREN.US",
                    "period_results": [
                        {
                            "interval": "30m",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_at": "2026-07-28T14:00:00+00:00",
                            "enhanced_at": "2026-07-28T14:30:00+00:00",
                            "crossed_at": "2026-07-28T15:00:00+00:00",
                        }
                    ],
                }
            ],
        }
    )

    period = projected["rows"][0]["period_results"][0]
    assert period["signal_at"] == "2026-07-28T14:30:00+00:00"
    assert period["enhanced_at"] == "2026-07-28T15:00:00+00:00"
    assert period["crossed_at"] == "2026-07-28T15:30:00+00:00"


def test_daily_signal_timestamp_keeps_its_trading_date() -> None:
    projected = project_turning_point_history(
        {
            "request": {"intervals": ["1d"]},
            "results": [
                {
                    "symbol": "IREN.US",
                    "period_results": [
                        {
                            "interval": "1d",
                            "decision": "MATCHED",
                            "reason": "matched",
                            "signal_at": "2026-07-28T00:00:00+00:00",
                        }
                    ],
                }
            ],
        }
    )

    period = projected["rows"][0]["period_results"][0]
    assert period["signal_at"] == "2026-07-28T00:00:00+00:00"
