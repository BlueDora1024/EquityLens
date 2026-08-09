from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QGuiApplication

from stock_toolbox import composition
from stock_toolbox.composition import StockToolboxApplication, build_application
from stock_toolbox.core.settings.models import ServiceTestResult
from stock_toolbox.desktop_qml import settings_bridge
from stock_toolbox.desktop_qml.settings_bridge import (
    SettingsBridge,
    choose_default_model,
)
from stock_toolbox.infrastructure.providers.catalog import (
    provider_development_prompt,
)
from stock_toolbox.runtime.environment import RuntimeEnvironment


def test_settings_bridge_loads_local_service_state(scenario_application) -> None:
    bridge = SettingsBridge(scenario_application)

    assert bridge.provider_configured is True
    assert bridge.providers == [
        {
            "id": "longbridge",
            "name": "长桥",
            "summary": "官方 OpenAPI · 美股基础资料、交易日历与多周期行情",
            "builtin": True,
            "configured": True,
            "active": True,
            "selected": True,
        },
        {
            "id": "futu",
            "name": "富途",
            "summary": "官方 OpenAPI · 通过本机 Futu OpenD 提供美股资料与多周期行情",
            "builtin": True,
            "configured": False,
            "active": False,
            "selected": False,
        },
    ]
    assert bridge.selected_provider_id == "longbridge"
    assert [item["id"] for item in bridge.provider_checks] == [
        "oauth",
        "trading_day",
        "company_profile",
        "daily_bars",
    ]
    assert all(item["state"] == "passed" for item in bridge.provider_checks)
    assert bridge.ai_base_url == "https://api.deepseek.com"
    assert bridge.ai_model == "deepseek-v4-flash"
    assert bridge.api_key_hint == "尚未配置"
    assert bridge.ai_configured is False
    assert bridge.display_timezone == "Asia/Shanghai"
    assert bridge.proxy_mode == "off"
    assert bridge.proxy_url_hint == ""


def test_settings_bridge_exposes_official_deepseek_api_key_page(
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    assert bridge.deepseek_api_keys_url == "https://platform.deepseek.com/api_keys"


def test_settings_bridge_saves_display_timezone_and_proxy(
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    assert bridge.save_network(
        "America/New_York",
        "custom",
        "http://name:secret@127.0.0.1:7890",
    )

    saved = scenario_application.settings()
    assert saved.display_timezone == "America/New_York"
    assert saved.proxy_mode == "custom"
    assert saved.proxy_url == "http://name:secret@127.0.0.1:7890"
    assert bridge.proxy_url_hint == "http://name:••••@127.0.0.1:7890"


def test_settings_bridge_checks_proxy_off_main_thread(
    qtbot,
    monkeypatch,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)
    monkeypatch.setattr(
        StockToolboxApplication,
        "test_network_connection",
        lambda _application: ServiceTestResult(
            "network",
            True,
            "NETWORK_QUALITY_OK",
        ),
    )

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.quality_proxy() is True

    assert bridge.busy is False
    assert bridge.status == "网络质检通过；行情仍以供应商质检为准。"


def test_settings_bridge_checks_yahoo_fallback_off_main_thread(
    qtbot,
    monkeypatch,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)
    monkeypatch.setattr(
        StockToolboxApplication,
        "test_yahoo_connection",
        lambda _application: ServiceTestResult(
            "yahoo",
            True,
            "YAHOO_QUALITY_OK",
            ("NVDA.US", "1d"),
        ),
    )

    assert bridge.yahoo_quality_state == "pending"
    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.quality_yahoo() is True

    assert bridge.busy is False
    assert bridge.yahoo_quality_state == "passed"
    assert bridge.yahoo_quality_detail == "NVDA 日线可用"
    assert bridge.yahoo_quality_checked_at
    assert bridge.status == "Yahoo 备用行情质检通过 · NVDA 日线可用。"


def test_settings_bridge_reports_yahoo_fallback_failure_without_raw_exception(
    qtbot,
    monkeypatch,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)
    monkeypatch.setattr(
        StockToolboxApplication,
        "test_yahoo_connection",
        lambda _application: ServiceTestResult(
            "yahoo",
            False,
            "network_error",
        ),
    )

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.quality_yahoo() is True

    assert bridge.yahoo_quality_state == "failed"
    assert bridge.yahoo_quality_detail == "无法读取 NVDA 日线"
    assert bridge.status == "Yahoo 备用行情不可用，请检查网络或代理设置。"


def test_settings_bridge_selects_provider_development_guide(
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    bridge.select_provider("add")

    assert bridge.selected_provider_id == "add"
    assert "DailyBarsProviderPort" in bridge.provider_prompt
    assert "600 只股票" in bridge.provider_prompt


def test_settings_bridge_copies_the_canonical_provider_prompt(
    qtbot,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)
    application = QGuiApplication.instance()

    assert application is not None
    assert bridge.copy_provider_prompt() is True
    assert application.clipboard().text() == bridge.provider_prompt
    assert bridge.provider_prompt == provider_development_prompt()


def test_selecting_futu_requests_opend_guidance_and_changes_checks(
    qtbot,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    with qtbot.waitSignal(bridge.futu_guidance_requested, timeout=1_000):
        bridge.select_provider("futu")

    assert bridge.selected_provider_id == "futu"
    assert [item["id"] for item in bridge.provider_checks] == [
        "opend",
        "trading_day",
        "company_profile",
        "snapshot",
        "daily_bars",
        "history_quota",
    ]
    assert bridge.futu_reference_url.startswith("https://openapi.futunn.com/")


def test_futu_candidate_quality_then_activation_keeps_one_active_provider(
    qtbot,
    monkeypatch,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)
    bridge.select_provider("futu")

    def quality(_application) -> ServiceTestResult:
        scenario_application._settings_store.save_provider_candidate(
            "futu",
            configured=True,
        )
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

    monkeypatch.setattr(StockToolboxApplication, "quality_futu", quality)
    monkeypatch.setattr(
        composition,
        "_futu_provider",
        lambda _settings: scenario_application._provider,
    )

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.quality_provider() is True

    assert bridge.selected_provider_quality_passed is True
    assert [item["id"] for item in bridge.providers if item["active"]] == ["longbridge"]

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.activate_selected_provider() is True

    assert bridge.active_provider_id == "futu"
    assert [item["id"] for item in bridge.providers if item["active"]] == ["futu"]


def test_futu_quality_failure_is_visible_and_names_the_failed_check(
    qtbot,
    monkeypatch,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)
    bridge.select_provider("futu")
    monkeypatch.setattr(
        StockToolboxApplication,
        "quality_futu",
        lambda _application: ServiceTestResult(
            "provider",
            False,
            "PROVIDER_DAILY_BARS_FAILED",
            ("opend", "trading_day", "company_profile", "snapshot"),
        ),
    )

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.quality_provider() is True

    states = {item["id"]: item["state"] for item in bridge.provider_checks}
    assert states["daily_bars"] == "failed"
    assert bridge.status == "富途质检未通过：AAPL 日 K 线读取失败。"


def test_futu_quality_uses_isolated_worker_when_bundled(
    qtbot,
    monkeypatch,
    scenario_application,
) -> None:
    scenario_application._settings_store.save_provider_candidate(
        "futu",
        configured=True,
    )
    scenario_application._settings_store.activate_provider("futu")
    bridge = SettingsBridge(scenario_application)
    calls: list[tuple[Path, list[str]]] = []

    monkeypatch.setattr(
        bridge,
        "_futu_quality_worker_program",
        lambda: Path("/Applications/EquityLens.app/Contents/MacOS/equitylens"),
    )

    def run_worker(program: Path, arguments: list[str]) -> ServiceTestResult:
        calls.append((program, arguments))
        return ServiceTestResult(
            "provider",
            True,
            "PROVIDER_QUALITY_OK",
            tuple(check_id for check_id, _label in settings_bridge._FUTU_CHECKS),
        )

    monkeypatch.setattr(settings_bridge, "_run_futu_quality_process", run_worker)
    monkeypatch.setattr(
        StockToolboxApplication,
        "quality_futu",
        lambda _application: (_ for _ in ()).throw(AssertionError("must be isolated")),
    )

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.quality_provider() is True

    assert len(calls) == 1
    assert calls[0][1][-5:] == [
        "services",
        "quality",
        "--provider",
        "futu",
        "--json",
    ]
    assert all(item["state"] == "passed" for item in bridge.provider_checks)
    assert bridge.status == "富途质检通过 · 当前已启用"


def test_first_run_cannot_open_ai_before_provider_quality_passes(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.PRODUCTION,
        home=tmp_path,
    )
    bridge = SettingsBridge(application)

    bridge.select_page("ai")

    assert bridge.page == "provider"
    assert bridge.status == "请先完成行情供应商授权与质检。"


def test_default_model_prefers_current_then_fast_general_models() -> None:
    assert choose_default_model(("reasoner", "fast-flash", "chat-pro"), "chat-pro") == ("chat-pro")
    assert choose_default_model(("reasoner", "fast-flash", "chat-pro"), "missing") == ("fast-flash")
    assert choose_default_model(("z-model", "a-model"), "") == "a-model"


def test_settings_bridge_saves_ai_fields_without_exposing_secret(
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    assert bridge.save_ai(
        "https://example.invalid/v1",
        "demo-model",
        "test-secret",
    )

    saved = scenario_application.settings()
    assert saved.ai_base_url == "https://example.invalid/v1"
    assert saved.ai_model == "demo-model"
    assert not hasattr(bridge, "api_key")


def test_reset_requires_exact_second_confirmation(scenario_application) -> None:
    bridge = SettingsBridge(scenario_application)

    bridge.request_reset()

    assert bridge.reset_pending is True
    assert bridge.confirm_reset("确认") is False
    assert bridge.reset_pending is True


def test_reset_immediately_clears_transient_settings_state(
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)
    bridge.select_page("ai")
    bridge._authorization_finished(
        ServiceTestResult("provider", True, "OAUTH_AUTHORIZED", ("candidate",))
    )
    bridge._models = ("demo-flash",)
    bridge._selected_ai_model = "demo-flash"
    bridge._ai_quality_verified = True

    bridge.request_reset()

    assert bridge.confirm_reset("恢复默认") is True
    assert bridge.page == "provider"
    assert bridge.provider_authorized_pending is False
    assert bridge.models == []
    assert bridge.ai_configured is False
    assert bridge.provider_configured is True  # scenario uses the virtual provider
    assert all(item["state"] == "passed" for item in bridge.provider_checks)
    assert bridge.reset_pending is False


def test_settings_bridge_runs_provider_quality_off_main_thread(
    qtbot,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.quality_provider() is True

    assert bridge.busy is False
    assert "质检通过" in bridge.status
    assert all(item["state"] == "passed" for item in bridge.provider_checks)


def test_settings_bridge_maps_pending_authorization_to_quality_steps(
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    bridge._authorization_finished(
        ServiceTestResult("provider", True, "OAUTH_AUTHORIZED", ("candidate",))
    )

    assert bridge.provider_authorized_pending is True
    assert [item["state"] for item in bridge.provider_checks] == [
        "passed",
        "pending",
        "pending",
        "pending",
    ]


def test_settings_bridge_auto_configures_ai_in_one_background_flow(
    qtbot,
    monkeypatch,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)
    calls: list[tuple[object, ...]] = []

    def discover(
        _application: StockToolboxApplication,
        base_url: str,
        api_key: bytearray,
    ) -> tuple[str, ...]:
        calls.append(("discover", base_url, api_key.decode()))
        api_key[:] = b"\x00" * len(api_key)
        return ("reasoner", "demo-flash", "chat-pro")

    def configure(
        _application: StockToolboxApplication,
        base_url: str,
        model: str,
        api_key: bytearray,
    ) -> ServiceTestResult:
        calls.append(("configure", base_url, model, api_key.decode()))
        api_key[:] = b"\x00" * len(api_key)
        return ServiceTestResult("ai", True, "AI_QUALITY_OK", ("数据中心",))

    monkeypatch.setattr(StockToolboxApplication, "discover_ai_models", discover)
    monkeypatch.setattr(StockToolboxApplication, "configure_ai", configure)

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.auto_configure_ai("https://ai.example/v1", "secret") is True

    assert calls == [
        ("discover", "https://ai.example/v1", "secret"),
        ("configure", "https://ai.example/v1", "demo-flash", "secret"),
    ]
    assert bridge.models == ["reasoner", "demo-flash", "chat-pro"]
    assert bridge.ai_model == "demo-flash"
    assert bridge.ai_configured is True
    assert "质检通过" in bridge.status


def test_configured_ai_refreshes_models_and_can_select_another_model(
    qtbot,
    monkeypatch,
    scenario_application,
) -> None:
    original = SettingsBridge(scenario_application)
    assert original.save_ai("https://ai.example/v1", "model-a", "secret")
    bridge = SettingsBridge(scenario_application)
    monkeypatch.setattr(
        StockToolboxApplication,
        "discover_saved_ai_models",
        lambda _application: ("model-a", "model-b"),
    )
    monkeypatch.setattr(
        StockToolboxApplication,
        "preview_ai_classification",
        lambda _application: ServiceTestResult(
            "ai", True, "AI_QUALITY_OK", ("数据中心",)
        ),
    )

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        bridge.select_page("ai")

    assert bridge.models == ["model-a", "model-b"]
    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.select_ai_model("model-b") is True

    assert bridge.ai_model == "model-b"
    assert scenario_application.settings().ai_model == "model-b"


def test_settings_bridge_recovers_when_ai_discovery_raises(
    qtbot,
    monkeypatch,
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    def fail(
        _application: StockToolboxApplication,
        _base_url: str,
        _api_key: bytearray,
    ) -> tuple[str, ...]:
        raise RuntimeError("secret response must not leak")

    monkeypatch.setattr(StockToolboxApplication, "discover_ai_models", fail)

    with qtbot.waitSignal(bridge.finished, timeout=5_000):
        assert bridge.auto_configure_ai("https://ai.example/v1", "secret") is True

    assert bridge.busy is False
    assert bridge.ai_configured is False
    assert bridge.status == "AI 自动检测失败，请检查 URL、Key 或服务状态。"
    assert "secret response" not in bridge.status


def test_settings_bridge_can_complete_first_run_after_provider_ready(
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    assert bridge.complete_first_run() is True
    assert scenario_application.settings().first_run_complete is True


def test_settings_bridge_can_enable_isolated_developer_tools(
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    assert bridge.developer_mode_enabled is False
    assert bridge.set_developer_mode(True) is True
    assert bridge.developer_mode_enabled is True


def test_settings_bridge_exposes_appearance_as_a_regular_settings_page(
    scenario_application,
) -> None:
    bridge = SettingsBridge(scenario_application)

    bridge.select_page("appearance")

    assert bridge.page == "appearance"
