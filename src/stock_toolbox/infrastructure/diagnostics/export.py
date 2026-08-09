"""Create a self-contained diagnostic ZIP without business data."""

from __future__ import annotations

import json
import platform
import zipfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from stock_toolbox.infrastructure.diagnostics.query import sanitized_payload
from stock_toolbox.infrastructure.diagnostics.redaction import scrub_text

_README = """EquityLens 诊断日志

此压缩包仅包含脱敏后的结构化诊断事件、运行环境和性能汇总。
不包含业务数据库、用户设置、API Key、OAuth Token、代理凭据、
行情明细、CSV 内容、AI 提示词、AI 响应或分析历史。
"""


def export_diagnostics(
    root: Path,
    target: Path,
    *,
    environment: Mapping[str, str],
) -> Path:
    events = _read_sanitized_events(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    environment_payload = {
        "python": platform.python_version(),
        "platform": scrub_text(platform.platform()),
        "architecture": platform.machine(),
        **{key: scrub_text(value) for key, value in environment.items()},
    }
    levels = Counter(str(event.get("level", "")) for event in events)
    actions = Counter(str(event.get("action", "")) for event in events)
    summary = {
        "event_count": len(events),
        "warning_count": levels["warning"],
        "error_count": levels["error"],
        "ui_stall_count": actions["ui_stall"],
        "slow_query_count": (
            actions["slow_query"] + actions["very_slow_query"]
        ),
    }
    jsonl = "".join(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        for event in events
    )
    with zipfile.ZipFile(
        target,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        archive.writestr("README.txt", _README)
        archive.writestr(
            "environment.json",
            json.dumps(environment_payload, ensure_ascii=False, indent=2),
        )
        archive.writestr(
            "summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2),
        )
        archive.writestr("logs/diagnostics.jsonl", jsonl)
    return target


def _read_sanitized_events(root: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for path in sorted(root.glob("diagnostics-*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        events.extend(
            event
            for line in lines
            if (event := sanitized_payload(line)) is not None
        )
    return events
