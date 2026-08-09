from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
    ExtremeDeviationRunStatus,
)
from stock_toolbox.composition import build_application
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_offline_extreme_deviation_run_uses_supported_periods_and_history(
    tmp_path: Path,
) -> None:
    app = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="extreme-deviation",
    )
    assert app.import_securities("IREN, NVDA, AMD").success_count == 3
    pool = app.master_data.create_watchlist("Extreme Lab")
    securities = app.master_data.list_securities()
    app.master_data.add_watchlist_members(
        pool.id,
        tuple((item.id, item.bindings[0].id) for item in securities),
    )
    intervals = (
        CandleInterval.MIN_30,
        CandleInterval.MIN_60,
        CandleInterval.DAY,
        CandleInterval.WEEK,
    )
    progress = []

    result = app.run_extreme_deviation(
        ExtremeDeviationRequest(
            pool.id,
            intervals,
            date(2026, 7, 24),
            ("IREN.US", "NVDA.US"),
        ),
        progress=progress.append,
    )

    assert result.status in {
        ExtremeDeviationRunStatus.READY,
        ExtremeDeviationRunStatus.PARTIAL,
    }
    assert result.run is not None
    assert result.run.algorithm_version == "extreme-deviation-v2"
    assert tuple(item.symbol for item in result.run.results) == (
        "IREN.US",
        "NVDA.US",
    )
    assert all(len(item.periods) == 4 for item in result.run.results)
    assert progress[-1].stage == "SAVE"
    history = app.list_extreme_deviation_history()
    assert history[0]["run_id"] == result.run.run_id
    assert result.run.run_id in app.export_extreme_deviation_history(
        result.run.run_id,
        "json",
    )
    csv_export = app.export_extreme_deviation_history(result.run.run_id, "csv")
    markdown_export = app.export_extreme_deviation_history(
        result.run.run_id,
        "markdown",
    )
    assert "symbol,classification,consensus,interval,score,label,confidence,error" in csv_export
    assert "# 极值偏离结果" in markdown_export
    assert "IREN.US" in csv_export

    report = app.generate_extreme_deviation_report(
        result.run.run_id,
        ("IREN.US",),
    )
    assert report.selected_symbols == ("IREN.US",)
    assert report.prompt_version == "extreme-deviation-report-v2"
    assert "技术指标复盘，不构成投资建议。" in report.content
    updated = app.list_extreme_deviation_history()[0]["payload"]
    assert isinstance(updated, dict)
    assert updated["ai_reports"][0]["content"] == report.content


def test_market_data_smoke_covers_supported_extreme_deviation_periods(
    tmp_path: Path,
) -> None:
    app = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
    )

    result = app.test_extreme_deviation_market_data_connection("IREN.US")

    assert result.ok
    assert result.code == "EXTREME_DEVIATION_MARKET_DATA_OK"
    assert result.details[0] == "IREN.US"
    assert set(result.details[2:]) == {
        "30m:650",
        "60m:650",
        "1d:650",
        "1w:650",
    }
