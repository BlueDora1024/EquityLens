from __future__ import annotations

from stock_toolbox.desktop_qml.scenario_bridge import ScenarioBridge


def test_scenario_bridge_lists_bundled_isolated_scenarios(
    scenario_application,
) -> None:
    bridge = ScenarioBridge(scenario_application)

    assert len(bridge.scenarios) >= 2
    assert all(row["id"] and row["title"] for row in bridge.scenarios)
    assert "不会读取或修改正式数据库" in bridge.isolation_note


def test_scenario_bridge_runs_selected_scenario_off_main_thread(
    qtbot,
    scenario_application,
) -> None:
    bridge = ScenarioBridge(scenario_application)
    scenario_id = str(bridge.scenarios[0]["id"])

    with qtbot.waitSignal(bridge.finished, timeout=10_000):
        assert bridge.run_scenario(scenario_id) is True
        assert bridge.running is True

    assert bridge.running is False
    assert bridge.result["terminal"] == "succeeded"
