from __future__ import annotations

from pathlib import Path

import pytest

from stock_toolbox.devtools.catalog import ScenarioCatalog
from stock_toolbox.devtools.runner import ScenarioRunner

FAILURE_SCENARIOS = (
    "timeout-recovery",
    "repeated-429",
    "auth-fatal",
    "quota-fatal",
    "exactly-80-partial",
    "below-80-failure",
    "database-busy",
    "disk-blocked",
    "user-cancel",
    "ai-old-report",
)


@pytest.mark.parametrize("scenario_id", FAILURE_SCENARIOS)
def test_failure_scenario_runs_through_shared_composition(
    scenario_id: str,
    tmp_path: Path,
) -> None:
    scenario = ScenarioCatalog.bundled().get(scenario_id)

    result = ScenarioRunner().run(
        scenario,
        home=tmp_path / scenario_id,
    )

    assert result["scenario_assertions_passed"] is True
    assert result["operation_terminal"] == scenario.expected["operation_terminal"]
    assert result["history_count"] == scenario.expected["history_count"]
    assert result["provider_call_count"] <= scenario.max_provider_calls
    assert result["provider_calls_after_terminal"] == result["provider_call_count"]


def test_failure_scenario_catalog_contains_ten_integrated_fixtures() -> None:
    catalog_ids = {item.id for item in ScenarioCatalog.bundled().list()}

    assert set(FAILURE_SCENARIOS) <= catalog_ids
