from __future__ import annotations

import os

import pytest

from stock_toolbox.core.settings.network import (
    apply_proxy_environment,
    masked_proxy_url,
    normalize_proxy_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (" http://127.0.0.1:7890 ", "http://127.0.0.1:7890"),
        (
            "socks5://name:secret@proxy.example:1080",
            "socks5://name:secret@proxy.example:1080",
        ),
    ),
)
def test_normalizes_supported_proxy_urls(raw: str, expected: str) -> None:
    assert normalize_proxy_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ("", "ftp://proxy.example:21", "http:///missing-host", "proxy.example:7890"),
)
def test_rejects_invalid_proxy_urls(raw: str) -> None:
    with pytest.raises(ValueError, match="proxy"):
        normalize_proxy_url(raw)


def test_masks_proxy_credentials() -> None:
    assert (
        masked_proxy_url("http://name:secret@proxy.example:7890")
        == "http://name:••••@proxy.example:7890"
    )


def test_applies_and_clears_custom_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.casefold(), raising=False)

    apply_proxy_environment("custom", "http://127.0.0.1:7890")

    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["https_proxy"] == "http://127.0.0.1:7890"

    apply_proxy_environment("off", "")

    assert "HTTPS_PROXY" not in os.environ
    assert "https_proxy" not in os.environ
