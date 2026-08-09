"""Versioned JSON codec owned by the RS strength module."""

from __future__ import annotations

from stock_toolbox.infrastructure.persistence.history_json import (
    export_history_json,
    parse_history_json,
)
from stock_toolbox.infrastructure.persistence.history_records import HistorySnapshotRecord


class RSHistoryCodec:
    analysis_type = "rs_strength"
    analysis_version = "1.0.0"
    result_schema_version = 1

    def dumps(self, snapshot: HistorySnapshotRecord) -> bytes:
        return export_history_json(snapshot)

    def loads(self, content: bytes) -> HistorySnapshotRecord:
        return parse_history_json(content)
