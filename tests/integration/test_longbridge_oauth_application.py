from __future__ import annotations

from pathlib import Path

from stock_toolbox import composition
from stock_toolbox.composition import build_application
from stock_toolbox.core.settings.models import ServiceSettingsInput
from stock_toolbox.infrastructure.virtual.provider import VirtualProvider
from stock_toolbox.runtime.environment import RuntimeEnvironment


def configured_application(tmp_path: Path, run_id: str):
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id=run_id,
    )
    old_client_id = "oauth-client-old"
    old_token = application._longbridge_oauth.token_path(old_client_id)
    old_token.parent.mkdir(parents=True, exist_ok=True)
    old_token.write_text("old-token", encoding="utf-8")
    current = application.settings()
    application._settings_store.save(
        ServiceSettingsInput(
            "longbridge",
            current.timeout_seconds,
            current.max_retries,
            current.ai_base_url,
            current.ai_model,
            current.developer_mode_enabled,
            old_client_id,
        )
    )
    return application, old_client_id, old_token


def test_candidate_authorization_switches_only_after_four_quality_checks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application, old_client_id, old_token = configured_application(
        tmp_path,
        "oauth-candidate-success",
    )
    candidate = "oauth-client-candidate"
    candidate_token = application._longbridge_oauth.token_path(candidate)
    monkeypatch.setattr(application._longbridge_oauth, "register", lambda: candidate)

    def authorize(value: str, on_open_url) -> object:
        assert value == candidate
        on_open_url("https://open.longbridge.com/oauth2/authorize")
        candidate_token.write_text("candidate-token", encoding="utf-8")
        return object()

    monkeypatch.setattr(application._longbridge_oauth, "authorize", authorize)
    monkeypatch.setattr(
        composition,
        "_longbridge_provider",
        lambda _settings, _oauth: VirtualProvider(),
    )
    opened: list[str] = []

    authorized = application.authorize_longbridge(on_open_url=opened.append)

    assert authorized.ok
    assert authorized.details == (candidate,)
    assert application.settings().longbridge_client_id == old_client_id
    assert old_token.exists()

    quality = application.quality_longbridge(candidate)

    assert quality.ok
    assert quality.details == ("oauth", "trading_day", "company_profile", "daily_bars")
    assert application.settings().longbridge_client_id == candidate
    assert application.settings().provider_configured
    assert not application.settings().first_run_complete
    assert candidate_token.exists()
    assert not old_token.exists()

    application.complete_first_run()

    assert application.settings().first_run_complete


def test_failed_candidate_quality_preserves_old_authorization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application, old_client_id, old_token = configured_application(
        tmp_path,
        "oauth-candidate-failure",
    )
    candidate = "oauth-client-failing"
    candidate_token = application._longbridge_oauth.token_path(candidate)
    candidate_token.write_text("candidate-token", encoding="utf-8")
    monkeypatch.setattr(
        composition,
        "_longbridge_provider",
        lambda _settings, _oauth: VirtualProvider(
            profile_errors={"AAPL.US": "profile_unavailable"}
        ),
    )

    quality = application.quality_longbridge(candidate)

    assert not quality.ok
    assert quality.code == "PROVIDER_PROFILE_FAILED"
    assert quality.details == ("oauth", "trading_day")
    assert application.settings().longbridge_client_id == old_client_id
    assert old_token.exists()
    assert not candidate_token.exists()
