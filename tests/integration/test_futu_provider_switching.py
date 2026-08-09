from __future__ import annotations

from pathlib import Path

from stock_toolbox import composition
from stock_toolbox.composition import UnavailableProvider, build_application
from stock_toolbox.core.market_data.provider_health import HistoryQuotaSnapshot, ProviderIdentity
from stock_toolbox.core.settings.models import ServiceSettingsInput
from stock_toolbox.infrastructure.providers.futu_opend import (
    FutuOpenDStatus,
)
from stock_toolbox.infrastructure.virtual.provider import VirtualProvider
from stock_toolbox.runtime.environment import RuntimeEnvironment


class OpenD:
    def __init__(self, status: FutuOpenDStatus) -> None:
        self.status = status
        self.opened = 0

    def probe(self) -> FutuOpenDStatus:
        return self.status

    def open(self) -> bool:
        self.opened += 1
        return self.status.installed


class FutuCandidate(VirtualProvider):
    provider_id = "futu"
    provider_display_name = "富途"
    quant_script_versions = frozenset()

    def get_history_quota(self, *, operation_control=None):
        del operation_control
        return HistoryQuotaSnapshot(1, 99, frozenset({"AAPL.US"}))


class LeakyFutuCandidate(FutuCandidate):
    def latest_completed_trading_day(self, *, operation_control=None):
        del operation_control
        raise RuntimeError("Authorization: Bearer should-never-leave-boundary")


def active_longbridge_application(tmp_path: Path, opend: OpenD):
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="futu-switch",
        futu_opend_override=opend,
    )
    client_id = "longbridge-active"
    token = application._longbridge_oauth.token_path(client_id)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("token", encoding="utf-8")
    current = application.settings()
    application._settings_store.save(
        ServiceSettingsInput(
            "longbridge",
            current.timeout_seconds,
            current.max_retries,
            current.ai_base_url,
            current.ai_model,
            current.developer_mode_enabled,
            client_id,
        )
    )
    application._provider = UnavailableProvider("longbridge", "Longbridge")
    return application


def test_failed_futu_quality_preserves_active_longbridge(
    tmp_path: Path,
) -> None:
    opend = OpenD(FutuOpenDStatus(True, False, "futu_opend_not_running"))
    application = active_longbridge_application(tmp_path, opend)

    result = application.quality_futu()

    assert result.ok is False
    assert result.code == "futu_opend_not_running"
    assert application.settings().provider_mode == "longbridge"
    assert application.settings().futu_configured is False
    assert application.provider_identity() == ProviderIdentity(
        "longbridge",
        "Longbridge",
        True,
    )


def test_successful_quality_then_atomic_activation_rebuilds_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    opend = OpenD(FutuOpenDStatus(True, True, "futu_opend_port_ready"))
    application = active_longbridge_application(tmp_path, opend)
    monkeypatch.setattr(
        composition,
        "_futu_provider",
        lambda _settings: FutuCandidate(),
    )

    quality = application.quality_futu()

    assert quality.ok is True
    assert quality.details == (
        "opend",
        "trading_day",
        "company_profile",
        "snapshot",
        "daily_bars",
        "history_quota",
    )
    assert application.settings().provider_mode == "longbridge"
    assert application.settings().futu_configured is True

    activated = application.activate_provider("futu")

    assert activated.provider_mode == "futu"
    assert application.provider_identity() == ProviderIdentity(
        "futu",
        "富途",
        True,
    )
    assert application._quant_market_data_for("daily-close-quant-v2") is None


def test_open_futu_opend_uses_local_gui_boundary(tmp_path: Path) -> None:
    opend = OpenD(FutuOpenDStatus(True, False, "futu_opend_not_running"))
    application = active_longbridge_application(tmp_path, opend)

    assert application.open_futu_opend() is True
    assert opend.opened == 1


def test_futu_quality_sanitizes_unknown_provider_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    opend = OpenD(FutuOpenDStatus(True, True, "futu_opend_port_ready"))
    application = active_longbridge_application(tmp_path, opend)
    monkeypatch.setattr(
        composition,
        "_futu_provider",
        lambda _settings: LeakyFutuCandidate(),
    )

    result = application.quality_futu()

    assert result.ok is False
    assert result.code == "PROVIDER_TRADING_DAY_FAILED"
    assert result.details == ("opend",)
    assert "Bearer" not in repr(result)
