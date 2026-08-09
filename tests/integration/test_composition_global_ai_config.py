from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from stock_toolbox import composition
from stock_toolbox.analyses.rs_strength.application.models import RunRequest
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
)
from stock_toolbox.composition import build_application
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.securities.models import (
    AIClassification,
    AICompanyAnalysis,
)
from stock_toolbox.core.settings.models import ServiceSettingsInput
from stock_toolbox.desktop_qml.report_operation import (
    execute_report_operation,
    reserve_report_operation,
)
from stock_toolbox.infrastructure.ai.openai_compatible import AIAdapterError
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_production_and_development_share_global_ai_configuration(
    tmp_path: Path,
) -> None:
    production = build_application(
        RuntimeEnvironment.PRODUCTION,
        home=tmp_path,
    )
    production.save_settings(
        ServiceSettingsInput(
            "virtual",
            30,
            1,
            "https://api.deepseek.com",
            "deepseek-chat",
        ),
        ai_api_key=bytearray(b"sk-test-shared-real-modes"),
    )

    development = build_application(
        RuntimeEnvironment.DEVELOPMENT,
        home=tmp_path,
    )
    integration = build_application(
        RuntimeEnvironment.INTEGRATION,
        home=tmp_path,
    )

    assert development.settings().ai_configured
    assert development.settings().ai_model == "deepseek-chat"
    assert not integration.settings().ai_configured


def test_ai_quality_saves_only_after_structured_classification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="ai-quality",
    )

    class PassingAI:
        def __init__(self, config, secret_store) -> None:
            assert secret_store.read(config.config_revision) == bytearray(b"quality-secret")

        def analyze_company(self, profile, existing, *, operation_control):
            return AICompanyAnalysis(
                True,
                "COMMON_STOCK",
                (AIClassification("AI Infrastructure", None, Decimal("0.9")),),
            )

    monkeypatch.setattr(composition, "OpenAICompatibleAI", PassingAI)
    key = bytearray(b"quality-secret")

    result = application.configure_ai(
        "https://api.example.com/v1",
        "model-a",
        key,
    )

    assert result.ok
    assert result.details == ("AI Infrastructure",)
    assert key == bytearray(len(key))
    assert application.settings().ai_configured
    assert application.settings().ai_model == "model-a"
    assert application.settings().first_run_complete


def test_ai_quality_failure_does_not_save_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="ai-quality-failure",
    )

    class FailingAI:
        def __init__(self, config, secret_store) -> None:
            pass

        def analyze_company(self, profile, existing, *, operation_control):
            raise RuntimeError("remote secret detail")

    monkeypatch.setattr(composition, "OpenAICompatibleAI", FailingAI)
    key = bytearray(b"failed-secret")

    result = application.configure_ai(
        "https://api.example.com/v1",
        "model-a",
        key,
    )

    assert not result.ok
    assert result.code == "AI_QUALITY_FAILED"
    assert key == bytearray(len(key))
    assert not application.settings().ai_configured


def _completed_rs_run(application) -> str:
    application.import_securities("IREN,NVDA,AMD")
    watchlist = application.master_data.create_watchlist("AI 报告测试")
    application.master_data.add_watchlist_members(
        watchlist.id,
        tuple(
            (security.id, security.bindings[0].id)
            for security in application.master_data.list_securities()
        ),
    )
    result = application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M", "6M", "1Y"),
            None,
        )
    )
    assert result.run_id is not None
    return str(result.run_id)


def test_scenario_generates_and_saves_rs_strength_report(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="rs-ai-report",
    )
    run_id = _completed_rs_run(application)

    report = application.generate_rs_strength_report(run_id)

    assert report.prompt_version == "rs-strength-report-v3"
    assert report.model == "virtual-rs-strength-report"
    assert report.content.startswith("一、总体结论\n1. 最强方向")
    assert "五、短期强度跃迁" in report.content
    assert "六、数据说明" in report.content
    reports = application.get_history(run_id).header.snapshot_extensions["ai_reports"]
    assert reports[-1]["content"] == report.content
    assert reports[-1]["input_sha256"] == report.input_sha256


def test_production_rs_report_requires_ai_configuration(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.PRODUCTION,
        home=tmp_path,
    )
    application.save_settings(
        ServiceSettingsInput(
            "virtual",
            30,
            1,
            "https://api.deepseek.com",
            "deepseek-chat",
        ),
    )
    run_id = _completed_rs_run(application)

    with pytest.raises(RuntimeError, match="ai_configuration_invalid"):
        application.generate_rs_strength_report(run_id)

    assert application.get_history(run_id).header.snapshot_extensions.get("ai_reports") is None


def test_registered_rs_report_handles_settings_reset_without_leaking(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.PRODUCTION,
        home=tmp_path,
    )
    application.save_settings(
        ServiceSettingsInput(
            "virtual",
            30,
            1,
            "https://api.deepseek.com",
            "deepseek-chat",
        ),
    )
    run_id = _completed_rs_run(application)
    assert reserve_report_operation(application, "settings-reset-report")

    result = execute_report_operation(
        application,
        "settings-reset-report",
        lambda control: application.generate_rs_strength_report(
            run_id,
            operation_control=control,
        ),
    )

    assert isinstance(result, AIAdapterError)
    assert result.code == "ai_configuration_invalid"
    assert application.get_history(run_id).header.snapshot_extensions.get("ai_reports") is None


def test_registered_rs_report_hides_deleted_history_race(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="rs-report-history-race",
    )
    run_id = _completed_rs_run(application)
    assert reserve_report_operation(application, "history-race-report")
    application.delete_history(run_id)

    result = execute_report_operation(
        application,
        "history-race-report",
        lambda control: application.generate_rs_strength_report(
            run_id,
            operation_control=control,
        ),
    )

    assert isinstance(result, AIAdapterError)
    assert result.code == "report_failed"
    assert run_id not in str(result)


def _completed_turning_point_run(application) -> str:
    application.import_securities("IREN,NVDA,AMD")
    watchlist = application.master_data.create_watchlist("拐点 AI 报告测试")
    application.master_data.add_watchlist_members(
        watchlist.id,
        tuple(
            (security.id, security.bindings[0].id)
            for security in application.master_data.list_securities()
        ),
    )
    result = application.run_turning_point(
        TurningPointRequest(
            watchlist.id,
            (
                CandleInterval.MIN_30,
                CandleInterval.DAY,
                CandleInterval.WEEK,
            ),
            date(2026, 7, 24),
        )
    )
    assert result.run is not None
    return result.run.run_id


def test_scenario_generates_and_saves_turning_point_report(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="turning-ai-report",
    )
    run_id = _completed_turning_point_run(application)

    report = application.generate_turning_point_report(run_id)

    assert report.prompt_version == "turning-point-report-v6"
    assert report.model == "virtual-turning-point-report"
    stored = application.list_turning_point_history()[0]["payload"]
    assert stored["ai_reports"][-1]["content"] == report.content


def test_production_turning_point_report_requires_ai_configuration(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.PRODUCTION,
        home=tmp_path,
    )
    application.save_settings(
        ServiceSettingsInput(
            "virtual",
            30,
            1,
            "https://api.deepseek.com",
            "deepseek-chat",
        ),
    )
    run_id = _completed_turning_point_run(application)

    with pytest.raises(RuntimeError, match="ai_configuration_invalid"):
        application.generate_turning_point_report(run_id)

    stored = application.list_turning_point_history()[0]["payload"]
    assert stored.get("ai_reports") is None
