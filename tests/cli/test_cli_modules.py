from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

import pytest

from rs_radar.cli import main as legacy_main
from stock_toolbox import cli
from stock_toolbox.cli import _parser, main
from stock_toolbox.composition import build_application
from stock_toolbox.core.operations.storage_guard import StorageCheck, StorageState
from stock_toolbox.core.settings.models import ServiceTestResult
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_analysis_list_is_machine_readable(capsys) -> None:
    assert main(["analysis", "list", "--json"]) == 0

    streams = capsys.readouterr()
    payload = json.loads(streams.out)
    assert streams.err == ""
    assert payload["analyses"] == [
        {
            "id": "extreme_deviation",
            "name": "极值偏离",
            "version": "1.0.0",
        },
        {
            "id": "rs_strength",
            "name": "RS 强度",
            "version": "1.0.0",
        },
        {
            "id": "turning_point",
            "name": "拐点筛选",
            "version": "1.0.0",
        },
    ]


def test_services_status_exposes_safe_configuration_state(
    tmp_path: Path,
    capsys,
) -> None:
    assert (
        main(
            [
                "--env",
                "integration",
                "--home",
                str(tmp_path),
                "services",
                "status",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["services"] == {
        "provider": "virtual",
        "provider_configured": False,
        "ai_configured": False,
        "first_run_complete": False,
    }
    assert "client_id" not in payload


def test_services_quality_can_target_futu(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeApplication:
        def settings(self):
            return type(
                "Settings",
                (),
                {
                    "provider_mode": "longbridge",
                    "longbridge_client_id": "",
                },
            )()

        def quality_futu(self) -> ServiceTestResult:
            calls.append("futu")
            return ServiceTestResult(
                "provider",
                True,
                "PROVIDER_QUALITY_OK",
                (
                    "opend",
                    "trading_day",
                    "company_profile",
                    "snapshot",
                    "daily_bars",
                    "history_quota",
                ),
            )

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(cli, "build_application", lambda *_args, **_kwargs: FakeApplication())

    exit_code = main(
        [
            "--env",
            "production",
            "--home",
            str(tmp_path),
            "services",
            "quality",
            "--provider",
            "futu",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert calls == ["futu", "close"]
    assert payload["quality"] == {
        "name": "provider",
        "ok": True,
        "code": "PROVIDER_QUALITY_OK",
        "details": [
            "opend",
            "trading_day",
            "company_profile",
            "snapshot",
            "daily_bars",
            "history_quota",
        ],
    }


def test_security_import_worker_streams_progress_and_result_jsonl(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO("IREN, NVDA, IREN"))

    code = main(
        [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "securities",
            "import-worker",
        ]
    )

    assert code == 0
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert events[0]["type"] == "progress"
    assert events[-1]["type"] == "result"
    assert events[-1]["committed"] is True
    assert [item["symbol"] for item in events[-1]["items"]] == [
        "IREN.US",
        "NVDA.US",
    ]
    assert events[-1]["duplicates"] == ["IREN.US"]


def test_rs_history_list_uses_module_scope(
    tmp_path: Path,
    capsys,
) -> None:
    assert (
        main(
            [
                "--env",
                "integration",
                "--home",
                str(tmp_path),
                "analysis",
                "rs-strength",
                "history",
                "list",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis_type"] == "rs_strength"
    assert payload["runs"] == []


def test_turning_point_full_scenario_is_machine_readable(
    tmp_path: Path,
    capsys,
) -> None:
    assert (
        main(
            [
                "--env",
                "scenario",
                "--home",
                str(tmp_path),
                "analysis",
                "turning-point",
                "run",
                "--scenario",
                "turning-point-full",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis_type"] == "turning_point"
    assert payload["result"]["imported"] == 3
    assert payload["result"]["matched_count"] >= 1
    assert payload["result"]["intervals"] == ["30m", "60m", "1d"]
    assert payload["result"]["trade_side"] == "RIGHT_CONFIRMED"


def test_turning_point_cli_accepts_repeated_intervals() -> None:
    args = _parser().parse_args(
        [
            "analysis",
            "turning-point",
            "run",
            "--watchlist-id",
            "pool",
            "--interval",
            "30m",
            "--interval",
            "1d",
        ]
    )

    assert args.intervals == ["30m", "1d"]


def test_turning_point_cli_accepts_left_trade_side() -> None:
    args = _parser().parse_args(
        [
            "analysis",
            "turning-point",
            "run",
            "--watchlist-id",
            "pool",
            "--trade-side",
            "left",
        ]
    )

    assert args.trade_side == "left"


def test_turning_point_worker_streams_sanitized_progress_and_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "analysis",
            "turning-point",
            "run-worker",
            "--watchlist-id",
            "missing-watchlist",
            "--interval",
            "30m",
            "--end-date",
            "2026-07-29",
            "--trade-side",
            "left",
        ]
    )

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert exit_code == 69
    assert events[0]["type"] == "progress"
    assert events[-1] == {
        "schema_version": "turning-point-worker-v1",
        "type": "result",
        "status": "FAILED",
        "run_id": None,
        "error_code": "APPLICATION_INTERNAL",
    }


@pytest.mark.parametrize(
    "obsolete_option",
    ("--minimum-market-value", "--positive-250d"),
)
def test_turning_point_cli_rejects_removed_hard_filters(
    obsolete_option: str,
) -> None:
    arguments = [
        "analysis",
        "turning-point",
        "run",
        "--watchlist-id",
        "pool",
        obsolete_option,
    ]
    if obsolete_option == "--minimum-market-value":
        arguments.append("2000000000")

    with pytest.raises(SystemExit):
        _parser().parse_args(arguments)


def test_turning_point_backtest_is_machine_readable(
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "backtest.json"
    assert (
        main(
            [
                "--env",
                "integration",
                "--home",
                str(tmp_path),
                "analysis",
                "turning-point",
                "backtest",
                "--symbol",
                "IREN",
                "--interval",
                "30m",
                "--count",
                "220",
                "--output",
                str(output),
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "turning-point-backtest-v1"
    assert payload["method"]["entry"] == "next_bar_open"
    assert {item["trade_side"] for item in payload["results"]} == {
        "LEFT_CD",
        "RIGHT_CONFIRMED",
    }
    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_legacy_cli_warns_only_on_stderr_and_preserves_json_stdout(
    tmp_path: Path,
    capsys,
) -> None:
    assert (
        legacy_main(
            [
                "--env",
                "scenario",
                "--home",
                str(tmp_path),
                "scenario",
                "list",
                "--json",
            ]
        )
        == 0
    )

    streams = capsys.readouterr()
    json.loads(streams.out)
    assert "deprecated" in streams.err.lower()


@pytest.mark.parametrize(
    "analysis_args",
    [
        (
            "rs-strength",
            "run",
            "--watchlist-id",
            "missing",
            "--end-date",
            "2026-07-24",
        ),
        (
            "turning-point",
            "run",
            "--watchlist-id",
            "missing",
            "--end-date",
            "2026-07-24",
        ),
        (
            "extreme-deviation",
            "run",
            "--watchlist-id",
            "missing",
            "--end-date",
            "2026-07-24",
        ),
    ],
)
def test_all_analysis_cli_launches_stop_on_blocked_storage(
    analysis_args: tuple[str, ...],
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "stock_toolbox.core.operations.storage_guard.StorageGuard.prepare_run",
        lambda _self: StorageCheck(
            StorageState.BLOCKED,
            0,
            error_code="storage_unavailable",
        ),
    )

    code = main(
        [
            "--env",
            "integration",
            "--home",
            str(tmp_path),
            "analysis",
            *analysis_args,
            "--json",
        ]
    )

    assert code == 69
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["status"] == "FAILED"
    assert payload["result"]["run_id"] is None
    assert payload["result"]["error_code"] == "storage_unavailable"
    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
    )
    assert application.list_history() == ()
    assert application.list_turning_point_history() == ()
    assert application.list_extreme_deviation_history() == ()


def test_storage_warning_allows_cli_run_and_block_preserves_its_history(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
    )
    assert application.import_securities("IREN").success_count == 1
    security = application.master_data.list_securities()[0]
    pool = application.master_data.create_watchlist("Storage warning")
    pool = application.master_data.add_watchlist_members(
        pool.id,
        ((security.id, security.bindings[0].id),),
    )
    monkeypatch.setattr(
        "stock_toolbox.core.operations.storage_guard.StorageGuard.prepare_run",
        lambda _self: StorageCheck(StorageState.WARNING, 512 * 1024**2),
    )
    command = [
        "--env",
        "integration",
        "--home",
        str(tmp_path),
        "analysis",
        "rs-strength",
        "run",
        "--watchlist-id",
        pool.id,
        "--end-date",
        "2026-07-24",
        "--json",
    ]

    assert main(command) == 0
    successful = json.loads(capsys.readouterr().out)
    assert successful["result"]["status"] == "READY"
    before = application.list_history()
    assert len(before) == 1

    monkeypatch.setattr(
        "stock_toolbox.core.operations.storage_guard.StorageGuard.prepare_run",
        lambda _self: StorageCheck(
            StorageState.BLOCKED,
            0,
            error_code="storage_unavailable",
        ),
    )
    assert main(command) == 69
    blocked = json.loads(capsys.readouterr().out)

    assert blocked["result"]["error_code"] == "storage_unavailable"
    assert application.list_history() == before
