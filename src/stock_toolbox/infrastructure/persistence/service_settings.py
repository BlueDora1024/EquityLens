"""Provider settings plus one shared global AI configuration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from stock_toolbox.core.settings.models import (
    ServiceSettingsDTO,
    ServiceSettingsInput,
)
from stock_toolbox.core.settings.network import (
    DISPLAY_TIMEZONES,
    PROXY_MODES,
    normalize_proxy_url,
)
from stock_toolbox.infrastructure.ai.openai_compatible import normalize_chat_endpoint
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import PersistenceValidationError
from stock_toolbox.infrastructure.persistence.global_ai_config import (
    GlobalAIConfig,
    GlobalAIConfigStore,
)
from stock_toolbox.infrastructure.persistence.records import SettingRecord
from stock_toolbox.infrastructure.persistence.settings_repository import (
    SettingsRepository,
)
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork
from stock_toolbox.infrastructure.providers.longbridge_oauth import (
    InvalidLongbridgeClientIdError,
    normalize_longbridge_client_id,
)

_CONFIG_KEY = "services.config"
_DEFAULT_AI_BASE_URL = "https://api.deepseek.com"
_DEFAULT_AI_MODEL = "deepseek-v4-flash"
_APPEARANCE_MODES = frozenset({"system", "light", "dark"})
_PROVIDER_MODES = frozenset({"virtual", "longbridge", "futu"})


class ServiceSettingsStore:
    def __init__(
        self,
        factory: SQLiteConnectionFactory,
        global_ai: GlobalAIConfigStore,
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
        oauth_token_present: Callable[[str], bool] = lambda _client_id: False,
        default_provider_mode: str = "virtual",
    ) -> None:
        if default_provider_mode not in _PROVIDER_MODES:
            raise ValueError("default provider mode is invalid")
        self._factory = factory
        self._global_ai = global_ai
        self._clock = clock
        self._new_id = new_id
        self._oauth_token_present = oauth_token_present
        self._default_provider_mode = default_provider_mode

    def load(self) -> ServiceSettingsDTO:
        value = self._value()
        ai = self._global_ai.load()
        provider_mode = str(value.get("provider_mode", self._default_provider_mode))
        if provider_mode not in _PROVIDER_MODES:
            provider_mode = self._default_provider_mode
        client_id = str(value.get("longbridge_client_id", ""))
        longbridge_configured = bool(client_id) and self._oauth_token_present(client_id)
        futu_configured = bool(value.get("futu_configured", False))
        provider_configured = {
            "virtual": False,
            "longbridge": longbridge_configured,
            "futu": futu_configured,
        }[provider_mode]
        display_timezone = str(
            value.get("display_timezone", "Asia/Shanghai")
        )
        if display_timezone not in DISPLAY_TIMEZONES:
            display_timezone = "Asia/Shanghai"
        proxy_mode = str(value.get("proxy_mode", "off"))
        if proxy_mode not in PROXY_MODES:
            proxy_mode = "off"
        proxy_url = str(value.get("proxy_url", ""))
        if proxy_mode != "custom":
            proxy_url = ""
        return ServiceSettingsDTO(
            provider_mode=provider_mode,
            timeout_seconds=(
                ai.timeout_seconds
                if ai is not None
                else self._integer(value, "provider_timeout_seconds", 30)
            ),
            max_retries=(
                ai.max_retries
                if ai is not None
                else self._integer(value, "provider_max_retries", 1)
            ),
            ai_base_url=ai.base_url if ai is not None else _DEFAULT_AI_BASE_URL,
            ai_model=ai.model if ai is not None else _DEFAULT_AI_MODEL,
            provider_configured=provider_configured,
            ai_configured=ai is not None,
            developer_mode_enabled=bool(
                value.get("developer_mode_enabled", False)
            ),
            longbridge_client_id=client_id,
            futu_configured=futu_configured,
            futu_opend_host="127.0.0.1",
            futu_opend_port=11111,
            first_run_complete=bool(value.get("first_run_complete", False)),
            display_timezone=display_timezone,
            proxy_mode=proxy_mode,
            proxy_url=proxy_url,
            product_tour_dismissed=bool(
                value.get("product_tour_dismissed", False)
            ),
        )

    def load_appearance_mode(self) -> str:
        return self._appearance_mode(self._value())

    def save_appearance_mode(self, mode: str) -> None:
        if mode not in _APPEARANCE_MODES:
            raise PersistenceValidationError()
        value = self._value()
        value["appearance_mode"] = mode
        with SQLiteUnitOfWork(self._factory) as uow:
            SettingsRepository(uow.connection).upsert_setting(
                SettingRecord(
                    _CONFIG_KEY,
                    "JSON",
                    value,
                    3,
                    self._clock(),
                )
            )
            uow.commit()

    def save(
        self,
        settings: ServiceSettingsInput,
        *,
        ai_api_key: bytearray | None = None,
    ) -> ServiceSettingsDTO:
        try:
            self._validate(settings)
            current_value = self._value()
            provider_config_id = self._provider_config_id(current_value)
            now = self._clock()
            next_value = dict(current_value)
            display_timezone = (
                settings.display_timezone
                if settings.display_timezone is not None
                else str(
                    current_value.get(
                        "display_timezone",
                        "Asia/Shanghai",
                    )
                )
            )
            proxy_mode = (
                settings.proxy_mode
                if settings.proxy_mode is not None
                else str(current_value.get("proxy_mode", "off"))
            )
            proxy_url = (
                settings.proxy_url
                if settings.proxy_url is not None
                else str(current_value.get("proxy_url", ""))
            )
            next_value.update(
                {
                    "provider_mode": settings.provider_mode,
                    "provider_config_id": provider_config_id,
                    "longbridge_client_id": settings.longbridge_client_id.strip(),
                    "provider_timeout_seconds": settings.timeout_seconds,
                    "provider_max_retries": settings.max_retries,
                    "developer_mode_enabled": settings.developer_mode_enabled,
                    "display_timezone": display_timezone,
                    "proxy_mode": proxy_mode,
                    "proxy_url": proxy_url if proxy_mode == "custom" else "",
                    "first_run_complete": bool(
                        current_value.get("first_run_complete", False)
                    ),
                }
            )
            with SQLiteUnitOfWork(self._factory) as uow:
                SettingsRepository(uow.connection).upsert_setting(
                    SettingRecord(
                        _CONFIG_KEY,
                        "JSON",
                        next_value,
                        2,
                        now,
                    )
                )
                uow.commit()
            current = self._global_ai.load()
            if ai_api_key or current is not None:
                if self._ai_changed(current, settings, ai_api_key):
                    self._global_ai.save(
                        base_url=settings.ai_base_url,
                        model=settings.ai_model,
                        timeout_seconds=settings.timeout_seconds,
                        max_retries=settings.max_retries,
                        api_key=ai_api_key,
                        expected_revision=(
                            current.revision if current is not None else None
                        ),
                    )
                elif ai_api_key is not None:
                    ai_api_key[:] = b"\x00" * len(ai_api_key)
            return self.load()
        finally:
            if ai_api_key is not None:
                ai_api_key[:] = b"\x00" * len(ai_api_key)

    def save_provider_candidate(
        self,
        provider_id: str,
        *,
        configured: bool,
    ) -> ServiceSettingsDTO:
        provider = provider_id.strip().casefold()
        if provider not in {"longbridge", "futu"}:
            raise PersistenceValidationError()
        value = self._value()
        value[f"{provider}_configured"] = configured
        with SQLiteUnitOfWork(self._factory) as uow:
            SettingsRepository(uow.connection).upsert_setting(
                SettingRecord(
                    _CONFIG_KEY,
                    "JSON",
                    value,
                    3,
                    self._clock(),
                )
            )
            uow.commit()
        return self.load()

    def activate_provider(self, provider_id: str) -> ServiceSettingsDTO:
        provider = provider_id.strip().casefold()
        if provider not in {"longbridge", "futu"}:
            raise PersistenceValidationError()
        current = self.load()
        configured = (
            current.futu_configured
            if provider == "futu"
            else (
                bool(current.longbridge_client_id)
                and self._oauth_token_present(current.longbridge_client_id)
            )
        )
        if not configured:
            raise PersistenceValidationError()
        value = self._value()
        value["provider_mode"] = provider
        with SQLiteUnitOfWork(self._factory) as uow:
            SettingsRepository(uow.connection).upsert_setting(
                SettingRecord(
                    _CONFIG_KEY,
                    "JSON",
                    value,
                    3,
                    self._clock(),
                )
            )
            uow.commit()
        return self.load()

    def complete_first_run(self) -> ServiceSettingsDTO:
        current = self.load()
        if (
            current.provider_mode != "virtual"
            and not current.provider_configured
        ):
            raise PersistenceValidationError()
        value = self._value()
        value["first_run_complete"] = True
        value.setdefault("provider_mode", current.provider_mode)
        value.setdefault("longbridge_client_id", current.longbridge_client_id)
        with SQLiteUnitOfWork(self._factory) as uow:
            SettingsRepository(uow.connection).upsert_setting(
                SettingRecord(
                    _CONFIG_KEY,
                    "JSON",
                    value,
                    3,
                    self._clock(),
                )
            )
            uow.commit()
        return self.load()

    def dismiss_product_tour(self) -> ServiceSettingsDTO:
        value = self._value()
        if value.get("product_tour_dismissed") is True:
            return self.load()
        value["product_tour_dismissed"] = True
        with SQLiteUnitOfWork(self._factory) as uow:
            SettingsRepository(uow.connection).upsert_setting(
                SettingRecord(
                    _CONFIG_KEY,
                    "JSON",
                    value,
                    3,
                    self._clock(),
                )
            )
            uow.commit()
        return self.load()

    def read_secret(self, name: str) -> bytearray:
        if name != "ai_api_key":
            raise KeyError(name)
        config = self._global_ai.load()
        if config is None:
            raise KeyError(name)
        return self._global_ai.read_secret(config.revision)

    def delete_credentials(self, service: str) -> ServiceSettingsDTO:
        if service == "ai":
            current = self._global_ai.load()
            if current is not None:
                self._global_ai.delete(expected_revision=current.revision)
        elif service != "provider":
            raise PersistenceValidationError()
        return self.load()

    def global_ai_config(self) -> GlobalAIConfig | None:
        return self._global_ai.load()

    def _value(self) -> dict[str, object]:
        with SQLiteUnitOfWork(self._factory) as uow:
            record = SettingsRepository(uow.connection).get_setting(
                _CONFIG_KEY
            )
        return (
            dict(record.value)
            if record is not None and isinstance(record.value, dict)
            else {}
        )

    @staticmethod
    def _integer(
        value: dict[str, object],
        key: str,
        default: int,
    ) -> int:
        raw = value.get(key, default)
        return raw if isinstance(raw, int) and not isinstance(raw, bool) else default

    @staticmethod
    def _appearance_mode(value: dict[str, object]) -> str:
        mode = value.get("appearance_mode", "system")
        return mode if isinstance(mode, str) and mode in _APPEARANCE_MODES else "system"

    def _provider_config_id(self, value: dict[str, object]) -> str:
        existing = value.get("provider_config_id")
        if isinstance(existing, str):
            return existing
        return self._new_id()

    @staticmethod
    def _ai_changed(
        current: GlobalAIConfig | None,
        settings: ServiceSettingsInput,
        ai_api_key: bytearray | None,
    ) -> bool:
        return (
            ai_api_key is not None
            or current is None
            or current.base_url != settings.ai_base_url.rstrip("/")
            or current.model != settings.ai_model.strip()
            or current.timeout_seconds != settings.timeout_seconds
            or current.max_retries != settings.max_retries
        )

    @staticmethod
    def _validate(settings: ServiceSettingsInput) -> None:
        if (
            settings.provider_mode not in _PROVIDER_MODES
            or not 5 <= settings.timeout_seconds <= 180
            or not 0 <= settings.max_retries <= 5
            or not settings.ai_model.strip()
        ):
            raise PersistenceValidationError()
        if settings.longbridge_client_id:
            try:
                normalize_longbridge_client_id(
                    settings.longbridge_client_id.strip()
                )
            except InvalidLongbridgeClientIdError as exception:
                raise PersistenceValidationError() from exception
        if (
            settings.display_timezone is not None
            and settings.display_timezone not in DISPLAY_TIMEZONES
        ):
            raise PersistenceValidationError()
        if settings.proxy_mode is not None:
            if settings.proxy_mode not in PROXY_MODES:
                raise PersistenceValidationError()
            if settings.proxy_mode == "custom":
                try:
                    normalize_proxy_url(settings.proxy_url or "")
                except ValueError as exception:
                    raise PersistenceValidationError() from exception
        normalize_chat_endpoint(settings.ai_base_url)
