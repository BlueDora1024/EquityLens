"""Bounded reading and filtering for the local diagnostics workspace."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from stock_toolbox.core.diagnostics.models import DiagnosticValue
from stock_toolbox.infrastructure.diagnostics.redaction import (
    SensitiveDiagnosticFieldError,
    sanitize_details,
    scrub_text,
)

_PRESENTATION_FIELDS = (
    "timestamp",
    "level",
    "module",
    "action",
    "status",
    "task_id",
    "stage",
    "ticker",
    "duration_ms",
    "memory_rss_mb",
    "memory_peak_mb",
    "error_code",
)


@dataclass(frozen=True, slots=True)
class DiagnosticFilter:
    module: str = ""
    level: str = ""
    query: str = ""


@dataclass(frozen=True, slots=True)
class DiagnosticFileStatus:
    health: str
    file_count: int
    total_bytes: int
    last_event: str
    warning_count: int
    error_count: int
    stall_count: int
    slow_query_count: int


def diagnostic_status(root: Path) -> DiagnosticFileStatus:
    try:
        files = tuple(path for path in root.glob("diagnostics-*.jsonl") if path.is_file())
        total_bytes = sum(path.stat().st_size for path in files)
    except OSError:
        return DiagnosticFileStatus("unavailable", 0, 0, "", 0, 0, 0, 0)
    events = recent_events(root, limit=500, scan_limit=2_000)
    return DiagnosticFileStatus(
        "normal",
        len(files),
        total_bytes,
        str(events[0].get("timestamp", "")) if events else "",
        sum(event.get("level") == "warning" for event in events),
        sum(event.get("level") == "error" for event in events),
        sum(event.get("action") == "ui_stall" for event in events),
        sum(
            event.get("action") in {"slow_query", "very_slow_query"}
            for event in events
        ),
    )


def recent_events(
    root: Path,
    *,
    filters: DiagnosticFilter | None = None,
    limit: int = 200,
    scan_limit: int = 5_000,
) -> list[dict[str, object]]:
    active_filters = filters or DiagnosticFilter()
    results: list[dict[str, object]] = []
    scanned = 0
    try:
        files = sorted(
            (path for path in root.glob("diagnostics-*.jsonl") if path.is_file()),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
    except OSError:
        return []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in reversed(lines):
            if scanned >= scan_limit or len(results) >= limit:
                return results
            scanned += 1
            event = sanitized_payload(line)
            if event is not None and _matches(event, active_filters):
                results.append(event)
    return results


def sanitized_payload(line: str) -> dict[str, object] | None:
    try:
        raw = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    payload: dict[str, object] = {}
    for key in _PRESENTATION_FIELDS:
        value = raw.get(key)
        if isinstance(value, str):
            payload[key] = scrub_text(value)
        elif isinstance(value, (int, float, bool)):
            payload[key] = value
    raw_details = raw.get("details")
    if isinstance(raw_details, dict):
        details: dict[str, DiagnosticValue] = {}
        for key, value in raw_details.items():
            if not isinstance(key, str) or (
                value is not None
                and not isinstance(value, (str, int, float, bool))
            ):
                continue
            try:
                details.update(sanitize_details({key: value}))
            except SensitiveDiagnosticFieldError:
                continue
        if details:
            payload["details"] = details
    return payload if payload.get("module") and payload.get("action") else None


def _matches(event: dict[str, object], filters: DiagnosticFilter) -> bool:
    if filters.module and event.get("module") != filters.module:
        return False
    if filters.level and event.get("level") != filters.level:
        return False
    query = filters.query.strip().casefold()
    if not query:
        return True
    searchable = " ".join(
        str(event.get(key, ""))
        for key in (
            "timestamp",
            "module",
            "action",
            "task_id",
            "ticker",
            "error_code",
        )
    ).casefold()
    return query in searchable
