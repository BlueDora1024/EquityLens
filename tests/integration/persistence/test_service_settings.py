from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stock_toolbox.core.settings.models import ServiceSettingsInput
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import PersistenceValidationError
from stock_toolbox.infrastructure.persistence.global_ai_config import (
    GlobalAIConfigStore,
)
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.service_settings import ServiceSettingsStore

NOW = datetime(2026, 7, 26, 12, tzinfo=UTC)


def uid(number: int) -> str:
    return f"70000000-0000-4000-8000-{number:012d}"


def stores(
    tmp_path: Path,
    *,
    authorized_client_id: str = "oauth-client-1",
    default_provider_mode: str = "virtual",
) -> tuple[ServiceSettingsStore, Path, GlobalAIConfigStore]:
    business_database = tmp_path / "RSRadar.sqlite3"
    MigrationRunner(
        business_database,
        app_version="0.1.0",
        now=lambda: NOW,
    ).bootstrap()
    identifiers = iter(uid(number) for number in range(1, 100))
    global_ai = GlobalAIConfigStore(
        tmp_path / "RSRadar.config.sqlite3",
        clock=lambda: NOW,
        new_id=lambda: next(identifiers),
    )
    settings = ServiceSettingsStore(
        SQLiteConnectionFactory(business_database),
        global_ai,
        clock=lambda: NOW,
        new_id=lambda: next(identifiers),
        oauth_token_present=lambda client_id: client_id == authorized_client_id,
        default_provider_mode=default_provider_mode,
    )
    return settings, business_database, global_ai


def test_first_run_state_defaults_to_longbridge_and_completes_explicitly(
    tmp_path: Path,
) -> None:
    settings_store, _database, _global_ai = stores(
        tmp_path,
        default_provider_mode="longbridge",
    )

    initial = settings_store.load()
    settings_store.save(
        ServiceSettingsInput(
            "longbridge",
            30,
            1,
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            longbridge_client_id="oauth-client-1",
        )
    )
    completed = settings_store.complete_first_run()

    assert initial.provider_mode == "longbridge"
    assert not initial.first_run_complete
    assert completed.first_run_complete


def test_service_settings_split_provider_and_global_ai_configuration(
    tmp_path: Path,
) -> None:
    settings_store, business_database, global_ai = stores(tmp_path)
    api_key = bytearray(b"sk-test-global-ai")

    first = settings_store.save(
        ServiceSettingsInput(
            provider_mode="longbridge",
            timeout_seconds=30,
            max_retries=1,
            ai_base_url="https://api.deepseek.com",
            ai_model="deepseek-chat",
            developer_mode_enabled=True,
            longbridge_client_id="oauth-client-1",
        ),
        ai_api_key=api_key,
    )

    assert api_key == bytearray(len(api_key))
    assert first.provider_configured
    assert first.ai_configured
    assert first.ai_model == "deepseek-chat"
    assert first.developer_mode_enabled
    global_config = global_ai.load()
    assert global_config is not None
    assert global_ai.read_secret(global_config.revision) == bytearray(
        b"sk-test-global-ai"
    )

    with sqlite3.connect(business_database) as connection:
        business_dump = "\n".join(connection.iterdump())
    assert "sk-test-global-ai" not in business_dump
    assert "api.deepseek.com" not in business_dump
    assert "deepseek-chat" not in business_dump


def test_metadata_update_keeps_global_key_and_delete_removes_entire_ai_config(
    tmp_path: Path,
) -> None:
    settings_store, _business_database, global_ai = stores(tmp_path)
    original = ServiceSettingsInput(
        "longbridge",
        30,
        1,
        "https://api.deepseek.com",
        "deepseek-chat",
        longbridge_client_id="oauth-client-1",
    )
    settings_store.save(
        original,
        ai_api_key=bytearray(b"sk-test-keep"),
    )

    updated = settings_store.save(
        ServiceSettingsInput(
            "longbridge",
            45,
            2,
            "https://api.deepseek.com/v1",
            "deepseek-reasoner",
            longbridge_client_id="oauth-client-1",
        )
    )

    assert updated.ai_configured
    assert updated.timeout_seconds == 45
    assert updated.max_retries == 2
    config = global_ai.load()
    assert config is not None
    assert global_ai.read_secret(config.revision) == bytearray(b"sk-test-keep")

    deleted = settings_store.delete_credentials("ai")
    assert deleted.provider_configured
    assert not deleted.ai_configured
    assert global_ai.load() is None
    assert deleted.ai_base_url == "https://api.deepseek.com"
    assert deleted.ai_model == "deepseek-v4-flash"


def test_provider_requires_client_id_and_oauth_token(tmp_path: Path) -> None:
    settings_store, _business_database, _global_ai = stores(
        tmp_path,
        authorized_client_id="authorized-client",
    )

    missing = settings_store.save(
        ServiceSettingsInput(
            "longbridge",
            30,
            1,
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            longbridge_client_id="not-authorized",
        )
    )
    authorized = settings_store.save(
        ServiceSettingsInput(
            "longbridge",
            30,
            1,
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            longbridge_client_id="authorized-client",
        )
    )

    assert not missing.provider_configured
    assert authorized.provider_configured


def test_futu_candidate_does_not_change_active_longbridge(
    tmp_path: Path,
) -> None:
    settings_store, _database, _global_ai = stores(
        tmp_path,
        authorized_client_id="oauth-client-1",
        default_provider_mode="longbridge",
    )
    settings_store.save(
        ServiceSettingsInput(
            "longbridge",
            30,
            1,
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            longbridge_client_id="oauth-client-1",
        )
    )

    candidate = settings_store.save_provider_candidate(
        "futu",
        configured=True,
    )

    assert candidate.provider_mode == "longbridge"
    assert candidate.provider_configured
    assert candidate.futu_configured
    assert candidate.futu_opend_host == "127.0.0.1"
    assert candidate.futu_opend_port == 11111


def test_provider_activation_is_atomic_and_requires_quality(
    tmp_path: Path,
) -> None:
    settings_store, _database, _global_ai = stores(
        tmp_path,
        default_provider_mode="longbridge",
    )

    with pytest.raises(PersistenceValidationError):
        settings_store.activate_provider("futu")
    assert settings_store.load().provider_mode == "longbridge"

    settings_store.save_provider_candidate("futu", configured=True)
    activated = settings_store.activate_provider("futu")

    assert activated.provider_mode == "futu"
    assert activated.provider_configured
    assert activated.futu_configured


def test_appearance_mode_defaults_to_system_and_persists_in_local_settings(
    tmp_path: Path,
) -> None:
    settings_store, business_database, _global_ai = stores(tmp_path)

    assert settings_store.load_appearance_mode() == "system"

    settings_store.save_appearance_mode("dark")

    assert settings_store.load_appearance_mode() == "dark"
    with sqlite3.connect(business_database) as connection:
        business_dump = "\n".join(connection.iterdump())
    assert '"appearance_mode":"dark"' in business_dump


def test_appearance_mode_rejects_unknown_values(tmp_path: Path) -> None:
    settings_store, _database, _global_ai = stores(tmp_path)

    with pytest.raises(PersistenceValidationError):
        settings_store.save_appearance_mode("sepia")


def test_saving_service_configuration_preserves_appearance_mode(
    tmp_path: Path,
) -> None:
    settings_store, _database, _global_ai = stores(tmp_path)
    settings_store.save_appearance_mode("dark")

    settings_store.save(
        ServiceSettingsInput(
            "virtual",
            45,
            2,
            "https://api.deepseek.com",
            "deepseek-chat",
        )
    )

    assert settings_store.load_appearance_mode() == "dark"


def test_product_tour_defaults_to_visible_and_dismissal_persists(
    tmp_path: Path,
) -> None:
    settings_store, business_database, _global_ai = stores(tmp_path)

    assert settings_store.load().product_tour_dismissed is False

    dismissed = settings_store.dismiss_product_tour()

    assert dismissed.product_tour_dismissed is True
    assert settings_store.load().product_tour_dismissed is True
    with sqlite3.connect(business_database) as connection:
        business_dump = "\n".join(connection.iterdump())
    assert '"product_tour_dismissed":true' in business_dump


def test_saving_service_configuration_preserves_product_tour_dismissal(
    tmp_path: Path,
) -> None:
    settings_store, _database, _global_ai = stores(tmp_path)
    settings_store.dismiss_product_tour()

    settings_store.save(
        ServiceSettingsInput(
            "virtual",
            45,
            2,
            "https://api.deepseek.com",
            "deepseek-chat",
        )
    )

    assert settings_store.load().product_tour_dismissed is True


def test_network_settings_default_and_persist_without_resetting_other_fields(
    tmp_path: Path,
) -> None:
    settings_store, _database, _global_ai = stores(tmp_path)

    initial = settings_store.load()
    saved = settings_store.save(
        ServiceSettingsInput(
            "virtual",
            30,
            1,
            "https://api.deepseek.com",
            "deepseek-chat",
            display_timezone="America/New_York",
            proxy_mode="custom",
            proxy_url="http://name:secret@127.0.0.1:7890",
        )
    )
    preserved = settings_store.save(
        ServiceSettingsInput(
            "virtual",
            45,
            2,
            "https://api.deepseek.com",
            "deepseek-chat",
        )
    )

    assert initial.display_timezone == "Asia/Shanghai"
    assert initial.proxy_mode == "off"
    assert initial.proxy_url == ""
    assert saved.display_timezone == "America/New_York"
    assert saved.proxy_mode == "custom"
    assert saved.proxy_url == "http://name:secret@127.0.0.1:7890"
    assert preserved.display_timezone == "America/New_York"
    assert preserved.proxy_url == saved.proxy_url


@pytest.mark.parametrize(
    ("timezone", "mode", "url"),
    (
        ("Mars/Olympus", "off", ""),
        ("Asia/Shanghai", "custom", ""),
        ("Asia/Shanghai", "custom", "ftp://proxy.example"),
        ("Asia/Shanghai", "unknown", ""),
    ),
)
def test_network_settings_reject_invalid_values(
    tmp_path: Path,
    timezone: str,
    mode: str,
    url: str,
) -> None:
    settings_store, _database, _global_ai = stores(tmp_path)

    with pytest.raises(PersistenceValidationError):
        settings_store.save(
            ServiceSettingsInput(
                "virtual",
                30,
                1,
                "https://api.deepseek.com",
                "deepseek-chat",
                display_timezone=timezone,
                proxy_mode=mode,
                proxy_url=url,
            )
        )
