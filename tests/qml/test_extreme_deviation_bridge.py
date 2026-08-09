from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event

import pytest

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationProgress,
    ExtremeDeviationRunResult,
    ExtremeDeviationRunStatus,
)
from stock_toolbox.analyses.extreme_deviation.application.report import (
    TechnicalReport,
)
from stock_toolbox.analyses.resource_budget import AnalysisBudgetSnapshot
from stock_toolbox.composition import build_application
from stock_toolbox.core.operations.failure_policy import (
    AnalysisReliability,
    FailureCode,
)
from stock_toolbox.core.operations.registry import CancelResult
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback
from stock_toolbox.core.operations.storage_guard import StorageState
from stock_toolbox.desktop_qml.extreme_deviation_bridge import (
    ExtremeDeviationBridge,
    _payload_rows,
    _security_option_name,
)
from stock_toolbox.desktop_qml.failure_presentation import FailureState
from stock_toolbox.infrastructure.ai.openai_compatible import AIAdapterError
from stock_toolbox.runtime.environment import RuntimeEnvironment
from tests.qml.helpers import seeded_watchlist


def test_extreme_bridge_loads_global_securities_and_freezes_one_security(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    assert bridge.active_concurrency == 4

    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    request = bridge.build_request()

    assert request is not None
    assert request.watchlist_id == ""
    assert request.security_id == watchlist.memberships[0].security_id
    assert request.requested_end_date.isoformat() == "2026-07-24"
    assert request.selected_symbols == ()
    assert bridge.member_count == 1
    assert len(request.intervals) == 4
    assert bridge.combination_count == 4
    assert bridge.securities_loading is False
    assert bridge.calendar_loading is False
    assert bridge.date_resolution_text == "已确认完整交易日"


def test_extreme_bridge_refreshes_securities_when_reentering_run_page(
    qtbot,
    scenario_application,
) -> None:
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    assert bridge.securities_loaded is True
    assert bridge.securities == []

    scenario_application.import_securities("IREN")

    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        assert bridge.prepare_new_run() is True

    assert [item["symbol"] for item in bridge.securities] == ["IREN.US"]


def test_extreme_bridge_requests_only_user_selected_periods(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")

    assert bridge.set_interval_selected("60m", False) is True
    assert bridge.set_interval_selected("1w", False) is True
    request = bridge.build_request()

    assert request is not None
    assert tuple(item.value for item in request.intervals) == ("30m", "1d")
    assert bridge.selected_interval_count == 2
    assert bridge.combination_count == 2


def test_extreme_process_worker_keeps_gui_path_isolated(
    qtbot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
    )
    watchlist = seeded_watchlist(application)
    bridge = ExtremeDeviationBridge(application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    monkeypatch.setenv("PYTHONPATH", str(Path.cwd() / "src"))
    worker = Path.cwd() / ".venv" / "bin" / "stock-toolbox"
    monkeypatch.setattr(bridge, "_worker_program", lambda: worker)
    monkeypatch.setattr(
        bridge,
        "_worker_arguments",
        lambda _request: [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "analysis",
            "extreme-deviation",
            "run-worker",
            "--security-id",
            watchlist.memberships[0].security_id,
            "--interval",
            "30m",
            "--end-date",
            "2026-07-24",
        ],
    )

    assert bridge.start() is True
    qtbot.waitUntil(
        lambda: bridge.requires_budget_confirmation or not bridge.running,
        timeout=15_000,
    )
    if bridge.requires_budget_confirmation:
        with qtbot.waitSignal(bridge.finished, timeout=15_000):
            assert bridge.confirm_budget_and_start() is True

    assert bridge.running is False
    assert bridge.terminal_has_usable_results is True
    assert bridge._task is None
    assert bridge._run_process is None
    application.close()


def test_extreme_process_stderr_is_drained(
    scenario_application,
) -> None:
    bridge = ExtremeDeviationBridge(scenario_application)

    class Process:
        def __init__(self) -> None:
            self.drained = False

        def readAllStandardError(self) -> bytes:
            self.drained = True
            return b"provider diagnostic\n"

    process = Process()
    bridge._run_process = process  # type: ignore[assignment]

    bridge._drain_run_process_error()

    assert process.drained is True


def test_extreme_process_quota_failure_is_not_presented_as_insufficient_data(
    scenario_application,
) -> None:
    bridge = ExtremeDeviationBridge(scenario_application)
    reliability = AnalysisReliability(
        0,
        4,
        0,
        Decimal(0),
        False,
        FailureCode.QUOTA_EXHAUSTED.value,
    )

    bridge._finish_process_run(
        ExtremeDeviationRunStatus.FAILED,
        "",
        "insufficient_reliable_results",
        reliability,
    )

    assert bridge.outcome_title == "服务配额已用完"


def test_extreme_progress_notifications_are_coalesced(
    qtbot,
    scenario_application,
) -> None:
    bridge = ExtremeDeviationBridge(scenario_application)
    notifications = 0

    def count_notification() -> None:
        nonlocal notifications
        notifications += 1

    bridge.changed.connect(count_notification)
    for completed in range(100):
        bridge._on_progress(
            ExtremeDeviationProgress(
                "FETCH_CANDLES",
                completed,
                100,
                f"S{completed}.US",
            )
        )

    assert notifications == 0
    qtbot.waitUntil(lambda: notifications == 1, timeout=1_000)


def test_extreme_security_option_does_not_repeat_a_matching_code() -> None:
    assert _security_option_name("CRCL.US", "CRCL") == "CRCL"
    assert _security_option_name("AMD.US", "超威半导体") == "AMD · 超威半导体"


def test_extreme_bridge_backtracks_non_trading_end_date(
    qtbot,
    scenario_application,
) -> None:
    bridge = ExtremeDeviationBridge(scenario_application)

    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-19")

    assert bridge.end_date == "2026-07-17"
    assert bridge.date_resolution_text == "所选日期休市，已回退至 2026-07-17"


def test_extreme_bridge_runs_and_exposes_symbol_detail(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")

    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        assert bridge.start() is True

    assert bridge.last_status in {"READY", "PARTIAL"}
    assert bridge.terminal_has_usable_results is True
    assert len(bridge.results) == 1
    assert bridge.select_symbol(str(bridge.results[0]["symbol"])) is True
    assert bridge.selected_detail["symbol"] == bridge.results[0]["symbol"]
    assert len(bridge.period_details) == 4
    assert len(bridge.history) == 1


def test_extreme_bridge_projects_single_security_runs_for_result_history(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        assert bridge.start() is True

    row = bridge.result_history[0]
    assert row["symbol"] == bridge.results[0]["symbol"]
    assert row["companyName"]
    assert row["completedAt"]
    assert row["summary"]
    assert row["status"] in {"完成", "部分完成"}


def test_extreme_bridge_prepares_a_blank_form_for_each_new_run(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    bridge._last_status = "PARTIAL"
    bridge._progress = 1.0
    bridge._active_stage = 5
    bridge._failure_state = FailureState(outcome_visible=True)
    bridge._results = [{"symbol": "IREN.US"}]

    assert bridge.prepare_new_run() is True

    assert bridge.selected_security_id == ""
    assert bridge.last_status == ""
    assert bridge.progress == 0.0
    assert bridge.active_stage == -1
    assert bridge.outcome_visible is False
    assert bridge.results == []


def test_extreme_period_status_uses_clear_completed_or_problem_copy() -> None:
    row = _payload_rows(
        [
            {
                "symbol": "IREN.US",
                "company_name": "IREN",
                "classification_name": "数据中心",
                "status": "PARTIAL",
                "consensus": {"kind": "NEUTRAL", "score": 0},
                "periods": [
                    {"interval": "30m", "error_code": "network"},
                ],
            }
        ]
    )[0]

    assert row["periods"][0]["status"] == "数据异常"


def test_extreme_payload_keeps_single_period_and_divergence_attention() -> None:
    single, divergence = _payload_rows(
        [
            {
                "symbol": "IREN.US",
                "consensus": {
                    "kind": "SINGLE_PERIOD_EXTREME",
                    "score": -88,
                    "attention_score": 88,
                },
                "periods": [],
            },
            {
                "symbol": "NVDA.US",
                "consensus": {
                    "kind": "PERIOD_DIVERGENCE",
                    "score": 0,
                    "attention_score": 91,
                },
                "periods": [],
            },
        ]
    )

    assert single["consensusLabel"] == "单周期极值"
    assert single["score"] == -88
    assert single["attentionScore"] == 88
    assert divergence["consensusLabel"] == "周期分歧"
    assert divergence["score"] == 0
    assert divergence["attentionScore"] == 91


def test_extreme_payload_visualizes_original_pressure_without_changing_scores() -> None:
    row = _payload_rows(
        [
            {
                "symbol": "AMD.US",
                "company_name": "AMD",
                "classification_name": "半导体",
                "status": "READY",
                "consensus": {"kind": "NEUTRAL", "score": 0},
                "periods": [
                    {
                        "interval": "1d",
                        "chart_points": [
                            {
                                "score": score,
                                "buy_pressure": buy,
                                "sell_pressure": sell,
                            }
                            for score, buy, sell in zip(
                                (60, 61, 63, 65, 95, -50, -52, -53, -89),
                                (2, 2.1, 2, 2.2, 48, 0, 0, 0, 0),
                                (0, 0, 0, 0, 0, 2, 2.1, 2, 36),
                                strict=True,
                            )
                        ],
                    }
                ],
            }
        ]
    )[0]

    chart_points = row["periods"][0]["chartPoints"]
    assert [point["score"] for point in chart_points] == [
        60,
        61,
        63,
        65,
        95,
        -50,
        -52,
        -53,
        -89,
    ]
    assert [point["buyVisualStrength"] for point in chart_points] == [
        0,
        0,
        0,
        0,
        100,
        0,
        0,
        0,
        0,
    ]
    assert [point["sellVisualStrength"] for point in chart_points] == [
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        100,
    ]


def test_extreme_payload_projects_intraday_bars_to_completion_time() -> None:
    row = _payload_rows(
        [
            {
                "symbol": "IREN.US",
                "consensus": {"kind": "NEUTRAL", "score": 0},
                "periods": [
                    {
                        "interval": "30m",
                        "chart_points": [
                            {
                                "timestamp": "2026-08-06T13:30:00+00:00",
                                "open": 1,
                                "high": 2,
                                "low": 0.5,
                                "close": 1.5,
                            }
                        ],
                    }
                ],
            }
        ]
    )[0]

    assert row["periods"][0]["chartPoints"][0]["timestamp"] == ("2026-08-06T14:00:00+00:00")


def test_extreme_bridge_generates_manual_report_and_exports_history(
    qtbot,
    scenario_application,
    tmp_path: Path,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        bridge.start()
    run_id = str(bridge.history[0]["runId"])

    bridge.set_report_symbol(str(bridge.results[0]["symbol"]), True)
    with qtbot.waitSignal(bridge.report_finished, timeout=5_000):
        assert bridge.generate_report() is True

    assert "技术指标复盘，不构成投资建议。" in bridge.report_text
    assert bridge.history[0]["reportCount"] == 1
    target = tmp_path / "extreme.md"
    assert bridge.export_history(run_id, "markdown", str(target)) is True
    assert "# 极值偏离结果" in target.read_text(encoding="utf-8")


def test_extreme_bridge_generates_report_for_selected_security_only(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        assert bridge.start() is True

    assert bridge.report_available is False
    with qtbot.waitSignal(bridge.report_finished, timeout=5_000):
        assert bridge.generate_selected_report() is True
    assert bridge.report_available is True
    assert "技术指标复盘，不构成投资建议。" in bridge.report_text


def test_extreme_report_failure_preserves_saved_report_and_run_state(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        assert bridge.start() is True
    bridge.set_report_symbol(str(bridge.results[0]["symbol"]), True)
    with qtbot.waitSignal(bridge.report_finished, timeout=5_000):
        assert bridge.generate_report() is True
    prior_report = bridge.report_text
    prior_results = bridge.results
    prior_status = bridge.last_status
    monkeypatch.setattr(
        type(scenario_application),
        "generate_extreme_deviation_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AIAdapterError("authentication_failed")),
    )

    with qtbot.waitSignal(bridge.report_finished, timeout=5_000):
        assert bridge.generate_report() is True

    assert bridge.report_text == prior_report
    assert bridge.results == prior_results
    assert bridge.last_status == prior_status
    assert bridge.report_error == "AI 授权失败，请检查 API Key。"


def test_extreme_report_is_close_safe_and_cancelable(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        assert bridge.start()
    bridge.set_report_symbol(str(bridge.results[0]["symbol"]), True)
    prior_results = bridge.results
    prior_status = bridge.last_status
    entered = Event()

    def blocked_report(
        _application,
        _run_id,
        _symbols,
        *,
        operation_control,
    ):
        entered.set()
        operation_control.wait_for_cancellation(5)
        raise AIAdapterError("canceled")

    monkeypatch.setattr(
        type(scenario_application),
        "generate_extreme_deviation_report",
        blocked_report,
    )

    assert bridge.generate_report()
    assert entered.wait(timeout=1)
    assert scenario_application.registry.has_active_operations()
    report_operation = scenario_application.registry.active_snapshots()[0]
    with qtbot.waitSignal(bridge.report_finished, timeout=2_000):
        assert (
            scenario_application.cancel_operation(report_operation.operation_id)
            is CancelResult.ACCEPTED
        )

    assert not scenario_application.registry.has_active_operations()
    assert bridge.results == prior_results
    assert bridge.last_status == prior_status
    assert bridge.report_error == "AI 解读已取消。"


def test_extreme_async_report_completion_stays_scoped_to_origin_run(
    scenario_application,
) -> None:
    bridge = ExtremeDeviationBridge(scenario_application)
    bridge._latest_run_id = "current-run"
    bridge._report_text = "当前历史的旧报告"
    bridge._report_error = "当前历史的旧错误"
    report = TechnicalReport(
        ("IREN.US",),
        "model",
        "prompt",
        "另一个历史的新报告",
        datetime(2026, 7, 25, tzinfo=UTC),
        "hash",
    )

    bridge._on_finished("report", ("another-run", report))
    assert bridge.report_text == "当前历史的旧报告"
    assert bridge.report_error == "当前历史的旧错误"

    bridge._on_finished(
        "report",
        ("another-run", AIAdapterError("rate_limited")),
    )
    assert bridge.report_text == "当前历史的旧报告"
    assert bridge.report_error == "当前历史的旧错误"


def test_extreme_failed_new_run_preserves_prior_result_and_report(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        assert bridge.start() is True
    bridge.set_report_symbol(str(bridge.results[0]["symbol"]), True)
    with qtbot.waitSignal(bridge.report_finished, timeout=5_000):
        assert bridge.generate_report() is True
    prior_results = bridge.results
    prior_report = bridge.report_text

    monkeypatch.setattr(
        type(scenario_application),
        "run_extreme_deviation",
        lambda *_args, **_kwargs: ExtremeDeviationRunResult(
            ExtremeDeviationRunStatus.FAILED,
            error_code="internal",
        ),
    )
    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        assert bridge.start() is True

    assert bridge.results == prior_results
    assert bridge.report_text == prior_report
    assert bridge.terminal_has_usable_results is False


def test_extreme_bridge_pin_delete_and_idle_cancel(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        bridge.start()
    run_id = str(bridge.history[0]["runId"])

    assert bridge.cancel() is False
    assert bridge.set_pinned(run_id, True) is True
    assert bridge.history[0]["pinned"] is True
    assert bridge.delete_history(run_id) is True
    assert bridge.history == []


def test_extreme_bridge_requires_confirmation_without_changing_request(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request

    bridge._on_budget_finished(
        request,
        AnalysisBudgetSnapshot(
            600,
            6,
            3_600,
            0,
            3_600,
            2_000,
            "Longbridge 服务端量化",
        ),
    )

    assert bridge.requires_budget_confirmation is True
    assert bridge.estimated_cold_requests == 3_600
    assert bridge.build_request() == request
    with qtbot.waitSignal(bridge.finished, timeout=8_000):
        assert bridge.confirm_budget_and_start() is True
    assert bridge.requires_budget_confirmation is False


def test_extreme_futu_quota_shortfall_only_allows_whole_run_yahoo(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    bridge._budget_snapshot = AnalysisBudgetSnapshot(
        1,
        4,
        4,
        0,
        4,
        50,
        "Futu 历史 K 线",
        quota_remaining=0,
        quota_new_symbols=1,
        quota_shortfall=1,
        provider_id="futu",
    )
    launched: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        bridge,
        "_launch_run",
        lambda item, *, force_yahoo=False: launched.append((item, force_yahoo)),
    )

    assert bridge.quota_blocked is True
    assert bridge.quota_remaining == 0
    assert bridge.quota_new_symbols == 1
    assert bridge.quota_shortfall == 1
    assert bridge.confirm_budget_and_start() is False
    assert bridge.use_yahoo_for_budget_and_start() is True
    assert launched == [(request, True)]


def test_extreme_bridge_exposes_shared_recovery_and_outcome_contract(
    scenario_application,
) -> None:
    bridge = ExtremeDeviationBridge(scenario_application)

    bridge._on_progress(
        ExtremeDeviationProgress(
            "FETCH_CANDLES",
            1,
            3,
            "IREN.US · 1d",
            feedback=RunFeedback(
                FeedbackKind.RETRYING,
                FailureCode.TIMEOUT,
                "IREN.US",
                "1d",
                attempt=2,
                max_attempts=2,
                wait_seconds=1.5,
            ),
        )
    )
    assert bridge.recovery_visible is True
    assert bridge.recovery_tone == "warning"
    assert bridge.retry_count == 2
    assert bridge.wait_seconds == 1.5

    bridge._on_progress(
        ExtremeDeviationProgress(
            "FETCH_CANDLES",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.RECOVERED,
                symbol="IREN.US",
                interval="1d",
            ),
        )
    )
    assert bridge.recovery_tone == "success"
    assert bridge.retry_count == 0
    assert bridge.wait_seconds == 0

    bridge._on_progress(
        ExtremeDeviationProgress(
            "FETCH_CANDLES",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.THROTTLED,
                FailureCode.RATE_LIMITED,
                "IREN.US",
                "1d",
                wait_seconds=4,
                active_concurrency=1,
            ),
        )
    )
    assert bridge.wait_seconds == 4
    assert bridge.active_concurrency == 1

    bridge._on_progress(
        ExtremeDeviationProgress(
            "FETCH_CANDLES",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.RECOVERED,
                active_concurrency=1,
            ),
        )
    )
    bridge._on_progress(ExtremeDeviationProgress("FETCH_CANDLES", 2, 3))
    assert bridge.recovery_visible is False
    assert bridge.active_concurrency == 1

    bridge._on_progress(
        ExtremeDeviationProgress(
            "FETCH_CANDLES",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.CIRCUIT_OPEN,
                FailureCode.RATE_LIMITED,
                "IREN.US",
                "1d",
            ),
        )
    )
    assert bridge.retry_count == 0
    assert bridge.wait_seconds == 0
    assert bridge.failure_groups[0]["code"] == "rate_limited"
    assert bridge.failure_groups[0]["count"] == 1

    bridge._on_finished(
        "run",
        ExtremeDeviationRunResult(
            ExtremeDeviationRunStatus.PARTIAL,
            reliability=AnalysisReliability(
                8,
                1,
                1,
                Decimal("0.8"),
                True,
                "rate_limited",
            ),
        ),
    )
    assert bridge.outcome_tone == "warning"
    assert "可用但不完整" in bridge.outcome_title
    assert "未执行 1" in bridge.outcome_summary

    bridge._on_finished(
        "run",
        ExtremeDeviationRunResult(
            ExtremeDeviationRunStatus.FAILED,
            error_code="internal",
            reliability=AnalysisReliability(
                7,
                2,
                1,
                Decimal("0.7"),
                False,
                "internal",
            ),
        ),
    )
    assert bridge.outcome_tone == "danger"
    assert "未保存历史记录" in bridge.outcome_summary


def test_extreme_cancel_after_fatal_feedback_is_calm(
    scenario_application,
) -> None:
    bridge = ExtremeDeviationBridge(scenario_application)
    bridge._on_progress(
        ExtremeDeviationProgress(
            "FETCH_CANDLES",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.RETRYING,
                FailureCode.TIMEOUT,
                "IREN.US",
                attempt=2,
                max_attempts=3,
                wait_seconds=4,
            ),
        )
    )
    bridge._on_progress(
        ExtremeDeviationProgress(
            "FETCH_CANDLES",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.FATAL,
                FailureCode.AUTHENTICATION_FAILED,
                "IREN.US",
            ),
        )
    )
    assert bridge.retry_count == 0
    assert bridge.wait_seconds == 0

    bridge._on_finished(
        "run",
        ExtremeDeviationRunResult(ExtremeDeviationRunStatus.CANCELED),
    )

    assert bridge.recovery_visible is False
    assert bridge.outcome_visible is False
    assert bridge.outcome_primary_action == ""
    assert bridge.failure_groups == []


def test_extreme_preflight_failures_replace_stale_presentation(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    bridge._on_progress(
        ExtremeDeviationProgress(
            "FETCH_CANDLES",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.ITEM_SKIPPED,
                FailureCode.TIMEOUT,
                "IREN.US",
            ),
        )
    )

    bridge._on_budget_finished(
        request,
        AnalysisBudgetSnapshot(
            3,
            6,
            100,
            0,
            100,
            2_000,
            "virtual",
            storage_state=StorageState.BLOCKED,
            error_code="storage_unavailable",
        ),
    )

    assert bridge.failure_groups == []
    assert bridge.outcome_title == "存储不可用"
    assert bridge.outcome_primary_action == "open_settings"

    bridge._budget_request = request
    bridge._on_progress(
        ExtremeDeviationProgress(
            "FETCH_CANDLES",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.FATAL,
                FailureCode.AUTHENTICATION_FAILED,
                "IREN.US",
            ),
        )
    )
    bridge._on_budget_finished(
        request,
        RuntimeError("Authorization: Bearer secret"),
    )

    assert bridge.failure_groups == []
    assert bridge.outcome_title == "运行未完成"
    assert bridge.outcome_primary_action == "retry"
    assert "secret" not in bridge.outcome_summary


def test_extreme_blocked_budget_never_launches_or_confirms(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = ExtremeDeviationBridge(scenario_application)
    with qtbot.waitSignal(bridge.support_finished, timeout=5_000):
        bridge.load_support_data()
    bridge.select_security(watchlist.memberships[0].security_id)
    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    calls: list[object] = []
    monkeypatch.setattr(
        type(scenario_application),
        "run_extreme_deviation",
        lambda *_args, **_kwargs: calls.append(object()),
    )

    bridge._on_budget_finished(
        request,
        AnalysisBudgetSnapshot(
            3,
            6,
            100,
            0,
            100,
            2_000,
            "virtual",
            storage_state=StorageState.BLOCKED,
            free_bytes=0,
            error_code="storage_unavailable",
        ),
    )

    assert calls == []
    assert bridge.running is False
    assert bridge._task is None
    bridge._budget_snapshot = AnalysisBudgetSnapshot(
        3,
        6,
        3_000,
        0,
        3_000,
        2_000,
        "virtual",
        storage_state=StorageState.BLOCKED,
        error_code="storage_unavailable",
    )
    assert bridge.requires_budget_confirmation is False
    assert bridge.confirm_budget_and_start() is False
    assert bridge.last_status == "FAILED"
    assert "storage_unavailable" in bridge.status_text
    assert bridge.outcome_primary_action == "open_settings"
