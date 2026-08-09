"""Small validated network-setting helpers shared by every adapter."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

DISPLAY_TIMEZONES = frozenset(
    {"Asia/Shanghai", "America/New_York", "system"}
)
PROXY_MODES = frozenset({"off", "system", "custom"})
_PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_SYSTEM_PROXY_ENV = {key: os.environ.get(key) for key in _PROXY_KEYS}


def normalize_proxy_url(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    if (
        parsed.scheme.casefold() not in {"http", "https", "socks5"}
        or not parsed.hostname
    ):
        raise ValueError("invalid proxy URL")
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def masked_proxy_url(raw: str) -> str:
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.password is None:
        return raw
    user = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit(
        (
            parsed.scheme,
            f"{user}:••••@{host}{port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def apply_proxy_environment(mode: str, url: str) -> None:
    if mode not in PROXY_MODES:
        raise ValueError("invalid proxy mode")
    if mode == "custom":
        custom_url = normalize_proxy_url(url)
        for key in _PROXY_KEYS:
            os.environ[key] = custom_url
        return
    source = _SYSTEM_PROXY_ENV if mode == "system" else {}
    for key in _PROXY_KEYS:
        restored = source.get(key)
        if restored is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = restored
