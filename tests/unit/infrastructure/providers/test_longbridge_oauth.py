from __future__ import annotations

from pathlib import Path

import pytest

from stock_toolbox.infrastructure.providers.longbridge_oauth import (
    InvalidLongbridgeClientIdError,
    LongbridgeOAuthService,
)


class FakeBuilder:
    def __init__(
        self,
        token_path: Path,
        *,
        open_browser: bool,
        authorization_url: str = (
            "https://open.longbridge.com/oauth2/authorize"
        ),
    ) -> None:
        self.token_path = token_path
        self.open_browser = open_browser
        self.authorization_url = authorization_url

    def build(self, on_open_url):
        if self.open_browser:
            on_open_url(self.authorization_url)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text("opaque-token-cache", encoding="utf-8")
        return "oauth-handle"


class RegistrationResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> object:
        return self.payload


class RegistrationClient:
    def __init__(self, response: RegistrationResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, object]] = []

    def post(self, url: str, **kwargs: object) -> RegistrationResponse:
        self.calls.append((url, kwargs.get("json")))
        return self.response


def test_dynamic_registration_uses_official_public_client_contract(
    tmp_path: Path,
) -> None:
    client = RegistrationClient(
        RegistrationResponse(201, {"client_id": "registered-client"})
    )
    service = LongbridgeOAuthService(home=tmp_path, http_client=client)

    client_id = service.register()

    assert client_id == "registered-client"
    assert client.calls == [
        (
            "https://openapi.longbridge.com/oauth2/register",
            {
                "redirect_uris": ["http://localhost:60355/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": "EquityLens",
                "client_uri": (
                    "http://localhost:60355/longbridge-integration"
                ),
            },
        )
    ]


@pytest.mark.parametrize(
    "response",
    (
        RegistrationResponse(500, {}),
        RegistrationResponse(201, {}),
        RegistrationResponse(201, {"client_id": "../escape"}),
        RegistrationResponse(201, []),
    ),
)
def test_dynamic_registration_sanitizes_remote_failures(
    tmp_path: Path,
    response: RegistrationResponse,
) -> None:
    service = LongbridgeOAuthService(
        home=tmp_path,
        http_client=RegistrationClient(response),
    )

    with pytest.raises(RuntimeError, match="oauth_registration_failed"):
        service.register()


def test_oauth_authorization_uses_sdk_builder_and_standard_token_path(
    tmp_path: Path,
) -> None:
    opened: list[str] = []
    configs: list[tuple[object, bool]] = []
    quotes: list[object] = []
    client_id = "client-123"
    token_path = (
        tmp_path / ".longbridge" / "openapi" / "tokens" / client_id
    )
    service = LongbridgeOAuthService(
        home=tmp_path,
        builder_factory=lambda value: FakeBuilder(
            token_path,
            open_browser=value == client_id,
        ),
        config_factory=lambda oauth, *, enable_print_quote_packages: (
            configs.append((oauth, enable_print_quote_packages)) or "config"
        ),
        quote_factory=lambda config: quotes.append(config) or "quote",
    )

    quote = service.authorize(client_id, opened.append)

    assert quote == "quote"
    assert opened == [
        "https://open.longbridge.com/oauth2/authorize?scope=4"
    ]
    assert configs == [("oauth-handle", False)]
    assert quotes == ["config"]
    assert service.token_path(client_id) == token_path
    assert service.is_authorized(client_id)


def test_oauth_authorization_hides_account_order_and_trading_scopes(
    tmp_path: Path,
) -> None:
    opened: list[str] = []
    token_path = (
        tmp_path / ".longbridge" / "openapi" / "tokens" / "client-123"
    )
    service = LongbridgeOAuthService(
        home=tmp_path,
        builder_factory=lambda _value: FakeBuilder(
            token_path,
            open_browser=True,
            authorization_url=(
                "https://open.longbridge.com/oauth2/authorize"
                "?client_id=client-123&state=opaque"
            ),
        ),
        config_factory=lambda _oauth, **_kwargs: "config",
        quote_factory=lambda _config: "quote",
    )

    service.authorize("client-123", opened.append)

    assert opened == [
        (
            "https://open.longbridge.com/oauth2/authorize"
            "?client_id=client-123&state=opaque&scope=4"
        )
    ]


def test_oauth_client_id_rejects_path_traversal(tmp_path: Path) -> None:
    service = LongbridgeOAuthService(home=tmp_path)

    for value in ("", "../token", "client/id", " client "):
        with pytest.raises(InvalidLongbridgeClientIdError):
            service.token_path(value)


def test_clear_authorization_removes_only_selected_client_token(
    tmp_path: Path,
) -> None:
    service = LongbridgeOAuthService(home=tmp_path)
    selected = service.token_path("client-selected")
    other = service.token_path("client-other")
    selected.parent.mkdir(parents=True)
    selected.write_text("selected", encoding="utf-8")
    other.write_text("other", encoding="utf-8")

    service.clear("client-selected")

    assert not selected.exists()
    assert other.read_text(encoding="utf-8") == "other"


def test_quote_context_never_starts_browser_without_cached_token(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    service = LongbridgeOAuthService(
        home=tmp_path,
        builder_factory=lambda client_id: calls.append(client_id),
    )

    with pytest.raises(FileNotFoundError):
        service.quote_context("client-without-token")

    assert calls == []


def test_contexts_share_one_oauth_config_for_quote_and_fundamental(
    tmp_path: Path,
) -> None:
    client_id = "client-contexts"
    token_path = (
        tmp_path / ".longbridge" / "openapi" / "tokens" / client_id
    )
    token_path.parent.mkdir(parents=True)
    token_path.write_text("opaque-token-cache", encoding="utf-8")
    builds: list[str] = []
    configs: list[object] = []
    quotes: list[object] = []
    fundamentals: list[object] = []
    async_quotes: list[object] = []

    class CachedBuilder:
        def build(self, on_open_url):
            builds.append(client_id)
            return "oauth-handle"

    service = LongbridgeOAuthService(
        home=tmp_path,
        builder_factory=lambda _value: CachedBuilder(),
        config_factory=lambda oauth, *, enable_print_quote_packages: (
            configs.append((oauth, enable_print_quote_packages)) or "config"
        ),
        quote_factory=lambda config: quotes.append(config) or "quote",
        fundamental_factory=lambda config: (
            fundamentals.append(config) or "fundamental"
        ),
        async_quote_factory=lambda config: (
            async_quotes.append(config) or "async-quote"
        ),
    )

    contexts = service.contexts(client_id)

    assert contexts.quote == "quote"
    assert contexts.fundamental == "fundamental"
    assert async_quotes == []
    assert contexts.async_quote_factory() == "async-quote"
    assert builds == [client_id]
    assert configs == [("oauth-handle", False)]
    assert quotes == ["config"]
    assert fundamentals == ["config"]
    assert async_quotes == ["config"]
