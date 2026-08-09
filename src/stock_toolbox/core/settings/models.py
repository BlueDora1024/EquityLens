"""Masked service configuration shown in the Settings dialog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServiceSettingsInput:
    provider_mode: str
    timeout_seconds: int
    max_retries: int
    ai_base_url: str
    ai_model: str
    developer_mode_enabled: bool = False
    longbridge_client_id: str = ""
    display_timezone: str | None = None
    proxy_mode: str | None = None
    proxy_url: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceSettingsDTO:
    provider_mode: str
    timeout_seconds: int
    max_retries: int
    ai_base_url: str
    ai_model: str
    provider_configured: bool
    ai_configured: bool
    developer_mode_enabled: bool
    longbridge_client_id: str = ""
    futu_configured: bool = False
    futu_opend_host: str = "127.0.0.1"
    futu_opend_port: int = 11111
    first_run_complete: bool = False
    display_timezone: str = "Asia/Shanghai"
    proxy_mode: str = "off"
    proxy_url: str = ""
    product_tour_dismissed: bool = False


@dataclass(frozen=True, slots=True)
class ServiceTestResult:
    service: str
    ok: bool
    code: str
    details: tuple[str, ...] = ()
