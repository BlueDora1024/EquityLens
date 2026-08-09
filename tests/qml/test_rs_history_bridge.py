from __future__ import annotations

import zipfile
from datetime import UTC, date, datetime
from threading import Event

import pytest

from stock_toolbox.analyses.rs_strength.application.models import RunRequest
from stock_toolbox.analyses.rs_strength.application.report import (
    RSStrengthReport,
)
from stock_toolbox.core.operations.registry import CancelResult
from stock_toolbox.desktop_qml.rs_history_bridge import RsHistoryBridge
from stock_toolbox.desktop_qml.shell_bridge import ShellBridge
from stock_toolbox.desktop_qml.time_display import display_datetime
from stock_toolbox.infrastructure.ai.openai_compatible import AIAdapterError
from tests.qml.helpers import seeded_watchlist


def test_rs_history_bridge_lists_latest_ten_and_frozen_results(
    scenario_application,
    tmp_path,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    result = scenario_application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M", "6M", "1Y"),
            None,
        )
    )
    bridge = RsHistoryBridge(scenario_application)

    assert len(bridge.history) == 1
    assert not bridge.select_run("missing")
    assert bridge.select_run(str(result.run_id)) is True
    assert len(bridge.ranges) == 3
    assert bridge.selected_range_id == bridge.ranges[0]["id"]
    assert len(bridge.stock_results) == 3
    assert {
        item["rangeId"] for item in bridge.stock_results
    } == {bridge.selected_range_id}
    descending_rs = [float(item["rs"]) for item in bridge.stock_results]
    assert descending_rs == sorted(descending_rs, reverse=True)
    assert bridge.stock_sort_descending is True
    assert bridge.selected_range_summary["benchmark"] == "SPY"
    assert bridge.selected_range_summary["label"] == bridge.ranges[0]["label"]
    assert bridge.selected_range_summary["benchmarkReturn"] == (
        bridge.stock_results[0]["benchmarkReturn"]
    )
    assert bridge.toggle_stock_sort() is True
    ascending_rs = [float(item["rs"]) for item in bridge.stock_results]
    assert ascending_rs == sorted(ascending_rs)
    assert bridge.stock_sort_descending is False
    assert bridge.select_range(str(bridge.ranges[1]["id"]))
    assert len(bridge.stock_results) == 3
    assert {
        item["rangeId"] for item in bridge.stock_results
    } == {bridge.selected_range_id}
    assert [float(item["rs"]) for item in bridge.stock_results] == sorted(
        float(item["rs"]) for item in bridge.stock_results
    )
    assert bridge.selected_range_summary["label"] == bridge.ranges[1]["label"]
    assert not bridge.select_range("missing")
    assert bridge.classification_results
    assert all(
        str(item["scoreText"]) == "—"
        or (
            str(item["scoreText"]).count(".") == 1
            and len(str(item["scoreText"]).split(".")[-1]) == 1
        )
        for item in bridge.classification_results
    )
    unscored = [
        item
        for item in bridge.classification_results
        if item["score"] is None
    ]
    assert unscored
    assert all(
        str(item["statusLabel"]).startswith("样本不足")
        for item in unscored
    )
    assert all(item["statusHelpVisible"] is False for item in unscored)
    assert all(
        item["statusHelpVisible"] is True
        for item in bridge.classification_results
        if item["score"] is not None
    )
    assert all(
        item["statusLabel"] != item["status"]
        for item in bridge.classification_results
    )
    assert all(
        item["statusExplanation"]
        and any(
            str(period["label"]) in str(item["statusExplanation"])
            for period in bridge.ranges
        )
        for item in bridge.classification_results
    )
    assert bridge.selected_summary["benchmark"] == "SPY"
    assert bridge.export_default_name.startswith("RS统计_")
    assert bridge.export_default_name.endswith(".zip")
    assert "/" not in bridge.export_default_name
    assert ":" not in bridge.export_default_name
    assert bridge.export_default_url.startswith("file:")
    target = tmp_path / "complete-history.zip"
    assert bridge.export_history(str(result.run_id), "csv", str(target))
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {
            "metadata.csv",
            "stocks.csv",
            "classifications.csv",
            "failures.csv",
        }
    target_without_suffix = tmp_path / "完整历史"
    assert bridge.export_history(
        str(result.run_id),
        "csv",
        str(target_without_suffix),
    )
    assert not target_without_suffix.exists()
    with zipfile.ZipFile(target_without_suffix.with_suffix(".zip")) as archive:
        assert "stocks.csv" in archive.namelist()


def test_rs_history_bridge_localizes_untouched_default_names(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    result = scenario_application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M",),
            None,
        )
    )
    snapshot = scenario_application.get_history(str(result.run_id))
    expected = (
        f"{snapshot.header.original_run_name} "
        f"{display_datetime(snapshot.header.completed_at, 'Asia/Shanghai')}"
    )
    bridge = RsHistoryBridge(scenario_application)

    assert bridge.history[0]["name"] == expected
    assert bridge.select_run(str(result.run_id))
    assert bridge.selected_summary["name"] == expected

    assert bridge.update_history(
        str(result.run_id),
        "我的复盘名称",
        "",
        False,
    )
    assert bridge.history[0]["name"] == "我的复盘名称"
    assert bridge.selected_summary["name"] == "我的复盘名称"


def test_rs_history_bridge_generates_and_reloads_saved_ai_report(
    qtbot,
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    result = scenario_application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M", "6M"),
            None,
        )
    )
    bridge = RsHistoryBridge(scenario_application)
    assert bridge.select_run(str(result.run_id))

    assert bridge.ai_configured
    assert bridge.report_text == ""
    with qtbot.waitSignal(bridge.report_finished, timeout=5_000):
        assert bridge.generate_report()
        assert bridge.report_running

    assert not bridge.report_running
    assert bridge.report_error == ""
    assert "RS 相对强弱复盘，不构成投资建议。" in bridge.report_text
    reloaded = RsHistoryBridge(scenario_application)
    assert reloaded.select_run(str(result.run_id))
    assert reloaded.report_text == bridge.report_text


def test_rs_report_failure_preserves_saved_report_and_results(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    result = scenario_application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M", "6M"),
            None,
        )
    )
    bridge = RsHistoryBridge(scenario_application)
    assert bridge.select_run(str(result.run_id))
    with qtbot.waitSignal(bridge.report_finished, timeout=5_000):
        assert bridge.generate_report()
    prior_report = bridge.report_text
    prior_results = bridge.stock_results
    prior_summary = bridge.selected_summary
    prior_history_count = len(scenario_application.list_history())
    failed_calls = 0

    def fail_report(*_args, **_kwargs):
        nonlocal failed_calls
        failed_calls += 1
        raise AIAdapterError("rate_limited")

    monkeypatch.setattr(
        type(scenario_application),
        "generate_rs_strength_report",
        fail_report,
    )

    with qtbot.waitSignal(bridge.report_finished, timeout=5_000):
        assert bridge.generate_report()

    assert bridge.report_text == prior_report
    assert bridge.stock_results == prior_results
    assert bridge.selected_summary == prior_summary
    assert bridge.report_error == "AI 服务请求过于频繁，请稍后再试。"
    assert failed_calls == 1
    assert len(scenario_application.list_history()) == prior_history_count


def test_rs_report_is_close_safe_and_cancelable(
    qtbot,
    scenario_application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    result = scenario_application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M",),
            None,
        )
    )
    bridge = RsHistoryBridge(scenario_application)
    shell = ShellBridge(scenario_application)
    assert bridge.select_run(str(result.run_id))
    prior_results = bridge.stock_results
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
        "generate_rs_strength_report",
        blocked_report,
    )

    assert bridge.generate_report()
    assert entered.wait(timeout=1)
    assert scenario_application.registry.has_active_operations()
    assert shell.has_active_operation
    report_operation = scenario_application.registry.active_snapshots()[0]
    with qtbot.waitSignal(bridge.report_finished, timeout=2_000):
        assert (
            scenario_application.cancel_operation(
                report_operation.operation_id
            )
            is CancelResult.ACCEPTED
        )

    assert not scenario_application.registry.has_active_operations()
    assert bridge.stock_results == prior_results
    assert bridge.report_error == "AI 解读已取消。"
    shell.close()


def test_rs_async_report_completion_stays_scoped_to_origin_run(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    result = scenario_application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M",),
            None,
        )
    )
    bridge = RsHistoryBridge(scenario_application)
    assert bridge.select_run(str(result.run_id))
    bridge._report_text = "当前历史的旧报告"
    bridge._report_error = "当前历史的旧错误"
    report = RSStrengthReport(
        "model",
        "prompt",
        "另一个历史的新报告",
        datetime(2026, 7, 25, tzinfo=UTC),
        "hash",
    )

    bridge._on_report_finished("another-run", report)
    assert bridge.report_text == "当前历史的旧报告"
    assert bridge.report_error == "当前历史的旧错误"

    bridge._on_report_finished(
        "another-run",
        AIAdapterError("rate_limited"),
    )
    assert bridge.report_text == "当前历史的旧报告"
    assert bridge.report_error == "当前历史的旧错误"


def test_switching_history_resets_selected_range(
    scenario_application,
) -> None:
    watchlist = seeded_watchlist(scenario_application)
    first = scenario_application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M", "6M"),
            None,
        )
    )
    second_watchlist = scenario_application.master_data.create_watchlist(
        "第二组"
    )
    scenario_application.master_data.add_watchlist_members(
        second_watchlist.id,
        tuple(
            (security.id, security.bindings[0].id)
            for security in scenario_application.master_data.list_securities()
        ),
    )
    second = scenario_application.run(
        RunRequest(
            second_watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("1Y",),
            None,
        )
    )
    bridge = RsHistoryBridge(scenario_application)
    assert bridge.select_run(str(first.run_id))
    assert bridge.select_range(str(bridge.ranges[1]["id"]))

    assert bridge.select_run(str(second.run_id))

    assert len(bridge.ranges) == 1
    assert bridge.selected_range_id == bridge.ranges[0]["id"]
    assert bridge.stock_sort_descending is True
