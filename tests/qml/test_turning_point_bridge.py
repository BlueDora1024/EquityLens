from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event

import pytest

from stock_toolbox.analyses.resource_budget import AnalysisBudgetSnapshot
from stock_toolbox.analyses.turning_point.application.history import (
    project_turning_point_history,
)
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointProgress,
    TurningPointRunResult,
    TurningPointRunStatus,
)
from stock_toolbox.analyses.turning_point.application.report import (
    TurningPointReport,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    TurningPointTradeSide,
)
from stock_toolbox.composition import build_application
from stock_toolbox.core.operations.failure_policy import (
    AnalysisReliability,
    FailureCode,
)
from stock_toolbox.core.operations.registry import CancelResult
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback
from stock_toolbox.core.operations.storage_guard import StorageState
from stock_toolbox.core.settings.models import ServiceSettingsInput
from stock_toolbox.desktop_qml.progress_diagnostics import ProgressEventSampler
from stock_toolbox.desktop_qml.turning_point_bridge import TurningPointBridge
from stock_toolbox.infrastructure.ai.openai_compatible import AIAdapterError
from stock_toolbox.runtime.environment import RuntimeEnvironment
from tests.qml.helpers import seeded_watchlist


def test_turning_point_bridge_builds_existing_application_request(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    assert bridge.active_concurrency == 4

    bridge.select_watchlist(watchlist.id)
    bridge.set_interval("30m")
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()

    assert request is not None
    assert request.watchlist_id == watchlist.id
    assert request.intervals == (request.interval,)
    assert request.requested_end_date.isoformat() == "2026-07-24"
    assert not hasattr(request, "minimum_market_value")
    assert not hasattr(request, "require_positive_250d")
    assert bridge.can_start is True


def test_turning_point_bridge_selects_one_trade_side_and_builds_request(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")

    assert bridge.trade_side == "RIGHT_CONFIRMED"
    assert bridge.trade_side_label == "右侧 · 均线确认"
    assert bridge.set_trade_side("LEFT_CD") is True
    assert bridge.trade_side == "LEFT_CD"
    assert bridge.trade_side_label == "左侧 · CD"
    assert bridge.build_request().trade_side is TurningPointTradeSide.LEFT_CD
    assert bridge.set_trade_side("UNKNOWN") is False


def test_turning_point_bridge_defaults_to_three_periods_and_keeps_one(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)

    assert [item["value"] for item in bridge.intervals if item["selected"]] == [
        "30m",
        "60m",
        "1d",
    ]
    bridge.set_interval_selected("30m", False)
    bridge.set_interval_selected("60m", False)
    bridge.set_interval_selected("1d", False)

    assert bridge.selected_interval_count == 1


def test_turning_point_bridge_rejects_today_and_future_dates(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)

    bridge.set_end_date("2999-01-01")

    assert bridge.end_date == ""
    assert bridge.maximum_historical_date < "2999-01-01"


def test_turning_point_budget_confirmation_is_consumed_before_launch(
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    bridge._budget_snapshot = AnalysisBudgetSnapshot(
        100,
        3,
        300,
        0,
        300,
        50,
        "Longbridge 服务端量化",
    )
    launched: list[object] = []
    monkeypatch.setattr(
        bridge,
        "_launch_run",
        lambda item, *, force_yahoo=False: launched.append((item, force_yahoo)),
    )

    assert bridge.requires_budget_confirmation is True
    assert bridge.confirm_budget_and_start() is True

    assert launched == [(request, False)]
    assert bridge.requires_budget_confirmation is False
    assert bridge._budget_request is None
    assert bridge._budget_snapshot is None


def test_turning_futu_quota_shortfall_only_allows_whole_run_yahoo(
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    bridge._budget_snapshot = AnalysisBudgetSnapshot(
        123,
        3,
        369,
        0,
        369,
        50,
        "Futu 历史 K 线",
        quota_remaining=98,
        quota_new_symbols=123,
        quota_shortfall=25,
        provider_id="futu",
    )
    launched: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        bridge,
        "_launch_run",
        lambda item, *, force_yahoo=False: launched.append((item, force_yahoo)),
    )

    assert bridge.quota_blocked is True
    assert bridge.quota_remaining == 98
    assert bridge.quota_new_symbols == 123
    assert bridge.quota_shortfall == 25
    assert bridge.confirm_budget_and_start() is False
    assert bridge.use_yahoo_for_budget_and_start() is True
    assert launched == [(request, True)]


def test_turning_point_support_data_loads_in_background(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)

    bridge.load_support_data()
    qtbot.waitUntil(lambda: bridge.support_loaded, timeout=5_000)

    assert bridge.support_loading is False
    assert bridge.watchlists[0]["id"] == watchlist.id


def test_turning_point_process_worker_keeps_gui_path_isolated(
    qtbot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
    )
    watchlist = seeded_watchlist(application)
    bridge = TurningPointBridge(application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_interval("30m")
    bridge.set_end_date("2026-07-24")
    monkeypatch.setenv("PYTHONPATH", str(Path.cwd() / "src"))
    worker = Path.cwd() / ".venv" / "bin" / "stock-toolbox"
    monkeypatch.setattr(bridge, "_turning_worker_program", lambda: worker)
    monkeypatch.setattr(
        bridge,
        "_turning_worker_arguments",
        lambda _request: [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "analysis",
            "turning-point",
            "run-worker",
            "--watchlist-id",
            watchlist.id,
            "--interval",
            "30m",
            "--end-date",
            "2026-07-24",
            "--trade-side",
            "right",
        ],
    )

    with qtbot.waitSignal(bridge.finished, timeout=15_000):
        assert bridge.start() is True

    assert bridge.running is False
    assert bridge.results_available is True
    assert bridge.history
    assert bridge._task is None
    assert bridge._run_process is None
    application.close()


def test_turning_point_process_worker_surfaces_fallback_offer(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)

    bridge._consume_run_process_line(
        b'{"type":"fallback","operation_kind":"turning_point",'
        b'"failed_symbols":["IREN.US"],"intervals":["30m"],'
        b'"failure_codes":["timeout"],"completed":2,"total":3}'
    )

    assert bridge.fallback_gate.pending is True
    assert bridge.fallback_gate.failed_count == 1
    assert bridge.fallback_gate.failure_text == "请求超时"


def test_turning_point_process_stderr_is_drained(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)

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


def test_turning_process_quota_failure_is_not_presented_as_insufficient_data(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)
    reliability = AnalysisReliability(
        0,
        372,
        0,
        Decimal(0),
        False,
        FailureCode.QUOTA_EXHAUSTED.value,
    )

    bridge._finish_process_run(
        TurningPointRunStatus.FAILED,
        "",
        "insufficient_reliable_results",
        [],
        reliability,
    )

    assert bridge.outcome_title == "服务配额已用完"


def test_turning_point_progress_notifications_are_coalesced(
    qtbot,
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)
    notifications = 0

    def count_notification() -> None:
        nonlocal notifications
        notifications += 1

    bridge.changed.connect(count_notification)
    for completed in range(100):
        bridge._on_progress(
            TurningPointProgress(
                "FETCH_CANDLES",
                completed,
                100,
                f"S{completed}.US",
            )
        )

    assert notifications == 0
    qtbot.waitUntil(lambda: notifications == 1, timeout=1_000)


def test_progress_diagnostics_sample_large_runs_but_keep_boundaries() -> None:
    sampler = ProgressEventSampler(max_updates_per_stage=20)

    emitted = [completed for completed in range(101) if sampler.accept("COMPUTE", completed, 100)]

    assert emitted[0] == 0
    assert emitted[-1] == 100
    assert len(emitted) <= 21


def test_turning_point_support_data_refreshes_new_watchlists(
    qtbot,
    scenario_application,
) -> None:
    first = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)

    bridge.load_support_data()
    qtbot.waitUntil(lambda: bridge.support_loaded, timeout=5_000)
    second = scenario_application.master_data.create_watchlist("后来创建")

    bridge.load_support_data()
    qtbot.waitUntil(lambda: not bridge.support_loading, timeout=5_000)

    assert {row["id"] for row in bridge.watchlists} >= {
        first.id,
        second.id,
    }


def test_turning_point_support_refresh_preserves_cache_on_error(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.load_support_data()
    qtbot.waitUntil(lambda: bridge.support_loaded, timeout=5_000)
    bridge.select_watchlist(watchlist.id)
    cached = list(bridge.watchlists)
    monkeypatch.setattr(
        scenario_application.master_data,
        "list_watchlists",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    bridge.load_support_data()
    qtbot.waitUntil(lambda: not bridge.support_loading, timeout=5_000)

    assert bridge.watchlists == cached
    assert bridge.selected_watchlist_id == watchlist.id


def test_turning_point_support_refresh_clears_removed_selection(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge._watchlist_id = watchlist.id

    bridge._apply_support({"watchlists": [], "history": []})

    assert bridge.selected_watchlist_id == ""


def test_turning_point_bridge_rejects_unknown_watchlist(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge._apply_support(
        {
            "watchlists": scenario_application.master_data.list_watchlists(),
            "history": [],
        }
    )

    assert bridge.select_watchlist("missing") is False
    assert bridge.select_watchlist(watchlist.id) is True


def test_turning_point_bridge_runs_and_exposes_complete_history(
    qtbot,
    scenario_application,
    tmp_path: Path,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.start() is True
        assert bridge.running is True

    assert bridge.last_status in {"READY", "PARTIAL"}
    assert len(bridge.results) == bridge.matched_count
    assert bridge.matched_count >= 1
    assert bridge.result_filters[0]["value"] == "attention"
    assert bridge.result_filters[0]["count"] == bridge.matched_count
    assert all(row["count"] > 0 for row in bridge.result_filters)
    assert bridge.results[0]["matchedPeriodChips"]
    assert "命中" in bridge.results[0]["matchedPeriodChips"][0]["tip"]
    assert len(bridge.history) == 1
    run_id = str(bridge.history[0]["runId"])
    assert bridge.select_run(run_id) is True
    assert len(bridge.results) == bridge.matched_count
    first_interval = next(
        item["value"]
        for item in bridge.result_filters
        if item["value"] != "attention" and item["count"] > 0
    )
    assert bridge.select_result_interval(first_interval) is True
    assert all(item["selectedPeriod"]["interval"] == first_interval for item in bridge.results)

    assert bridge.export_default_name.startswith("拐点筛选_")
    assert bridge.export_default_name.endswith(".csv")
    assert bridge.export_default_url.startswith("file:")
    target = tmp_path / "turning-point.csv"
    assert bridge.export_history(run_id, str(target)) is True
    exported = target.read_text(encoding="utf-8-sig")
    assert "symbol,source" in exported
    assert "interval" in exported
    assert "signal_at" in exported
    assert "IREN.US" in exported

    assert bridge.prepare_new_run() is True
    assert bridge.selected_run_id == ""
    assert bridge.results_available is False
    assert bridge.results == []
    assert len(bridge.history) == 1


def test_turning_history_filters_belong_to_selected_run(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.start() is True

    run_id = str(bridge.history[0]["runId"])
    assert bridge.select_run(run_id) is True
    assert bridge.selected_run_id == run_id
    assert bridge.result_view == "attention"
    assert [row["label"] for row in bridge.result_filters] == [
        "综合关注",
        "30 分钟",
        "1 小时",
        "日线",
    ]
    period_filter = next(
        row for row in bridge.result_filters if row["value"] != "attention" and row["count"] > 0
    )
    assert bridge.select_result_interval(str(period_filter["value"])) is True
    assert bridge.results
    assert all(
        row["selectedPeriod"]["interval"] == period_filter["value"] for row in bridge.results
    )
    assert bridge.select_result_interval("1w") is False


def test_turning_history_hides_empty_period_filters_and_explains_empty_run(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)
    bridge._apply_projection(
        project_turning_point_history(
            {
                "request": {"intervals": ["30m", "60m"]},
                "results": [],
                "unmatched_results": [],
            }
        )
    )

    assert bridge.result_filters == []
    assert "没有证券命中" in bridge.result_empty_text


def test_turning_history_operation_time_follows_display_timezone(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.start() is True

    run_id = str(bridge.history[0]["runId"])
    bridge._history_records[run_id]["completed_at"] = datetime(2026, 7, 24, 1, 30, tzinfo=UTC)
    bridge._apply_history(list(bridge._history_records.values()))
    assert bridge.history[0]["completedAt"] == "2026-07-24 09:30"

    current = scenario_application.settings()
    scenario_application.save_settings(
        ServiceSettingsInput(
            current.provider_mode,
            current.timeout_seconds,
            current.max_retries,
            current.ai_base_url,
            current.ai_model,
            current.developer_mode_enabled,
            current.longbridge_client_id,
            "America/New_York",
            current.proxy_mode,
            current.proxy_url,
        )
    )
    bridge.refresh_display_timezone()

    assert bridge.history[0]["completedAt"] == "2026-07-23 21:30"


def test_turning_history_switch_resets_record_scoped_state(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.start() is True
    first_id = str(bridge.history[0]["runId"])
    assert bridge.set_pinned(first_id, True)

    bridge.set_interval_selected("60m", False)
    bridge.set_interval_selected("1d", False)
    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.start() is True
    second_id = next(str(row["runId"]) for row in bridge.history if str(row["runId"]) != first_id)

    assert bridge.select_run(first_id)
    assert bridge.selected_run_pinned is True
    assert bridge.select_result_interval("30m")
    assert bridge.result_view == "30m"

    assert bridge.select_run(second_id)
    assert bridge.selected_run_id == second_id
    assert bridge.result_view == "attention"
    assert bridge.selected_run_pinned is False
    assert [row["value"] for row in bridge.result_filters] == [
        "attention",
        "30m",
    ]


def test_turning_point_bridge_ignores_retired_250d_risk_labels(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)

    bridge._apply_projection(
        project_turning_point_history(
            {
                "request": {"intervals": ["1d"]},
                "results": [
                    {
                        "symbol": "IREN.US",
                        "market_value_usd": 1_900_000_000,
                        "return_250d": -0.2,
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
                    }
                ],
            }
        )
    )

    assert bridge.results[0]["riskLabels"] == [
        "小市值 · 低于 20 亿美元",
    ]


def test_turning_point_bridge_pin_delete_and_idle_cancel(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        bridge.start()
    run_id = str(bridge.history[0]["runId"])

    assert bridge.cancel() is False
    assert bridge.set_pinned(run_id, True) is True
    assert bridge.history[0]["pinned"] is True
    assert bridge.delete_history(run_id) is True
    assert bridge.history == []


def test_turning_point_bridge_generates_saved_report(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=10_000):
        assert bridge.start() is True

    with qtbot.waitSignal(bridge.report_finished, timeout=10_000):
        assert bridge.generate_report() is True

    assert "多周期" in bridge.report_text
    assert bridge.report_running is False
    assert bridge.report_error == ""


def test_turning_report_failure_preserves_saved_report_and_run_state(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=10_000):
        assert bridge.start() is True
    with qtbot.waitSignal(bridge.report_finished, timeout=10_000):
        assert bridge.generate_report() is True
    prior_report = bridge.report_text
    prior_results = bridge.results
    prior_status = bridge.last_status
    monkeypatch.setattr(
        type(scenario_application),
        "generate_turning_point_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AIAdapterError("quota_exhausted")),
    )

    with qtbot.waitSignal(bridge.report_finished, timeout=10_000):
        assert bridge.generate_report() is True

    assert bridge.report_text == prior_report
    assert bridge.results == prior_results
    assert bridge.last_status == prior_status
    assert bridge.report_error == "AI 服务配额已用完，请在设置中检查账户配额。"


def test_turning_report_is_close_safe_and_cancelable(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=10_000):
        assert bridge.start()
    prior_results = bridge.results
    prior_status = bridge.last_status
    entered = Event()

    def blocked_report(
        _application,
        _run_id,
        *,
        operation_control,
    ):
        entered.set()
        operation_control.wait_for_cancellation(5)
        raise AIAdapterError("canceled")

    monkeypatch.setattr(
        type(scenario_application),
        "generate_turning_point_report",
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


def test_turning_async_report_completion_stays_scoped_to_origin_run(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)
    bridge._selected_run_id = "current-run"
    bridge._report_text = "当前历史的旧报告"
    bridge._report_error = "当前历史的旧错误"
    report = TurningPointReport(
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


def test_turning_point_bridge_exposes_shared_recovery_and_outcome_contract(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)

    bridge._on_progress(
        TurningPointProgress(
            "FETCH_INDICATORS",
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
        TurningPointProgress(
            "FETCH_INDICATORS",
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
        TurningPointProgress(
            "FETCH_INDICATORS",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.THROTTLED,
                FailureCode.RATE_LIMITED,
                "IREN.US",
                "1d",
                wait_seconds=2.5,
                active_concurrency=1,
            ),
        )
    )
    assert bridge.wait_seconds == 2.5
    assert bridge.active_concurrency == 1

    bridge._on_progress(
        TurningPointProgress(
            "FETCH_INDICATORS",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.RECOVERED,
                active_concurrency=1,
            ),
        )
    )
    bridge._on_progress(TurningPointProgress("FETCH_INDICATORS", 2, 3))
    assert bridge.recovery_visible is False
    assert bridge.active_concurrency == 1

    bridge._on_progress(
        TurningPointProgress(
            "FETCH_INDICATORS",
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
        (
            TurningPointRunResult(
                TurningPointRunStatus.PARTIAL,
                reliability=AnalysisReliability(
                    8,
                    1,
                    1,
                    Decimal("0.8"),
                    True,
                    "rate_limited",
                ),
            ),
            [],
        ),
    )
    assert bridge.outcome_tone == "warning"
    assert "可用但不完整" in bridge.outcome_title
    assert "未执行 1" in bridge.outcome_summary

    bridge._on_finished(
        "run",
        (
            TurningPointRunResult(
                TurningPointRunStatus.FAILED,
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
            [],
        ),
    )
    assert bridge.outcome_tone == "danger"
    assert "未保存历史记录" in bridge.outcome_summary


def test_turning_point_cancel_after_fatal_feedback_is_calm(
    scenario_application,
) -> None:
    bridge = TurningPointBridge(scenario_application)
    bridge._on_progress(
        TurningPointProgress(
            "FETCH_INDICATORS",
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
        TurningPointProgress(
            "FETCH_INDICATORS",
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
        (
            TurningPointRunResult(TurningPointRunStatus.CANCELED),
            [],
        ),
    )

    assert bridge.recovery_visible is False
    assert bridge.outcome_visible is False
    assert bridge.outcome_primary_action == ""
    assert bridge.failure_groups == []


def test_turning_point_preflight_failures_replace_stale_presentation(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    bridge._on_progress(
        TurningPointProgress(
            "FETCH_INDICATORS",
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
            3,
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
        TurningPointProgress(
            "FETCH_INDICATORS",
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


def test_turning_point_failed_new_run_preserves_prior_result_and_report(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    with qtbot.waitSignal(bridge.finished, timeout=10_000):
        assert bridge.start() is True
    with qtbot.waitSignal(bridge.report_finished, timeout=10_000):
        assert bridge.generate_report() is True
    prior_results = bridge.results
    prior_report = bridge.report_text

    monkeypatch.setattr(
        type(scenario_application),
        "run_turning_point",
        lambda *_args, **_kwargs: TurningPointRunResult(
            TurningPointRunStatus.FAILED,
            error_code="internal",
        ),
    )
    with qtbot.waitSignal(bridge.finished, timeout=10_000):
        assert bridge.start() is True

    assert bridge.results == prior_results
    assert bridge.results_available is True
    assert bridge.report_text == prior_report


def test_turning_point_blocked_budget_never_launches_or_confirms(
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = TurningPointBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    calls: list[object] = []
    monkeypatch.setattr(
        type(scenario_application),
        "run_turning_point",
        lambda *_args, **_kwargs: calls.append(object()),
    )

    bridge._on_budget_finished(
        request,
        AnalysisBudgetSnapshot(
            3,
            3,
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
        3,
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
