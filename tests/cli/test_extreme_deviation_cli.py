from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
)
from stock_toolbox.cli import main
from stock_toolbox.composition import build_application
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_extreme_deviation_full_scenario_is_machine_readable(
    tmp_path: Path,
    capsys,
) -> None:
    code = main(
        [
            "--env",
            "scenario",
            "--home",
            str(tmp_path),
            "analysis",
            "extreme-deviation",
            "run",
            "--scenario",
            "extreme-deviation-full",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis_type"] == "extreme_deviation"
    assert payload["result"]["result_count"] == 3
    assert payload["result"]["period_count"] == 12
    assert payload["result"]["cache_fetched"] == 12


def test_extreme_deviation_history_list_is_module_scoped(
    tmp_path: Path,
    capsys,
) -> None:
    code = main(
        [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "analysis",
            "extreme-deviation",
            "history",
            "list",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "analysis_type": "extreme_deviation",
        "runs": [],
        "schema_version": "cli-output-v1",
    }


def test_extreme_deviation_report_is_scriptable(
    tmp_path: Path,
    capsys,
) -> None:
    app = build_application(RuntimeEnvironment.INTEGRATION, home=tmp_path)
    assert app.import_securities("IREN, NVDA").success_count == 2
    pool = app.master_data.create_watchlist("CLI Report")
    securities = app.master_data.list_securities()
    pool = app.master_data.add_watchlist_members(
        pool.id,
        tuple((item.id, item.bindings[0].id) for item in securities),
    )
    result = app.run_extreme_deviation(
        ExtremeDeviationRequest(
            pool.id,
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        )
    )
    assert result.run is not None

    code = main(
        [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "analysis",
            "extreme-deviation",
            "report",
            "--run-id",
            result.run.run_id,
            "--symbols",
            "IREN.US,NVDA.US",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis_type"] == "extreme_deviation"
    assert payload["report"]["selected_symbols"] == ["IREN.US", "NVDA.US"]
    assert "不构成投资建议" in payload["report"]["content"]
