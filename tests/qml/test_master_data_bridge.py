from __future__ import annotations

from pathlib import Path

from stock_toolbox.composition import build_application
from stock_toolbox.core.securities.import_service import ImportProgress
from stock_toolbox.desktop_qml.master_data_bridge import MasterDataBridge
from stock_toolbox.runtime.environment import RuntimeEnvironment
from tests.qml.helpers import seeded_watchlist


def test_master_data_bridge_reads_csv_for_import(
    scenario_application,
    tmp_path: Path,
) -> None:
    target = tmp_path / "symbols.csv"
    target.write_text("ticker\nIREN\nNVDA\n", encoding="utf-8")
    bridge = MasterDataBridge(scenario_application)

    assert "IREN" in bridge.read_import_file(str(target))
    assert bridge.import_preview == {
        "column": "ticker",
        "rows": 2,
        "recognized": 2,
        "duplicates": 0,
        "invalid": 0,
    }


def test_master_data_bridge_requires_choice_for_ambiguous_columns(
    scenario_application,
    tmp_path: Path,
) -> None:
    target = tmp_path / "broker-export.csv"
    target.write_text(
        "Symbol,Underlying,Price\nAAPL,QQQ,210\nNVDA,SPY,180\n",
        encoding="utf-8",
    )
    bridge = MasterDataBridge(scenario_application)

    assert bridge.read_import_file(str(target)) == ""
    assert bridge.import_file_requires_choice is True
    assert [item["name"] for item in bridge.import_file_candidates] == [
        "Symbol",
        "Underlying",
    ]

    assert bridge.select_import_column(1) is True
    assert bridge.import_file_text == "QQQ.US\nSPY.US"
    assert bridge.import_preview["column"] == "Underlying"


def test_import_progress_does_not_invalidate_all_master_data(
    qtbot,
    scenario_application,
) -> None:
    bridge = MasterDataBridge(scenario_application)
    master_changes = 0
    import_changes = 0

    def record_master_change() -> None:
        nonlocal master_changes
        master_changes += 1

    def record_import_change() -> None:
        nonlocal import_changes
        import_changes += 1

    bridge.changed.connect(record_master_change)
    bridge.import_changed.connect(record_import_change)

    with qtbot.waitSignal(bridge.import_finished, timeout=5_000):
        assert bridge.import_securities("IREN, NVDA")

    assert import_changes >= 2
    assert master_changes == 1


def test_import_progress_uses_weighted_monotonic_stages(
    scenario_application,
) -> None:
    bridge = MasterDataBridge(scenario_application)

    observed: list[float] = []
    for event in (
        ImportProgress("PARSING", 0, 10),
        ImportProgress("FETCHING_PROFILES", 0, 10),
        ImportProgress("CLASSIFYING", 0, 10),
        ImportProgress("ITEM", 1, 10, "AAPL.US", "IMPORTED"),
        ImportProgress("SAVING", 10, 10),
        ImportProgress("DONE", 10, 10),
    ):
        bridge._on_import_progress(event)
        observed.append(bridge.import_progress)

    assert observed == sorted(observed)
    assert observed[0] > 0
    assert observed[1] >= 0.15
    assert observed[2] >= 0.25
    assert observed[-2] >= 0.95
    assert observed[-1] == 1.0


def test_global_security_refresh_runs_in_background_and_persists_snapshot(
    qtbot,
    scenario_application,
) -> None:
    scenario_application.import_securities("IREN, NVDA")
    bridge = MasterDataBridge(scenario_application)

    with qtbot.waitSignal(bridge.refresh_finished, timeout=5_000):
        assert bridge.refresh_securities() is True
        assert bridge.refresh_running is True

    assert bridge.refresh_running is False
    assert bridge.refresh_progress == 1.0
    assert bridge.refresh_summary["updated"] == 2
    assert bridge.refresh_summary["unavailable"] == 0
    rows = bridge.securities
    assert all(row["availabilityStatus"] == "ACTIVE" for row in rows)
    assert all(row["cachedLastPrice"] != "" for row in rows)
    assert all(row["cachedMarketValue"] != "" for row in rows)


def test_master_data_bridge_sorts_and_filters_global_securities(
    scenario_application,
) -> None:
    seeded_watchlist(scenario_application)
    bridge = MasterDataBridge(scenario_application)

    assert [item["symbol"] for item in bridge.securities] == [
        "AMD.US",
        "IREN.US",
        "NVDA.US",
    ]

    bridge.set_search("iren")

    assert [item["symbol"] for item in bridge.securities] == ["IREN.US"]


def test_master_data_properties_reuse_one_loaded_snapshot(
    scenario_application,
    monkeypatch,
) -> None:
    seeded_watchlist(scenario_application)
    bridge = MasterDataBridge(scenario_application)
    watchlist_id = str(bridge.watchlists[0]["id"])
    classification_id = str(bridge.classifications[0]["id"])

    def unexpected_read(*_args, **_kwargs):
        raise AssertionError("QML property binding repeated a database read")

    monkeypatch.setattr(
        scenario_application.master_data,
        "list_securities",
        unexpected_read,
    )
    monkeypatch.setattr(
        scenario_application.master_data,
        "list_classifications",
        unexpected_read,
    )
    monkeypatch.setattr(
        scenario_application.master_data,
        "list_watchlists",
        unexpected_read,
    )
    monkeypatch.setattr(
        scenario_application.master_data,
        "get_watchlist",
        unexpected_read,
    )

    bridge.select_watchlist(watchlist_id)
    bridge.select_classification(classification_id)

    assert bridge.securities
    assert bridge.classifications
    assert bridge.watchlists
    assert bridge.selected_watchlist_members
    assert isinstance(bridge.watchlist_candidates, list)
    assert isinstance(bridge.classification_members, list)


def test_master_data_bridge_projects_user_facing_symbol_number_and_details(
    scenario_application,
) -> None:
    scenario_application.import_securities("NVDA, IREN")
    bridge = MasterDataBridge(scenario_application)

    rows = bridge.securities

    assert [row["rowNumber"] for row in rows] == [1, 2]
    assert [row["displaySymbol"] for row in rows] == ["IREN", "NVDA"]
    assert all(not str(row["displaySymbol"]).endswith(".US") for row in rows)
    assert rows[0]["exchange"] == "NASDAQ"
    assert rows[0]["currency"] == "USD"
    assert rows[0]["assetTypeText"] == "普通股"
    assert rows[0]["classificationText"]


def test_master_data_bridge_reports_delete_impact_and_cascades_pool_memberships(
    scenario_application,
) -> None:
    scenario_application.import_securities("NVDA")
    security = scenario_application.master_data.list_securities()[0]
    for name in ("核心池", "复盘池"):
        watchlist = scenario_application.master_data.create_watchlist(name)
        scenario_application.master_data.add_watchlist_members(
            watchlist.id,
            ((security.id, security.bindings[0].id),),
        )
    bridge = MasterDataBridge(scenario_application)

    impact = bridge.security_delete_impact(security.id)

    assert impact["watchlistCount"] == 2
    assert bridge.delete_security(security.id)
    assert bridge.securities == []
    assert all(
        not watchlist.memberships
        for watchlist in scenario_application.master_data.list_watchlists()
    )


def test_master_data_bridge_loads_and_formats_live_security_snapshot(
    qtbot,
    scenario_application,
) -> None:
    scenario_application.import_securities("NVDA")
    security = scenario_application.master_data.list_securities()[0]
    bridge = MasterDataBridge(scenario_application)

    with qtbot.waitSignal(bridge.snapshot_finished, timeout=5_000):
        assert bridge.load_security_snapshot(security.id)

    assert bridge.snapshot_running is False
    assert bridge.security_snapshot["securityId"] == security.id
    assert bridge.security_snapshot["lastPrice"].startswith("$")
    assert "亿" in bridge.security_snapshot["marketValue"]


def test_master_data_bridge_edits_shared_classifications(
    scenario_application,
) -> None:
    scenario_application.import_securities("IREN")
    security = scenario_application.master_data.list_securities()[0]
    bridge = MasterDataBridge(scenario_application)

    assert bridge.create_classification("AI 基础设施") is True
    classification_id = next(
        str(item["id"])
        for item in bridge.classifications
        if item["name"] == "AI 基础设施"
    )
    assert bridge.set_security_classifications(
        security.id,
        [classification_id],
    )

    refreshed = scenario_application.master_data.get_security(security.id)
    assert [binding.classification_name for binding in refreshed.bindings] == [
        "AI 基础设施"
    ]


def test_master_data_bridge_reports_and_removes_a_referenced_classification(
    scenario_application,
) -> None:
    scenario_application.import_securities("IREN")
    security = scenario_application.master_data.list_securities()[0]
    replacement = scenario_application.master_data.create_classification(
        "替代标签"
    )
    security = scenario_application.master_data.set_security_classifications(
        security.id,
        (security.bindings[0].classification_id, replacement.id),
    )
    removed = security.bindings[0]
    watchlist = scenario_application.master_data.create_watchlist("复盘池")
    scenario_application.master_data.add_watchlist_members(
        watchlist.id,
        ((security.id, removed.id),),
    )
    bridge = MasterDataBridge(scenario_application)

    impact = bridge.security_classification_removal_impact(
        security.id,
        removed.classification_id,
    )

    assert impact["watchlistCount"] == 1
    assert impact["watchlistNames"] == ["复盘池"]
    assert impact["replacementName"] == "替代标签"
    assert bridge.remove_security_classification(
        security.id,
        removed.classification_id,
    )
    refreshed = scenario_application.master_data.get_security(security.id)
    assert tuple(item.classification_name for item in refreshed.bindings) == (
        "替代标签",
    )
    assert (
        scenario_application.master_data.get_watchlist(watchlist.id)
        .memberships[0]
        .participating_classification_name
        == "替代标签"
    )


def test_master_data_bridge_projects_selected_classification_members_and_candidates(
    scenario_application,
) -> None:
    scenario_application.import_securities("AAPL, AMD, NVDA")
    securities = scenario_application.master_data.list_securities()
    selected = securities[0]
    classification = scenario_application.master_data.create_classification(
        "自定义标签"
    )
    scenario_application.master_data.set_security_classifications(
        selected.id,
        (classification.id,),
    )
    bridge = MasterDataBridge(scenario_application)

    bridge.select_classification(classification.id)

    assert [row["id"] for row in bridge.classification_members] == [selected.id]
    assert bridge.classification_members[0]["displaySymbol"] == "AAPL"
    assert {
        row["displaySymbol"] for row in bridge.classification_candidates
    } == {"AMD", "NVDA"}


def test_master_data_bridge_batch_adds_classification_with_partial_success(
    scenario_application,
) -> None:
    scenario_application.import_securities("AAPL, AMD, IREN")
    securities = {
        item.canonical_symbol: item
        for item in scenario_application.master_data.list_securities()
    }
    target = scenario_application.master_data.create_classification("目标标签")
    scenario_application.master_data.set_security_classifications(
        securities["AAPL.US"].id,
        (target.id,),
    )
    full_ids = tuple(
        scenario_application.master_data.create_classification(name).id
        for name in ("标签一", "标签二", "标签三")
    )
    scenario_application.master_data.set_security_classifications(
        securities["AMD.US"].id,
        full_ids,
    )
    scenario_application.master_data.set_security_classifications(
        securities["IREN.US"].id,
        (),
    )
    bridge = MasterDataBridge(scenario_application)

    result = bridge.add_classification_members(
        target.id,
        [
            securities["AAPL.US"].id,
            securities["AMD.US"].id,
            securities["IREN.US"].id,
            securities["IREN.US"].id,
        ],
    )

    assert result["summary"] == {"added": 1, "existing": 1, "failed": 1}
    assert [row["category"] for row in result["details"]] == [
        "existing",
        "failed",
        "added",
    ]
    assert result["details"][1]["reason"] == "已有 3 个标签，达到上限"
    assert target.id in {
        binding.classification_id
        for binding in scenario_application.master_data.get_security(
            securities["IREN.US"].id
        ).bindings
    }
    assert bridge.classification_batch_result == result


def test_master_data_bridge_watchlist_candidates_exclude_existing_members(
    scenario_application,
) -> None:
    scenario_application.import_securities("IREN, NVDA")
    securities = {
        item.canonical_symbol: item
        for item in scenario_application.master_data.list_securities()
    }
    watchlist = scenario_application.master_data.create_watchlist("复盘池")
    scenario_application.master_data.add_watchlist_members(
        watchlist.id,
        ((
            securities["IREN.US"].id,
            securities["IREN.US"].bindings[0].id,
        ),),
    )
    bridge = MasterDataBridge(scenario_application)

    bridge.select_watchlist(watchlist.id)

    assert [row["displaySymbol"] for row in bridge.watchlist_candidates] == [
        "NVDA"
    ]
    member = bridge.selected_watchlist_members[0]
    assert member["displaySymbol"] == "IREN"
    assert ".US" not in str(member["displaySymbol"])
    assert member["bindings"]


def test_master_data_bridge_batch_adds_watchlist_members(
    scenario_application,
) -> None:
    scenario_application.import_securities("AAPL, AMD")
    securities = scenario_application.master_data.list_securities()
    bridge = MasterDataBridge(scenario_application)
    watchlist_id = bridge.create_watchlist("批量池")

    result = bridge.add_watchlist_members_batch(
        watchlist_id,
        [
            {
                "securityId": security.id,
                "bindingId": security.bindings[0].id,
            }
            for security in securities
        ],
    )

    assert result == {"added": 2}
    assert len(
        scenario_application.master_data.get_watchlist(watchlist_id).memberships
    ) == 2


def test_master_data_bridge_updates_pool_local_participating_binding(
    scenario_application,
) -> None:
    scenario_application.import_securities("IREN")
    security = scenario_application.master_data.list_securities()[0]
    extra = scenario_application.master_data.create_classification("加密基础设施")
    security = scenario_application.master_data.set_security_classifications(
        security.id,
        (security.bindings[0].classification_id, extra.id),
    )
    watchlist = scenario_application.master_data.create_watchlist("复盘池")
    scenario_application.master_data.add_watchlist_members(
        watchlist.id,
        ((security.id, security.bindings[0].id),),
    )
    bridge = MasterDataBridge(scenario_application)
    bridge.select_watchlist(watchlist.id)

    assert bridge.update_watchlist_member_binding(
        watchlist.id,
        security.id,
        security.bindings[1].id,
    )

    updated = scenario_application.master_data.get_watchlist(watchlist.id)
    assert (
        updated.memberships[0].participating_binding_id
        == security.bindings[1].id
    )
    assert bridge.selected_watchlist_members[0]["classification"] == "加密基础设施"


def test_master_data_bridge_renames_and_deletes_global_entities(
    scenario_application,
) -> None:
    bridge = MasterDataBridge(scenario_application)
    classification_id = str(
        bridge.create_classification("临时分类")
        and next(
            row["id"]
            for row in bridge.classifications
            if row["name"] == "临时分类"
        )
    )
    watchlist_id = bridge.create_watchlist("临时池")
    scenario_application.import_securities("IREN")
    security_id = scenario_application.master_data.list_securities()[0].id

    assert bridge.rename_classification(classification_id, "重命名分类")
    assert bridge.rename_watchlist(watchlist_id, "重命名池")
    assert bridge.delete_watchlist(watchlist_id)
    assert bridge.delete_classification(classification_id)
    assert bridge.delete_security(security_id)
    assert bridge.securities == []


def test_master_data_bridge_import_reports_each_product_bucket(
    qtbot,
    scenario_application,
) -> None:
    bridge = MasterDataBridge(scenario_application)

    with qtbot.waitSignal(bridge.import_finished, timeout=5_000):
        assert bridge.import_securities("IREN, NVDA, IREN") is True

    assert bridge.import_running is False
    assert bridge.import_summary["success"] == 2
    assert bridge.import_summary["duplicate"] == 1
    assert bridge.import_completed == bridge.import_total == 3
    assert bridge.import_progress == 1.0
    assert [item["symbol"] for item in bridge.securities] == [
        "IREN.US",
        "NVDA.US",
    ]


def test_master_data_bridge_can_clear_one_completed_import_session(
    qtbot,
    scenario_application,
) -> None:
    bridge = MasterDataBridge(scenario_application)

    with qtbot.waitSignal(bridge.import_finished, timeout=5_000):
        assert bridge.import_securities("IREN, NVDA, IREN") is True

    assert bridge.import_summary
    assert bridge.import_details
    assert bridge.import_total == 3

    assert bridge.reset_import_session() is True

    assert bridge.import_summary == {}
    assert bridge.import_details == []
    assert bridge.import_completed == 0
    assert bridge.import_total == 0
    assert bridge.import_progress == 0.0
    assert bridge.import_preview == {}
    assert bridge.import_status == ""


def test_master_data_bridge_import_process_rejects_repeat_clicks_and_streams_result(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
    )
    bridge = MasterDataBridge(application)
    monkeypatch.setenv("PYTHONPATH", str(Path.cwd() / "src"))
    worker = Path.cwd() / ".venv" / "bin" / "stock-toolbox"
    monkeypatch.setattr(bridge, "_import_worker_program", lambda: worker)
    monkeypatch.setattr(
        bridge,
        "_import_worker_arguments",
        lambda: [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "securities",
            "import-worker",
        ],
    )

    with qtbot.waitSignal(bridge.import_finished, timeout=10_000):
        assert bridge.import_securities("IREN, NVDA") is True
        assert bridge.import_running is True
        assert bridge.import_securities("AMD") is False

    assert bridge.import_running is False
    assert bridge.import_summary["success"] == 2
    assert [item["symbol"] for item in bridge.securities] == [
        "IREN.US",
        "NVDA.US",
    ]
    application.close()
