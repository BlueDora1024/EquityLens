from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest

from stock_toolbox.infrastructure.persistence.errors import PersistenceValidationError
from stock_toolbox.infrastructure.persistence.history_json import parse_history_json
from stock_toolbox.infrastructure.persistence.history_service import HistoryService
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork
from tests.integration.persistence.test_history_repository import (
    factory,
    snapshot,
)

NOW = datetime(2026, 7, 25, 13, tzinfo=UTC)


def uid(number: int) -> str:
    return f"90000000-0000-4000-8000-{number:012d}"


def service(tmp_path: Path) -> HistoryService:
    ids = iter(uid(number) for number in range(1, 100))
    return HistoryService(
        factory(tmp_path),
        clock=lambda: NOW,
        new_id=lambda: next(ids),
    )


def test_list_manage_and_delete_history(tmp_path: Path) -> None:
    history = service(tmp_path)
    with SQLiteUnitOfWork(history.factory) as uow:
        from stock_toolbox.infrastructure.persistence.history_repository import (
            HistoryRepository,
        )

        repository = HistoryRepository(uow.connection)
        repository.insert_snapshot(snapshot(1))
        repository.insert_snapshot(snapshot(2))
        uow.commit()

    listed = history.list(limit=10)
    assert [item.header.run_identifier for item in listed] == [
        "run-2",
        "run-1",
    ]

    history.update(
        listed[0].header.run_id,
        display_name="重点复盘",
        note="keep",
        pinned=True,
    )
    updated = history.get(listed[0].header.run_id)
    assert updated.header.display_name == "重点复盘"
    assert updated.header.original_run_name == "Original 2"
    assert updated.header.pinned

    history.delete(listed[1].header.run_id)
    assert [item.header.run_identifier for item in history.list()] == ["run-2"]


def test_multi_delete_and_clear_unpinned_are_atomic(
    tmp_path: Path,
) -> None:
    history = service(tmp_path)
    with SQLiteUnitOfWork(history.factory) as uow:
        from stock_toolbox.infrastructure.persistence.history_repository import (
            HistoryRepository,
        )

        repository = HistoryRepository(uow.connection)
        for number in (1, 2, 3):
            repository.insert_snapshot(snapshot(number))
        uow.commit()
    listed = history.list()
    history.update(
        listed[0].header.run_id,
        display_name=listed[0].header.display_name,
        note="",
        pinned=True,
    )

    assert history.delete_many((listed[1].header.run_id,)) == 1
    assert history.clear_unpinned() == 1
    remaining = history.list()
    assert len(remaining) == 1
    assert remaining[0].header.pinned


def test_complete_exports_and_atomic_publish(tmp_path: Path) -> None:
    history = service(tmp_path)
    expected = snapshot(3)
    with SQLiteUnitOfWork(history.factory) as uow:
        from stock_toolbox.infrastructure.persistence.history_repository import (
            HistoryRepository,
        )

        HistoryRepository(uow.connection).insert_snapshot(expected)
        uow.commit()

    json_content = history.export(expected.header.run_id, "json")
    markdown = history.export(expected.header.run_id, "markdown")
    csv_zip = history.export(expected.header.run_id, "csv")

    assert b'"stock_results"' in json_content
    assert "IREN.US" in markdown.decode()
    with zipfile.ZipFile(BytesIO(csv_zip)) as archive:
        assert set(archive.namelist()) == {
            "metadata.csv",
            "stocks.csv",
            "classifications.csv",
            "failures.csv",
        }
        assert b"IREN.US" in archive.read("stocks.csv")

    target = tmp_path / "published" / "result.json"
    history.publish(expected.header.run_id, "json", target)
    assert target.read_bytes() == json_content
    assert not tuple(target.parent.glob("*.tmp"))


def test_ai_report_follows_history_export_import_and_delete(
    tmp_path: Path,
) -> None:
    source = service(tmp_path / "source")
    expected = snapshot(30)
    with SQLiteUnitOfWork(source.factory) as uow:
        from stock_toolbox.infrastructure.persistence.history_repository import (
            HistoryRepository,
        )

        HistoryRepository(uow.connection).insert_snapshot(expected)
        uow.commit()
    report = {
        "model": "deepseek-v4-flash",
        "prompt_version": "rs-strength-report-v1",
        "content": "强弱复盘",
        "generated_at": NOW.isoformat(),
        "input_sha256": "a" * 64,
    }

    source.attach_ai_report(expected.header.run_id, report)

    stored = source.get(expected.header.run_id)
    assert stored.header.snapshot_extensions["ai_reports"] == [report]
    exported = source.export(expected.header.run_id, "json")
    assert (
        parse_history_json(exported).header.snapshot_extensions["ai_reports"]
        == [report]
    )

    target = service(tmp_path / "target")
    imported = target.import_json(exported)
    assert imported.header.snapshot_extensions["ai_reports"] == [report]
    target.delete(imported.header.run_id)
    assert target.list() == ()


def test_cancellable_publish_never_replaces_target_with_partial_content(
    tmp_path: Path,
) -> None:
    history = service(tmp_path)
    target = tmp_path / "published" / "result.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous-complete-export")
    canceled = False
    progress: list[tuple[int, int]] = []

    def report(completed: int, total: int) -> None:
        nonlocal canceled
        progress.append((completed, total))
        if completed:
            canceled = True

    published = history.publish_content(
        b"x" * (2 * 1024 * 1024 + 1),
        target,
        cancellation_requested=lambda: canceled,
        progress=report,
    )

    assert not published
    assert target.read_bytes() == b"previous-complete-export"
    assert progress
    assert not tuple(target.parent.glob("*.tmp"))


def test_json_import_remaps_local_ids_and_rejects_duplicate_identifier(
    tmp_path: Path,
) -> None:
    source = service(tmp_path / "source")
    original = snapshot(4)
    with SQLiteUnitOfWork(source.factory) as uow:
        from stock_toolbox.infrastructure.persistence.history_repository import (
            HistoryRepository,
        )

        HistoryRepository(uow.connection).insert_snapshot(original)
        uow.commit()
    content = source.export(original.header.run_id, "json")

    target = service(tmp_path / "target")
    imported = target.import_json(content)

    assert imported.header.run_id != original.header.run_id
    assert imported.header.run_identifier == original.header.run_identifier
    assert imported.header.source == "IMPORTED"
    assert imported.header.pinned
    assert imported.header.imported_at == NOW
    assert imported.header.operation_id is None
    assert all(item.run_id == imported.header.run_id for item in imported.members)
    assert imported.members[0].id != original.members[0].id
    assert imported.stock_results[0].run_member_id == imported.members[0].id

    with pytest.raises(PersistenceValidationError):
        target.import_json(content)
    assert len(target.list()) == 1
