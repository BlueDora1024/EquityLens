from datetime import date
from pathlib import Path

from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
    TurningPointRunStatus,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    TurningPointTradeSide,
)
from stock_toolbox.composition import build_application
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_offline_turning_point_run_persists_complete_history(tmp_path: Path) -> None:
    app = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="turning-point",
    )
    imported = app.import_securities("IREN, NVDA, AMD")
    assert imported.success_count == 3
    pool = app.master_data.create_watchlist("Turning Point Lab")
    securities = app.master_data.list_securities()
    app.master_data.add_watchlist_members(
        pool.id,
        tuple((item.id, item.bindings[0].id) for item in securities),
    )

    progress = []
    result = app.run_turning_point(
        TurningPointRequest(
            pool.id,
            (
                CandleInterval.MIN_30,
                CandleInterval.MIN_60,
                CandleInterval.DAY,
            ),
            date(2026, 7, 24),
        ),
        progress=progress.append,
    )

    assert result.status in {
        TurningPointRunStatus.READY,
        TurningPointRunStatus.PARTIAL,
    }
    assert result.run is not None
    assert len(result.run.results) == 3
    assert {item.symbol for item in result.run.results} == {
        "AMD.US",
        "IREN.US",
        "NVDA.US",
    }
    assert all(len(item.period_results) == 3 for item in result.run.results)
    assert result.run.matched_count >= 1
    assert any(
        item.stage == "COMPUTE" and item.completed == item.total == 9
        for item in progress
    )
    assert progress[-2].stage == "ANNOTATE_RISK"
    assert progress[-2].total == result.run.matched_count
    assert progress[-1].stage == "SAVE"
    history = app.list_turning_point_history()
    assert len(history) == 1
    assert history[0]["run_id"] == result.run.run_id
    assert result.run.run_id in app.export_turning_point_history(
        result.run.run_id,
        "json",
    )
    csv_export = app.export_turning_point_history(result.run.run_id, "csv")
    markdown_export = app.export_turning_point_history(
        result.run.run_id,
        "markdown",
    )
    assert "attention_score" in csv_export
    assert "关注度" in markdown_export
    assert "AAA" not in csv_export
    assert "BBB" not in markdown_export


def test_offline_left_cd_run_freezes_trade_side(tmp_path: Path) -> None:
    app = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="turning-point-left",
    )
    app.import_securities("IREN, NVDA, AMD")
    pool = app.master_data.create_watchlist("Left CD Lab")
    securities = app.master_data.list_securities()
    app.master_data.add_watchlist_members(
        pool.id,
        tuple((item.id, item.bindings[0].id) for item in securities),
    )
    request = TurningPointRequest(
        pool.id,
        (CandleInterval.MIN_30, CandleInterval.DAY),
        date(2026, 7, 24),
        trade_side=TurningPointTradeSide.LEFT_CD,
    )

    result = app.run_turning_point(request)

    assert result.run is not None
    assert result.run.request.trade_side is TurningPointTradeSide.LEFT_CD
    assert result.run.algorithm_version == "turning-point-v7"
    assert all(
        period.signal_kind in {None, "CD_LEFT_ENTRY"}
        for row in result.run.results
        for period in row.period_results
    )
    payload = app.list_turning_point_history()[0]["payload"]
    assert payload["request"]["trade_side"] == "LEFT_CD"
    csv_export = app.export_turning_point_history(result.run.run_id, "csv")
    markdown_export = app.export_turning_point_history(
        result.run.run_id,
        "markdown",
    )
    assert "trade_side" in csv_export
    assert "交易侧：左侧 · CD" in markdown_export


def test_turning_point_service_rejects_today_or_future_before_provider(
    tmp_path: Path,
) -> None:
    app = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="turning-point-date-boundary",
    )

    result = app.run_turning_point(
        TurningPointRequest(
            "missing-watchlist",
            (CandleInterval.DAY,),
            date(2999, 1, 1),
        )
    )

    assert result.status is TurningPointRunStatus.FAILED
    assert result.error_code == "historical_date_required"
