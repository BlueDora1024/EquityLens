"""Strict canonical JSON serialization for complete history snapshots."""

from __future__ import annotations

import json
import types
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, get_args, get_origin, get_type_hints

from stock_toolbox.infrastructure.persistence.errors import PersistenceDataError
from stock_toolbox.infrastructure.persistence.history_records import HistorySnapshotRecord
from stock_toolbox.infrastructure.persistence.types import (
    canonical_date,
    canonical_decimal_text,
    canonical_instant,
    parse_canonical_date,
    parse_canonical_decimal,
    parse_canonical_instant,
)

LEGACY_HISTORY_SCHEMA = "rs-radar-history-v1"
HISTORY_SCHEMA = "stock-analysis-toolbox-history-v1"
MAX_HISTORY_JSON_BYTES = 10 * 1024 * 1024


def _encode(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _encode(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, datetime):
        return canonical_instant(value)
    if isinstance(value, date):
        return canonical_date(value)
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): _encode(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise PersistenceDataError("History contains unsupported data")


def export_history_json(snapshot: HistorySnapshotRecord) -> bytes:
    if snapshot.header.snapshot_format_version != LEGACY_HISTORY_SCHEMA:
        raise PersistenceDataError("History format version is unsupported")
    try:
        return json.dumps(
            {
                "analysis_type": "rs_strength",
                "analysis_version": "1.0.0",
                "result_schema_version": 1,
                "schema": HISTORY_SCHEMA,
                "snapshot": _encode(snapshot),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as error:
        raise PersistenceDataError("History cannot be serialized") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output = {}
    for key, value in pairs:
        if key in output:
            raise PersistenceDataError("History JSON contains duplicate keys")
        output[key] = value
    return output


def parse_history_json(content: bytes) -> HistorySnapshotRecord:
    if not isinstance(content, bytes) or len(content) > MAX_HISTORY_JSON_BYTES:
        raise PersistenceDataError("History JSON size is invalid")
    try:
        root = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                PersistenceDataError("History JSON number is invalid")
            ),
        )
        if not isinstance(root, dict):
            raise PersistenceDataError("History JSON envelope is invalid")
        if root.get("schema") == LEGACY_HISTORY_SCHEMA:
            if set(root) != {"schema", "snapshot"}:
                raise PersistenceDataError("History JSON envelope is invalid")
        elif root.get("schema") == HISTORY_SCHEMA:
            if (
                set(root)
                != {
                    "analysis_type",
                    "analysis_version",
                    "result_schema_version",
                    "schema",
                    "snapshot",
                }
                or root["analysis_type"] != "rs_strength"
                or root["analysis_version"] != "1.0.0"
                or root["result_schema_version"] != 1
            ):
                raise PersistenceDataError("History JSON envelope is invalid")
        else:
            raise PersistenceDataError("History JSON envelope is invalid")
        snapshot = _decode(root["snapshot"], HistorySnapshotRecord)
    except PersistenceDataError:
        raise
    except (RecursionError, TypeError, UnicodeDecodeError, ValueError) as error:
        raise PersistenceDataError("History JSON is invalid") from error
    if not isinstance(snapshot, HistorySnapshotRecord):
        raise PersistenceDataError("History snapshot is invalid")
    if snapshot.header.snapshot_format_version != LEGACY_HISTORY_SCHEMA:
        raise PersistenceDataError("History format version is inconsistent")
    return snapshot


def _decode(value: Any, annotation: Any) -> Any:
    if annotation is Any:
        return value
    if annotation is datetime:
        return parse_canonical_instant(value)
    if annotation is date:
        return parse_canonical_date(value)
    if annotation is Decimal:
        return parse_canonical_decimal(value)
    if annotation in {str, int, bool}:
        if type(value) is not annotation:
            raise PersistenceDataError("History scalar type is invalid")
        return value

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is types.UnionType:
        if value is None and type(None) in arguments:
            return None
        errors = []
        for option in arguments:
            if option is type(None):
                continue
            try:
                return _decode(value, option)
            except PersistenceDataError as error:
                errors.append(error)
        raise PersistenceDataError("History union value is invalid") from (
            errors[-1] if errors else None
        )
    if origin is tuple:
        if not isinstance(value, list):
            raise PersistenceDataError("History tuple must be an array")
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            item_type = arguments[0]
            return tuple(_decode(item, item_type) for item in value)
        if len(value) != len(arguments):
            raise PersistenceDataError("History tuple length is invalid")
        return tuple(
            _decode(item, item_type)
            for item, item_type in zip(value, arguments, strict=True)
        )
    if origin in {dict, Mapping}:
        if not isinstance(value, dict):
            raise PersistenceDataError("History mapping is invalid")
        key_type, value_type = arguments
        if key_type is not str or not all(
            isinstance(key, str) for key in value
        ):
            raise PersistenceDataError("History mapping key is invalid")
        return {
            key: _decode(item, value_type)
            for key, item in value.items()
        }
    if isinstance(annotation, type) and is_dataclass(annotation):
        if not isinstance(value, dict):
            raise PersistenceDataError("History object is invalid")
        hints = get_type_hints(annotation)
        expected = {field.name for field in fields(annotation)}
        if set(value) != expected:
            raise PersistenceDataError("History object fields are invalid")
        return annotation(
            **{
                name: _decode(value[name], hints[name])
                for name in expected
            }
        )
    raise PersistenceDataError("History type is unsupported")
