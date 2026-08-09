"""Longbridge SDK OAuth lifecycle using its standard per-user token cache."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from longbridge.openapi import (
    AsyncQuoteContext,
    Config,
    FundamentalContext,
    HttpClient,
    OAuth,
    OAuthBuilder,
    QuoteContext,
)

_CLIENT_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_REGISTER_URL = "https://openapi.longbridge.com/oauth2/register"
_CLIENT_URI = "http://localhost:60355/longbridge-integration"
_MINIMAL_SCOPE = "4"


class InvalidLongbridgeClientIdError(ValueError):
    """The client ID cannot safely identify one SDK token-cache entry."""


class LongbridgeOAuthRegistrationError(RuntimeError):
    """Sanitized dynamic client registration failure."""

    def __init__(self) -> None:
        super().__init__("oauth_registration_failed")


class OAuthBuilderPort(Protocol):
    def build(self, on_open_url: Callable[[str], None]) -> object: ...


class OAuthConfigFactory(Protocol):
    def __call__(
        self,
        oauth: object,
        *,
        enable_print_quote_packages: bool,
    ) -> object: ...


class RegistrationResponsePort(Protocol):
    status_code: int

    def json(self) -> Any: ...


class RegistrationHTTPPort(Protocol):
    def post(self, url: str, **kwargs: Any) -> RegistrationResponsePort: ...


def normalize_longbridge_client_id(value: str) -> str:
    if _CLIENT_ID.fullmatch(value) is None:
        raise InvalidLongbridgeClientIdError(value)
    return value


def _market_data_authorization_url(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.pop("mcp-endpoint", None)
    query["scope"] = _MINIMAL_SCOPE
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _default_config_factory(
    oauth: object,
    *,
    enable_print_quote_packages: bool,
) -> object:
    if not isinstance(oauth, OAuth):
        raise TypeError("Longbridge SDK returned an invalid OAuth handle")
    return Config.from_oauth(
        oauth,
        enable_print_quote_packages=enable_print_quote_packages,
    )


def _default_quote_factory(config: object) -> object:
    if not isinstance(config, Config):
        raise TypeError("Longbridge SDK returned an invalid configuration")
    return QuoteContext(config)


def _default_async_quote_factory(config: object) -> object:
    if not isinstance(config, Config):
        raise TypeError("Longbridge SDK returned an invalid configuration")
    return AsyncQuoteContext.create(config)


def _default_fundamental_factory(config: object) -> object:
    if not isinstance(config, Config):
        raise TypeError("Longbridge SDK returned an invalid configuration")
    return FundamentalContext(config)


def _default_quant_http_factory(oauth: object) -> object:
    if not isinstance(oauth, OAuth):
        raise TypeError("Longbridge SDK returned an invalid OAuth handle")
    return HttpClient.from_oauth(oauth)


@dataclass(frozen=True, slots=True)
class LongbridgeContexts:
    quote: Any
    fundamental: Any
    async_quote_factory: Callable[[], Any]
    quant_http_factory: Callable[[], Any]


class LongbridgeOAuthService:
    def __init__(
        self,
        *,
        home: Path,
        builder_factory: Callable[[str], OAuthBuilderPort] = OAuthBuilder,
        config_factory: OAuthConfigFactory = _default_config_factory,
        quote_factory: Callable[[object], Any] = _default_quote_factory,
        async_quote_factory: Callable[
            [object], Any
        ] = _default_async_quote_factory,
        fundamental_factory: Callable[
            [object], Any
        ] = _default_fundamental_factory,
        quant_http_factory: Callable[
            [object], Any
        ] = _default_quant_http_factory,
        http_client: RegistrationHTTPPort | None = None,
    ) -> None:
        self._home = home.expanduser().resolve()
        self._builder_factory = builder_factory
        self._config_factory = config_factory
        self._quote_factory = quote_factory
        self._async_quote_factory = async_quote_factory
        self._fundamental_factory = fundamental_factory
        self._quant_http_factory = quant_http_factory
        self._http_client = http_client or httpx.Client(
            follow_redirects=False,
            timeout=30,
        )

    def register(self) -> str:
        try:
            response = self._http_client.post(
                _REGISTER_URL,
                json={
                    "redirect_uris": ["http://localhost:60355/callback"],
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "client_name": "EquityLens",
                    "client_uri": _CLIENT_URI,
                },
            )
            payload = response.json()
            if response.status_code not in {200, 201} or not isinstance(payload, dict):
                raise LongbridgeOAuthRegistrationError()
            return normalize_longbridge_client_id(str(payload["client_id"]))
        except LongbridgeOAuthRegistrationError:
            raise
        except Exception as error:
            raise LongbridgeOAuthRegistrationError() from error

    def token_path(self, client_id: str) -> Path:
        normalized = normalize_longbridge_client_id(client_id)
        return (
            self._home
            / ".longbridge"
            / "openapi"
            / "tokens"
            / normalized
        )

    def is_authorized(self, client_id: str) -> bool:
        try:
            token = self.token_path(client_id)
        except InvalidLongbridgeClientIdError:
            return False
        return token.is_file()

    def authorize(
        self,
        client_id: str,
        on_open_url: Callable[[str], None],
    ) -> Any:
        normalized = normalize_longbridge_client_id(client_id)
        oauth = self._builder_factory(normalized).build(
            lambda url: on_open_url(_market_data_authorization_url(url))
        )
        config = self._config_factory(
            oauth,
            enable_print_quote_packages=False,
        )
        return self._quote_factory(config)

    def quote_context(self, client_id: str) -> Any:
        return self.contexts(client_id).quote

    def contexts(self, client_id: str) -> LongbridgeContexts:
        if not self.is_authorized(client_id):
            raise FileNotFoundError("Longbridge OAuth token is not available")

        def unexpected_authorization(_url: str) -> None:
            raise RuntimeError("Longbridge OAuth token requires authorization")

        normalized = normalize_longbridge_client_id(client_id)
        oauth = self._builder_factory(normalized).build(
            unexpected_authorization
        )
        config = self._config_factory(
            oauth,
            enable_print_quote_packages=False,
        )
        return LongbridgeContexts(
            self._quote_factory(config),
            self._fundamental_factory(config),
            lambda: self._async_quote_factory(config),
            lambda: self._quant_http_factory(oauth),
        )

    def clear(self, client_id: str) -> None:
        token = self.token_path(client_id)
        if token.is_file() or token.is_symlink():
            token.unlink()
        elif token.exists():
            raise IsADirectoryError(token)
