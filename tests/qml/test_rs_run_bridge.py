from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from PySide6.QtCore import QThreadPool

from stock_toolbox.analyses.resource_budget import AnalysisBudgetSnapshot
from stock_toolbox.analyses.rs_strength.application.models import (
    RunProgress,
    RunResult,
    RunStatus,
)
from stock_toolbox.analyses.rs_strength.application.service import StartRun
from stock_toolbox.core.market_data.date_policy import display_today
from stock_toolbox.core.market_data.provider_health import ProviderIdentity
from stock_toolbox.core.market_data.quant import QuantProgress, QuantSeriesDataset
from stock_toolbox.core.market_data.quant_daily import QuantDailyBarsService
from stock_toolbox.core.operations.failure_policy import (
    AnalysisReliability,
    FailureCode,
)
from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback
from stock_toolbox.core.operations.storage_guard import StorageState
from stock_toolbox.desktop_qml.rs_run_bridge import RsRunBridge
from tests.qml.helpers import seeded_watchlist


def test_rs_provider_status_uses_active_provider_identity(
    monkeypatch,
    scenario_application,
) -> None:
    monkeypatch.setattr(
        type(scenario_application),
        "provider_identity",
        lambda _application: ProviderIdentity("futu", "富途", True),
    )

    bridge = RsRunBridge(scenario_application)

    assert bridge.provider_status == "富途 · 已连接"


def test_rs_provider_status_can_be_refreshed_after_settings_change(
    qtbot,
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)

    with qtbot.waitSignal(bridge.changed, timeout=1_000):
        bridge.refresh_provider_status()


class _FatalBenchmarkQuant:
    def get_quant_series(
        self,
        symbols,
        request,
        *,
        operation_control,
        progress=None,
    ):
        del request, operation_control
        if progress is not None:
            progress(
                QuantProgress(
                    0,
                    len(symbols),
                    symbols[0],
                    0,
                    0,
                    feedback=RunFeedback(
                        FeedbackKind.RETRYING,
                        FailureCode.NETWORK_ERROR,
                        symbols[0],
                        attempt=2,
                        max_attempts=2,
                        wait_seconds=2,
                    ),
                )
            )
            progress(
                QuantProgress(
                    1,
                    len(symbols),
                    symbols[0],
                    0,
                    1,
                    feedback=RunFeedback(
                        FeedbackKind.FATAL,
                        FailureCode.AUTHENTICATION_FAILED,
                        symbols[0],
                    ),
                )
            )
        return QuantSeriesDataset(
            "longbridge",
            "Longbridge",
            {},
            {symbols[0]: FailureCode.AUTHENTICATION_FAILED.value},
        )


class _NoSaveHistory:
    def save(self, snapshot, *, operation_control):
        del snapshot, operation_control
        raise AssertionError("benchmark failure must not save")


def test_rs_bridge_builds_the_same_six_preflight_checks(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    assert bridge.active_concurrency == 4

    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")

    assert bridge.member_count == 3
    assert bridge.range_count == 6
    assert bridge.benchmark == "SPY.US"
    assert bridge.preflight_passed == 6
    assert bridge.can_start is True


def test_rs_bridge_rejects_today_and_exposes_calendar_maximum(
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)
    today = display_today(scenario_application.settings().display_timezone)

    bridge.set_end_date(today.isoformat())
    bridge.set_custom_dates("2026-01-01", today.isoformat())

    assert date.fromisoformat(bridge.maximum_historical_date) < today
    assert bridge.end_date == ""
    assert bridge.custom_end == ""


def test_rs_bridge_rejects_invalid_custom_range(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")

    bridge.set_custom_range(True, "2026-07-24", "2026-04-24")

    assert bridge.range_count == 7
    assert bridge.can_start is False


def test_rs_bridge_runs_existing_application_asynchronously(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.start() is True
        assert bridge.running is True

    assert bridge.running is False
    assert bridge.progress == 1.0
    assert bridge.last_status == "READY"


def test_rs_process_worker_keeps_provider_io_out_of_the_gui_process(
    qtbot,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    from stock_toolbox.composition import build_application
    from stock_toolbox.runtime.environment import RuntimeEnvironment

    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
    )
    watchlist = seeded_watchlist(application)
    bridge = RsRunBridge(application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    monkeypatch.setenv("PYTHONPATH", str(Path.cwd() / "src"))
    worker = Path.cwd() / ".venv" / "bin" / "stock-toolbox"
    monkeypatch.setattr(bridge, "_worker_program", lambda: worker)
    monkeypatch.setattr(
        bridge,
        "_worker_arguments",
        lambda _request, force_yahoo=False: [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "analysis",
            "rs-strength",
            "run-worker",
            "--watchlist-id",
            watchlist.id,
            "--benchmark",
            "SPY.US",
            "--end-date",
            "2026-07-24",
            "--range",
            "3M",
        ],
    )

    with qtbot.waitSignal(bridge.finished, timeout=15_000):
        bridge._launch_run(bridge.build_request())

    assert bridge.running is False
    assert bridge.last_status == "READY"
    assert bridge._task is None
    assert bridge._run_process is None
    assert application.list_history()
    application.close()


def test_rs_quant_feedback_reaches_queued_bridge_and_preserves_benchmark_auth(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    snapshots: list[tuple[bool, int, float]] = []
    bridge.changed.connect(
        lambda: snapshots.append(
            (
                bridge.recovery_visible,
                bridge.retry_count,
                bridge.wait_seconds,
            )
        )
    )

    def run_with_quant_feedback(
        _application,
        active_request,
        *,
        operation_id=None,
        progress=lambda _item: None,
        fallback_consent=None,
        force_yahoo=False,
    ):
        del fallback_consent, force_yahoo
        assert operation_id is not None
        registry = OperationRegistry(clock=lambda: datetime(2026, 7, 25, tzinfo=UTC))
        registry.reserve(operation_id, "key", "rs")
        context = registry.begin_reserved(operation_id)
        assert context is not None
        return StartRun(
            scenario_application.master_data,
            QuantDailyBarsService(_FatalBenchmarkQuant()),  # type: ignore[arg-type]
            _NoSaveHistory(),  # type: ignore[arg-type]
            clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
            new_id=lambda: "run-id",
            progress=progress,
            today=lambda: date(2026, 7, 25),
        ).execute(active_request, context)

    monkeypatch.setattr(
        type(scenario_application),
        "run",
        run_with_quant_feedback,
    )

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        bridge._launch_run(request)

    assert any(
        visible and retry_count == 2 and wait_seconds == 2
        for visible, retry_count, wait_seconds in snapshots
    )
    assert bridge.last_status == "FAILED"
    assert bridge.outcome_title == "授权已失效"
    assert bridge.outcome_primary_action == "open_settings"
    assert bridge.outcome_primary_label == "检查授权设置"


def test_rs_bridge_cancel_requires_an_active_run(
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)

    assert bridge.cancel() is False


def test_rs_watchlists_load_asynchronously_and_keep_a_stable_cache(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)

    assert bridge.watchlists == []
    assert bridge.watchlists_loaded is False

    with qtbot.waitSignal(bridge.watchlists_finished, timeout=5_000):
        assert bridge.load_watchlists() is True
        assert bridge.watchlists_loading is True

    assert bridge.watchlists_loading is False
    assert bridge.watchlists_loaded is True
    assert bridge.watchlists == [
        {
            "id": watchlist.id,
            "name": watchlist.display_name,
            "memberCount": 3,
        }
    ]


def test_rs_bridge_loads_latest_completed_trading_day_without_blocking(
    qtbot,
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)

    with qtbot.waitSignal(bridge.calendar_finished, timeout=5_000):
        assert bridge.refresh_latest_trading_day() is True
        assert bridge.calendar_loading is True

    assert bridge.calendar_loading is False
    assert bridge.end_date == "2026-07-24"


def test_rs_custom_range_defaults_from_end_date_and_remains_editable(
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)
    bridge.set_end_date("2026-07-24")

    bridge.set_custom_enabled(True)

    assert bridge.custom_enabled is True
    assert bridge.custom_start == "2026-04-24"
    assert bridge.custom_end == "2026-07-24"

    bridge.set_custom_dates("2026-05-01", "2026-07-18")

    assert bridge.custom_start == "2026-05-01"
    assert bridge.custom_end == "2026-07-18"


def test_rs_bridge_exposes_localized_live_progress_without_market_suffix(
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)

    bridge._on_progress(RunProgress("FETCHING", 2, 5, "AAPL.US", 2, 0))

    assert bridge.stage_label == "获取收盘结果"
    assert bridge.stage_detail == "正在按当前供应商能力并发获取行情"
    assert bridge.current_symbol == "AAPL"
    assert bridge.completed_count == 2
    assert bridge.total_count == 5
    assert bridge.succeeded_count == 2
    assert bridge.failed_count == 0
    assert bridge.status_text == "获取收盘结果 · 2/5 · AAPL"


def test_rs_bridge_presents_fast_success_stages_in_order(
    qtbot,
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)
    bridge._running = True
    presented: list[int] = []

    def capture_stage() -> None:
        if bridge.active_stage >= 0 and (not presented or presented[-1] != bridge.active_stage):
            presented.append(bridge.active_stage)

    bridge.changed.connect(capture_stage)
    for stage in (
        "PREFLIGHT",
        "FETCHING",
        "VALIDATING",
        "CALCULATING",
        "AGGREGATING",
        "SAVING",
    ):
        bridge._on_progress(RunProgress(stage, 1, 1))

    assert bridge.active_stage == 0
    with qtbot.waitSignal(bridge.finished, timeout=3_000):
        bridge._on_finished(RunResult(RunStatus.READY, run_id="run-id"))
        assert bridge.running is True
        assert bridge.last_status == ""

    assert presented == [0, 1, 2, 3, 4, 5]
    assert bridge.running is False
    assert bridge.last_status == "READY"


def test_rs_bridge_failure_bypasses_pending_stage_presentation(
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)
    bridge._running = True
    bridge._on_progress(RunProgress("PREFLIGHT", 1, 1))
    bridge._on_progress(RunProgress("FETCHING", 1, 1))

    bridge._on_finished(RunResult(RunStatus.FAILED, error_code="BENCHMARK_FETCH_FAILED"))

    assert bridge.running is False
    assert bridge.last_status == "FAILED"
    assert bridge.status_text == "运行失败"


def test_rs_bridge_keeps_preflight_stable_and_exposes_failed_terminal(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    bridge._running = True
    bridge._progress = 0.4

    assert bridge.preflight_passed == 6
    assert bridge.preflight_ready is True

    bridge._on_finished(RunResult(RunStatus.FAILED, error_code="BENCHMARK_FETCH_FAILED"))

    assert bridge.progress == 0.4
    assert bridge.terminal_visible is True
    assert bridge.terminal_kind == "FAILED"
    assert bridge.terminal_detail == "基准行情获取失败，请检查授权或稍后重试"
    assert bridge.status_text == "运行失败"


def test_rs_bridge_exposes_shared_recovery_and_outcome_contract(
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)
    emissions: list[None] = []
    bridge.changed.connect(lambda: emissions.append(None))

    bridge._on_progress(
        RunProgress(
            "FETCHING",
            1,
            3,
            "IREN.US",
            feedback=RunFeedback(
                FeedbackKind.RETRYING,
                FailureCode.TIMEOUT,
                "IREN.US",
                attempt=2,
                max_attempts=2,
                wait_seconds=1.5,
            ),
        )
    )
    assert len(emissions) == 1
    assert bridge.recovery_visible is True
    assert bridge.recovery_tone == "warning"
    assert "第 2 次重试" in bridge.recovery_message
    assert bridge.retry_count == 2
    assert bridge.wait_seconds == 1.5

    bridge._on_progress(
        RunProgress(
            "FETCHING",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.RECOVERED,
                symbol="IREN.US",
            ),
        )
    )
    assert bridge.recovery_tone == "success"
    assert bridge.retry_count == 0
    assert bridge.wait_seconds == 0

    bridge._on_progress(
        RunProgress(
            "FETCHING",
            1,
            3,
            "IREN.US",
            feedback=RunFeedback(
                FeedbackKind.THROTTLED,
                FailureCode.RATE_LIMITED,
                "IREN.US",
                wait_seconds=3,
                active_concurrency=1,
            ),
        )
    )
    assert bridge.wait_seconds == 3
    assert bridge.active_concurrency == 1

    bridge._on_progress(
        RunProgress(
            "FETCHING",
            1,
            3,
            feedback=RunFeedback(
                FeedbackKind.RECOVERED,
                active_concurrency=1,
            ),
        )
    )
    bridge._on_progress(RunProgress("FETCHING", 2, 3))
    assert bridge.recovery_visible is False
    assert bridge.active_concurrency == 1

    bridge._on_progress(
        RunProgress(
            "FETCHING",
            1,
            3,
            "IREN.US",
            feedback=RunFeedback(
                FeedbackKind.CIRCUIT_OPEN,
                FailureCode.RATE_LIMITED,
                "IREN.US",
                "1d",
            ),
        )
    )
    assert bridge.recovery_visible is True
    assert bridge.retry_count == 0
    assert bridge.wait_seconds == 0
    assert bridge.failure_groups == [
        {
            "code": "rate_limited",
            "count": 1,
            "symbols": ["IREN.US"],
            "intervals": ["1d"],
        }
    ]

    bridge._on_finished(
        RunResult(
            RunStatus.PARTIAL,
            reliability=AnalysisReliability(
                8,
                1,
                1,
                Decimal("0.8"),
                True,
                "rate_limited",
            ),
        )
    )
    assert bridge.outcome_visible is True
    assert bridge.outcome_tone == "warning"
    assert "可用但不完整" in bridge.outcome_title
    assert "成功 8" in bridge.outcome_summary

    bridge._on_finished(
        RunResult(
            RunStatus.FAILED,
            error_code="internal",
            reliability=AnalysisReliability(
                7,
                2,
                1,
                Decimal("0.7"),
                False,
                "internal",
            ),
        )
    )
    assert bridge.outcome_tone == "danger"
    assert "未保存历史记录" in bridge.outcome_summary


def test_rs_cancel_after_fatal_feedback_is_calm(
    scenario_application,
) -> None:
    bridge = RsRunBridge(scenario_application)
    bridge._on_progress(
        RunProgress(
            "FETCHING",
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
        RunProgress(
            "FETCHING",
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

    bridge._on_finished(RunResult(RunStatus.CANCELED))

    assert bridge.recovery_visible is False
    assert bridge.outcome_visible is False
    assert bridge.outcome_primary_action == ""
    assert bridge.failure_groups == []


def test_rs_terminal_quota_failure_exposes_aggregate_detail_and_allows_restart(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    bridge._failed_count = 115

    bridge._on_finished(
        RunResult(
            RunStatus.FAILED,
            reliability=AnalysisReliability(
                0,
                115,
                0,
                Decimal(0),
                False,
                "quota_exhausted",
            ),
        )
    )

    assert bridge.can_start is True
    assert bridge.failure_groups == [
        {
            "code": "quota_exhausted",
            "count": 115,
            "symbols": [],
            "intervals": [],
        }
    ]


def test_rs_restart_clears_terminal_quota_evidence_before_budget_check(
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    bridge._failed_count = 115
    bridge._on_finished(
        RunResult(
            RunStatus.FAILED,
            reliability=AnalysisReliability(
                0,
                115,
                0,
                Decimal(0),
                False,
                "quota_exhausted",
            ),
        )
    )
    pool = QThreadPool.globalInstance()
    monkeypatch.setattr(pool, "start", lambda _task: None)

    assert bridge.start() is True

    assert bridge.failed_count == 0
    assert bridge.failure_groups == []
    assert bridge.outcome_visible is False


def test_rs_preflight_failures_replace_stale_presentation(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    bridge._on_progress(
        RunProgress(
            "FETCHING",
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
        RunProgress(
            "FETCHING",
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


def test_rs_budget_confirmation_is_consumed_before_launch(
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    bridge._budget_snapshot = AnalysisBudgetSnapshot(
        100,
        6,
        600,
        0,
        600,
        50,
        "Longbridge 服务端量化",
    )
    launched: list[object] = []
    monkeypatch.setattr(bridge, "_launch_run", launched.append)

    assert bridge.requires_budget_confirmation is True
    assert bridge.confirm_budget_and_start() is True

    assert launched == [request]
    assert bridge.requires_budget_confirmation is False
    assert bridge._budget_request is None
    assert bridge._budget_snapshot is None


def test_rs_futu_quota_shortfall_only_allows_whole_run_yahoo(
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    bridge._budget_snapshot = AnalysisBudgetSnapshot(
        123,
        6,
        738,
        0,
        738,
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


def test_rs_blocked_budget_never_launches_or_allows_confirmation(
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    bridge = RsRunBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)
    bridge.set_end_date("2026-07-24")
    request = bridge.build_request()
    assert request is not None
    bridge._budget_request = request
    calls: list[object] = []
    monkeypatch.setattr(
        type(scenario_application),
        "run",
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
