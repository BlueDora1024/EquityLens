from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event, Thread
from typing import Any

import httpx
import pytest

from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.infrastructure.ai.openai_compatible import (
    AIAdapterError,
    AIServiceConfig,
)
from stock_toolbox.infrastructure.ai.technical_report import (
    OpenAICompatibleTechnicalReport,
)
from stock_toolbox.infrastructure.secrets.fake import FakeSecretStore


@dataclass
class Response:
    status_code: int = 200
    payload: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        return self.payload or {
            "choices": [
                {
                    "message": {
                        "content": "复盘正文",
                    }
                }
            ]
        }


@dataclass
class Client:
    responses: list[Response | Exception] = field(
        default_factory=lambda: [Response()]
    )
    calls: list[dict[str, object]] = field(default_factory=list)

    def post(self, url: str, **kwargs: object) -> Response:
        self.calls.append({"url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class InvalidJSONResponse(Response):
    def json(self) -> dict[str, Any]:
        raise ValueError("invalid json")


def adapter(
    client: Client,
    *,
    retries: int,
    waits: list[float] | None = None,
) -> OpenAICompatibleTechnicalReport:
    store = FakeSecretStore()
    store.create(7, bytearray(b"report-secret-canary"))
    return OpenAICompatibleTechnicalReport(
        AIServiceConfig(
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            7,
            Decimal(30),
            retries,
        ),
        store,
        client=client,
        sleeper=(waits.append if waits is not None else lambda _seconds: None),
    )


def test_report_client_keeps_secret_out_of_payload() -> None:
    store = FakeSecretStore()
    store.create(7, bytearray(b"report-secret-canary"))
    client = Client()
    adapter = OpenAICompatibleTechnicalReport(
        AIServiceConfig(
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            7,
            Decimal(30),
            0,
        ),
        store,
        client=client,
    )

    content = adapter.generate("system", {"results": [{"symbol": "IREN.US"}]})

    assert content == "复盘正文"
    assert "report-secret-canary" not in repr(client.calls[0]["json"])
    headers = client.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer report-secret-canary"


def test_report_timeout_retries_with_configured_bound_capped_at_two() -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    client = Client(
        [
            httpx.ReadTimeout("slow", request=request),
            httpx.ReadTimeout("slow", request=request),
            httpx.ReadTimeout("slow", request=request),
            Response(),
        ]
    )
    waits: list[float] = []

    with pytest.raises(AIAdapterError, match="timeout"):
        adapter(client, retries=5, waits=waits).generate("system", {})

    assert len(client.calls) == 3
    assert waits == [1.0, 2.0]


def test_report_timeout_recovers_without_request_storm() -> None:
    request = httpx.Request(
        "POST",
        "https://api.deepseek.com/chat/completions",
    )
    client = Client(
        [
            httpx.ReadTimeout("slow", request=request),
            Response(),
        ]
    )
    waits: list[float] = []

    content = adapter(client, retries=5, waits=waits).generate("system", {})

    assert content == "复盘正文"
    assert len(client.calls) == 2
    assert waits == [1.0]


def test_report_5xx_honors_safe_retry_after_then_recovers() -> None:
    client = Client(
        [
            Response(503, headers={"Retry-After": "3"}),
            Response(),
        ]
    )
    waits: list[float] = []

    content = adapter(client, retries=1, waits=waits).generate("system", {})

    assert content == "复盘正文"
    assert waits == [3.0]
    assert len(client.calls) == 2


@pytest.mark.parametrize("raw", ("nan", "inf", "-1", "999999"))
def test_report_retry_after_is_finite_and_bounded(raw: str) -> None:
    client = Client(
        [
            Response(503, headers={"Retry-After": raw}),
            Response(),
        ]
    )
    waits: list[float] = []

    adapter(client, retries=1, waits=waits).generate("system", {})

    assert len(waits) == 1
    assert 0 < waits[0] <= 60


def test_report_past_http_date_retries_immediately() -> None:
    client = Client(
        [
            Response(
                503,
                headers={
                    "Retry-After": "Thu, 24 Jul 2026 00:00:00 GMT",
                },
            ),
            Response(),
        ]
    )
    waits: list[float] = []
    store = FakeSecretStore()
    store.create(7, bytearray(b"report-secret-canary"))
    report = OpenAICompatibleTechnicalReport(
        AIServiceConfig(
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            7,
            Decimal(30),
            1,
        ),
        store,
        client=client,
        sleeper=waits.append,
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
    )

    assert report.generate("system", {}) == "复盘正文"
    assert waits == [0.0]


def test_report_429_returns_stable_rate_limited_after_bounded_retry() -> None:
    client = Client(
        [
            Response(429, headers={"Retry-After": "0"}),
            Response(429),
            Response(),
        ]
    )

    with pytest.raises(AIAdapterError, match="rate_limited"):
        adapter(client, retries=1).generate("system", {})

    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("status", "expected"),
    ((401, "authentication_failed"), (403, "permission_denied")),
)
def test_report_auth_and_permission_fail_without_retry(
    status: int,
    expected: str,
) -> None:
    client = Client([Response(status), Response()])

    with pytest.raises(AIAdapterError, match=expected):
        adapter(client, retries=2).generate("system", {})

    assert len(client.calls) == 1


def test_report_quota_error_is_stable_and_never_retried() -> None:
    client = Client(
        [
            Response(
                429,
                payload={
                    "error": {
                        "code": "insufficient_quota",
                        "message": "billing quota exhausted",
                    }
                },
            ),
            Response(),
        ]
    )

    with pytest.raises(AIAdapterError, match="quota_exhausted"):
        adapter(client, retries=2).generate("system", {})

    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("responses", "expected"),
    (
        ([Response(503), Response(503), Response()], "service_unavailable"),
        ([Response(429), Response(429), Response()], "rate_limited"),
    ),
)
def test_report_5xx_and_rate_limit_retry_only_once_when_config_is_two(
    responses: list[Response | Exception],
    expected: str,
) -> None:
    client = Client(responses)

    with pytest.raises(AIAdapterError, match=expected):
        adapter(client, retries=2).generate("system", {})

    assert len(client.calls) == 2


def test_report_invalid_200_body_retries_once_then_returns_stable_error() -> None:
    client = Client(
        [
            Response(payload={"choices": []}),
            Response(payload={"choices": []}),
            Response(),
        ]
    )

    with pytest.raises(AIAdapterError, match="invalid_response"):
        adapter(client, retries=2).generate("system", {})

    assert len(client.calls) == 2


def test_report_invalid_json_retries_once_then_returns_stable_error() -> None:
    client = Client(
        [
            InvalidJSONResponse(),
            InvalidJSONResponse(),
            Response(),
        ]
    )

    with pytest.raises(AIAdapterError, match="invalid_response"):
        adapter(client, retries=2).generate("system", {})

    assert len(client.calls) == 2


def test_report_retry_after_wait_is_interrupted_by_operation_cancel() -> None:
    store = FakeSecretStore()
    store.create(7, bytearray(b"report-secret-canary"))
    called = Event()

    class RateLimitedClient:
        def post(self, url: str, **kwargs: object) -> Response:
            del url, kwargs
            called.set()
            return Response(429, headers={"Retry-After": "60"})

    registry = OperationRegistry(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC)
    )
    registry.reserve("report-op", "report-key", "ai_report")
    context = registry.begin_reserved("report-op")
    assert context is not None
    report = OpenAICompatibleTechnicalReport(
        AIServiceConfig(
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            7,
            Decimal(30),
            2,
        ),
        store,
        client=RateLimitedClient(),
    )
    errors: list[BaseException] = []

    def generate() -> None:
        try:
            report.generate(
                "system",
                {},
                operation_control=context.operation_control,
            )
        except BaseException as error:  # noqa: BLE001 - test thread capture
            errors.append(error)

    worker = Thread(target=generate)
    worker.start()
    assert called.wait(timeout=1)
    registry.cancel("report-op")
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], AIAdapterError)
    assert str(errors[0]) == "canceled"
