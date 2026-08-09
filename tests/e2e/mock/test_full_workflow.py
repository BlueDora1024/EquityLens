from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_toolbox.analyses.rs_strength.application.models import RunRequest, RunStatus
from stock_toolbox.composition import build_application
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_offline_desktop_core_runs_import_pool_rs_and_history(
    tmp_path: Path,
) -> None:
    app = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="full-workflow",
    )

    imported = app.import_securities("IREN, NVDA, AMD, TQQQ, MISSING")
    assert imported.success_count == 3
    assert imported.excluded == (("TQQQ.US", "LEVERAGED_ETF"),)
    assert imported.unavailable == (("MISSING.US", "symbol_unavailable"),)

    securities = app.master_data.list_securities()
    assert tuple(item.canonical_symbol for item in securities) == (
        "AMD.US",
        "IREN.US",
        "NVDA.US",
    )
    assert all(item.bindings for item in securities)
    pool = app.master_data.create_watchlist("Tech Leaders")
    pool = app.master_data.add_watchlist_members(
        pool.id,
        tuple(
            (security.id, security.bindings[0].id)
            for security in securities
        ),
    )
    assert len(pool.memberships) == 3

    progress = []
    result = app.run(
        RunRequest(
            pool.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M", "6M", "1Y"),
            None,
        ),
        progress=progress.append,
    )

    assert result.status is RunStatus.READY
    assert result.output is not None
    assert len(result.output.stock_results) == 9
    assert progress[-1].stage == "SAVING"
    assert app.latest_history() is not None


def test_market_data_smoke_reads_profile_calendar_and_bars_without_mutation(
    tmp_path: Path,
) -> None:
    app = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="market-smoke",
    )

    result = app.test_market_data_connection(
        "IREN.US",
        "SPY.US",
    )

    assert result.ok
    assert result.code == "MARKET_DATA_OK"
    assert result.details[0] == "IREN.US"
    assert int(result.details[2]) > 0
    assert app.master_data.list_securities() == ()
    assert app.list_history() == ()
