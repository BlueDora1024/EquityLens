from __future__ import annotations

import pytest

from stock_toolbox.infrastructure.diagnostics.redaction import (
    SensitiveDiagnosticFieldError,
    sanitize_details,
    scrub_text,
)


@pytest.mark.parametrize(
    "key",
    (
        "api_key",
        "oauth_token",
        "Authorization",
        "proxy_url",
        "request_body",
        "response_body",
        "cookie",
    ),
)
def test_sensitive_keys_are_rejected(key: str) -> None:
    with pytest.raises(SensitiveDiagnosticFieldError):
        sanitize_details({key: "secret"})


def test_ticker_and_performance_details_are_allowed() -> None:
    assert sanitize_details(
        {
            "ticker": "IREN.US",
            "duration_ms": 315,
            "retry_count": 2,
        }
    ) == {
        "ticker": "IREN.US",
        "duration_ms": 315,
        "retry_count": 2,
    }


@pytest.mark.parametrize(
    "raw",
    (
        "Bearer abcdefghijklmnop",
        "sk-12345678901234567890",
        "token=abcdefghijklmnop",
        "http://name:secret@127.0.0.1:7890",
    ),
)
def test_value_scrubber_removes_secret_shapes(raw: str) -> None:
    value = scrub_text(raw)

    assert "abcdefghijklmnop" not in value
    assert "12345678901234567890" not in value
    assert "name:secret@" not in value
    assert "[REDACTED]" in value


def test_scrubber_caps_free_text() -> None:
    assert len(scrub_text("x" * 500)) == 240
