import json
from pathlib import Path
from types import SimpleNamespace

from stock_toolbox.cli import main
from stock_toolbox.core.settings.models import ServiceTestResult


def test_cli_lists_scenarios_as_stable_json(capsys) -> None:
    exit_code = main(["--env", "dev", "scenario", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["schema_version"] == "cli-output-v1"
    assert [item["id"] for item in payload["scenarios"]] == [
        "ai-old-report",
        "auth-fatal",
        "below-80-failure",
        "benchmark-failure",
        "database-busy",
        "disk-blocked",
        "exactly-80-partial",
        "full-workflow",
        "partial-run",
        "quota-fatal",
        "repeated-429",
        "rs-benchmark-v1",
        "startup-empty",
        "timeout-recovery",
        "user-cancel",
    ]


def test_cli_validates_scenario_without_side_effects(capsys) -> None:
    exit_code = main(["--env", "dev", "scenario", "validate", "startup-empty", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["result"] == {"id": "startup-empty", "valid": True}


def test_cli_refuses_scenario_command_in_production(capsys) -> None:
    exit_code = main(["--env", "production", "scenario", "run", "startup-empty", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error"]["code"] == "DEVTOOLS_PRODUCTION_FORBIDDEN"


def test_cli_returns_stable_error_for_unknown_scenario(capsys) -> None:
    exit_code = main(["--env", "dev", "scenario", "validate", "missing", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 66
    assert payload["error"]["code"] == "SCENARIO_NOT_FOUND"


def test_cli_runs_complete_workflow_through_shared_application(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = main(
        [
            "--env",
            "dev",
            "--home",
            str(tmp_path),
            "scenario",
            "run",
            "full-workflow",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    expected = {
        "id": "full-workflow",
        "terminal": "succeeded",
        "security_count": 3,
        "excluded_count": 1,
        "unavailable_count": 1,
        "watchlist_member_count": 3,
        "run_status": "READY",
        "stock_result_count": 9,
        "history_count": 1,
        "exported": ["json", "markdown", "csv"],
    }
    assert {
        key: payload["result"][key]
        for key in expected
    } == expected
    assert payload["result"]["scenario_assertions_passed"] is True
    assert len(tuple(tmp_path.rglob("full-workflow.json"))) == 1
    assert len(tuple(tmp_path.rglob("full-workflow.md"))) == 1
    assert len(tuple(tmp_path.rglob("full-workflow.zip"))) == 1


def test_cli_runs_partial_and_fatal_scenarios_deterministically(
    tmp_path: Path,
    capsys,
) -> None:
    results = {}
    for scenario_id in ("partial-run", "benchmark-failure"):
        exit_code = main(
            [
                "--env",
                "dev",
                "--home",
                str(tmp_path),
                "scenario",
                "run",
                scenario_id,
                "--json",
            ]
        )
        assert exit_code == 0
        results[scenario_id] = json.loads(capsys.readouterr().out)["result"]

    assert results["partial-run"]["run_status"] == "PARTIAL"
    assert results["partial-run"]["stock_result_count"] == 12
    assert results["partial-run"]["history_count"] == 1
    assert results["benchmark-failure"]["run_status"] == "FAILED"
    assert results["benchmark-failure"]["stock_result_count"] == 0
    assert results["benchmark-failure"]["history_count"] == 0


def test_cli_runs_frozen_600_member_benchmark(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "--env",
            "dev",
            "--home",
            str(tmp_path),
            "scenario",
            "run",
            "rs-benchmark-v1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    expected = {
        "id": "rs-benchmark-v1",
        "terminal": "succeeded",
        "security_count": 0,
        "excluded_count": 0,
        "unavailable_count": 0,
        "watchlist_member_count": 600,
        "run_status": "READY",
        "stock_result_count": 1800,
        "history_count": 0,
        "exported": [],
        "classification_result_count": 60,
        "session_count": 252,
        "canonical_bytes": 792434,
        "canonical_sha256": ("6ad2505299e01cc3b78d605982059b2917ea88b30c430d171d3a05fca05386a9"),
    }
    assert {
        key: payload["result"][key]
        for key in expected
    } == expected
    assert payload["result"]["scenario_assertions_passed"] is True


def test_live_smoke_refuses_missing_production_credentials(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = main(
        [
            "--env",
            "production",
            "--home",
            str(tmp_path),
            "live-smoke",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 78
    assert payload["error"]["code"] == "LIVE_CREDENTIALS_NOT_CONFIGURED"


def test_live_smoke_runs_non_mutating_provider_and_ai_checks(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    class FakeApplication:
        def settings(self):
            return SimpleNamespace(
                provider_mode="longbridge",
                provider_configured=True,
                ai_configured=True,
            )

        def test_provider_connection(self) -> ServiceTestResult:
            return ServiceTestResult(
                "provider",
                True,
                "PROVIDER_OK",
                ("longbridge",),
            )

        def test_market_data_connection(
            self,
            symbol: str,
            benchmark: str,
        ) -> ServiceTestResult:
            return ServiceTestResult(
                "provider",
                True,
                "MARKET_DATA_OK",
                (symbol, "2026-07-24", "30", benchmark, "30"),
            )

        def test_profile_ai_classification(
            self,
            symbol: str,
        ) -> ServiceTestResult:
            assert symbol == "IREN.US"
            return ServiceTestResult(
                "ai",
                True,
                "AI_OK",
                ("AI Data Center", "Bitcoin Mining"),
            )

        def test_extreme_deviation_ai_connection(self) -> ServiceTestResult:
            return ServiceTestResult(
                "ai",
                True,
                "EXTREME_DEVIATION_AI_OK",
                ("deepseek-chat", "six-section-report"),
            )

        def test_turning_point_market_data_connection(
            self,
            symbol: str,
        ) -> ServiceTestResult:
            return ServiceTestResult(
                "provider",
                True,
                "TURNING_POINT_MARKET_DATA_OK",
                (symbol, "2026-07-24", "120", "30m"),
            )

        def test_extreme_deviation_market_data_connection(
            self,
            symbol: str,
        ) -> ServiceTestResult:
            return ServiceTestResult(
                "provider",
                True,
                "EXTREME_DEVIATION_MARKET_DATA_OK",
                (symbol, "2026-07-24", "30m:650", "1w:410"),
            )

        def list_history(self) -> tuple[object, ...]:
            return ()

    monkeypatch.setattr(
        "stock_toolbox.cli.build_application",
        lambda *args, **kwargs: FakeApplication(),
    )

    exit_code = main(
        [
            "--env",
            "production",
            "--home",
            str(tmp_path),
            "live-smoke",
            "--symbol",
            "IREN.US",
            "--benchmark",
            "SPY.US",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["result"]["status"] == "PASS"
    assert [item["name"] for item in payload["result"]["checks"]] == [
        "provider_profile",
        "market_calendar_and_bars",
        "turning_point_snapshot_and_candles",
        "extreme_deviation_supported_period_candles",
        "ai_classification",
        "extreme_deviation_ai_report",
    ]
    assert payload["result"]["history_count_before"] == 0
    assert payload["result"]["history_count_after"] == 0
    assert "secret" not in json.dumps(payload).casefold()


def test_live_smoke_is_production_only(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "--env",
            "dev",
            "--home",
            str(tmp_path),
            "live-smoke",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 64
    assert payload["error"]["code"] == "LIVE_SMOKE_PRODUCTION_ONLY"
