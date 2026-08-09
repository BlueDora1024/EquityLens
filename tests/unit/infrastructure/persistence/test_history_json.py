from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from stock_toolbox.infrastructure.persistence.errors import PersistenceDataError
from stock_toolbox.infrastructure.persistence.history_json import (
    HISTORY_SCHEMA,
    LEGACY_HISTORY_SCHEMA,
    export_history_json,
    parse_history_json,
)
from stock_toolbox.infrastructure.persistence.history_repository import HistoryRepository
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork
from tests.integration.persistence.test_history_repository import (
    factory,
    partial_snapshot,
    snapshot,
)


def test_ready_history_json_is_canonical_and_semantically_roundtrips() -> None:
    expected = snapshot(1)

    content = export_history_json(expected)
    actual = parse_history_json(content)

    assert actual == expected
    assert content == export_history_json(actual)
    assert content.startswith(b'{"analysis_type":"rs_strength"')
    assert f'"schema":"{HISTORY_SCHEMA}"'.encode() in content
    assert not content.endswith(b"\n")
    assert b'"stock_return":"0.3"' in content
    assert b'"original_run_name":"Original 1"' in content
    assert b'"display_name":"Run 1"' in content


def test_partial_member_failure_scope_and_counts_roundtrip() -> None:
    expected = partial_snapshot(2)

    actual = parse_history_json(export_history_json(expected))

    assert actual == expected
    assert actual.header.valid_member_count == 1
    assert actual.header.failed_member_count == 1
    assert actual.header.failed_member_range_count == 0
    assert actual.failures[0].scope == "MEMBER"


def test_export_to_fresh_database_and_reexport_is_semantically_stable(
    tmp_path: Path,
) -> None:
    expected = partial_snapshot(3)
    restored = parse_history_json(export_history_json(expected))
    connection_factory = factory(tmp_path)
    with SQLiteUnitOfWork(connection_factory) as uow:
        HistoryRepository(uow.connection).insert_snapshot(restored)
        uow.commit()
    with SQLiteUnitOfWork(connection_factory) as uow:
        loaded = HistoryRepository(uow.connection).get_snapshot(
            expected.header.run_id
        )

    assert loaded is not None
    assert export_history_json(loaded) == export_history_json(expected)


@pytest.mark.parametrize(
    "content",
    [
        b"not-json",
        b'{"schema":"future","snapshot":{}}',
        b'{"schema":"rs-radar-history-v1"}',
        b'{"schema":"rs-radar-history-v1","snapshot":{},"unknown":1}',
    ],
)
def test_unknown_malformed_or_incomplete_json_is_rejected(content: bytes) -> None:
    with pytest.raises(PersistenceDataError):
        parse_history_json(content)


def test_legacy_rs_radar_envelope_remains_importable() -> None:
    expected = snapshot(4)
    current = export_history_json(expected)
    payload = __import__("json").loads(current)
    legacy = __import__("json").dumps(
        {
            "schema": LEGACY_HISTORY_SCHEMA,
            "snapshot": payload["snapshot"],
        },
        separators=(",", ":"),
    ).encode()

    assert parse_history_json(legacy) == expected


def test_export_rejects_header_format_version_mismatch() -> None:
    expected = snapshot(1)
    expected = replace(
        expected,
        header=replace(
            expected.header,
            snapshot_format_version="future",
        ),
    )

    with pytest.raises(PersistenceDataError):
        export_history_json(expected)


def test_oversized_json_is_rejected_before_parse() -> None:
    with pytest.raises(PersistenceDataError):
        parse_history_json(b" " * (10 * 1024 * 1024 + 1))
