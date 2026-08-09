"""Reject sensitive fields and scrub accidental credentials from short text."""

from __future__ import annotations

import re
from collections.abc import Mapping

from stock_toolbox.core.diagnostics.models import DiagnosticValue

_SENSITIVE_KEY = re.compile(
    r"(^|_)(api_?key|key|secret|token|password|authorization|cookie|"
    r"credential|prompt|request_body|response_body|proxy_url)($|_)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}")
_ASSIGNMENT = re.compile(
    r"\b(token|api[_-]?key|secret|password)\s*([=:])\s*[^\s,;]+",
    re.IGNORECASE,
)
_PROXY_USERINFO = re.compile(
    r"(?P<scheme>https?://|socks5?://)[^/@\s:]+:[^@\s]+@",
    re.IGNORECASE,
)
_MAX_TEXT = 240


class SensitiveDiagnosticFieldError(ValueError):
    """A caller attempted to place a forbidden field in diagnostics."""


def scrub_text(value: str) -> str:
    scrubbed = _BEARER.sub("Bearer [REDACTED]", value)
    scrubbed = _OPENAI_KEY.sub("[REDACTED]", scrubbed)
    scrubbed = _ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        scrubbed,
    )
    scrubbed = _PROXY_USERINFO.sub(
        lambda match: f"{match.group('scheme')}[REDACTED]@",
        scrubbed,
    )
    return scrubbed[:_MAX_TEXT]


def sanitize_details(
    details: Mapping[str, DiagnosticValue],
) -> dict[str, DiagnosticValue]:
    sanitized: dict[str, DiagnosticValue] = {}
    for key, value in details.items():
        if _SENSITIVE_KEY.search(key):
            raise SensitiveDiagnosticFieldError(key)
        sanitized[key] = scrub_text(value) if isinstance(value, str) else value
    return sanitized
