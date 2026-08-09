"""Complete frozen-history queries, import, export, and atomic publishing."""

from __future__ import annotations

import csv
import io
import os
import tempfile
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import PersistenceValidationError
from stock_toolbox.infrastructure.persistence.history_json import (
    export_history_json,
    parse_history_json,
)
from stock_toolbox.infrastructure.persistence.history_records import (
    HistorySnapshotRecord,
)
from stock_toolbox.infrastructure.persistence.history_repository import HistoryRepository
from stock_toolbox.infrastructure.persistence.types import (
    canonical_json,
    parse_canonical_json,
)
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork


class HistoryService:
    """A synchronous boundary suitable for GUI workers and the developer CLI."""

    def __init__(
        self,
        factory: SQLiteConnectionFactory,
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
    ) -> None:
        self.factory = factory
        self._clock = clock
        self._new_id = new_id

    def list(self, *, limit: int | None = None) -> tuple[HistorySnapshotRecord, ...]:
        if limit is not None and limit < 1:
            raise PersistenceValidationError()
        sql = (
            "SELECT run_id FROM run_snapshots ORDER BY pinned DESC,created_at_utc DESC,run_id DESC"
        )
        parameters: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            parameters = (limit,)
        with SQLiteUnitOfWork(self.factory) as uow:
            repository = HistoryRepository(uow.connection)
            rows = uow.connection.execute(sql, parameters).fetchall()
            snapshots = tuple(repository.get_snapshot(str(row["run_id"])) for row in rows)
        if any(item is None for item in snapshots):
            raise PersistenceValidationError()
        return tuple(item for item in snapshots if item is not None)

    def get(self, run_id: str) -> HistorySnapshotRecord:
        with SQLiteUnitOfWork(self.factory) as uow:
            result = HistoryRepository(uow.connection).get_snapshot(run_id)
        if result is None:
            raise PersistenceValidationError()
        return result

    def update(
        self,
        run_id: str,
        *,
        display_name: str,
        note: str,
        pinned: bool,
    ) -> None:
        name = display_name.strip()
        if not name or len(name) > 120 or len(note) > 2000:
            raise PersistenceValidationError()
        with SQLiteUnitOfWork(self.factory) as uow:
            HistoryRepository(uow.connection).update_management(
                run_id,
                display_name=name,
                note=note,
                pinned=pinned,
            )
            uow.commit()

    def attach_ai_report(
        self,
        run_id: str,
        report: Mapping[str, object],
    ) -> None:
        canonical_report = parse_canonical_json(canonical_json(dict(report)))
        if not isinstance(canonical_report, dict):
            raise PersistenceValidationError()
        with SQLiteUnitOfWork(self.factory) as uow:
            row = uow.connection.execute(
                "SELECT snapshot_extensions_json FROM run_snapshots "
                "WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise PersistenceValidationError()
            extensions = parse_canonical_json(
                row["snapshot_extensions_json"]
            )
            if not isinstance(extensions, dict):
                raise PersistenceValidationError()
            reports = extensions.get("ai_reports", [])
            if not isinstance(reports, list) or not all(
                isinstance(item, dict) for item in reports
            ):
                raise PersistenceValidationError()
            extensions["ai_reports"] = [*reports, canonical_report]
            cursor = uow.connection.execute(
                "UPDATE run_snapshots SET snapshot_extensions_json=? "
                "WHERE run_id=?",
                (canonical_json(extensions), run_id),
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()

    def delete(self, run_id: str) -> None:
        with SQLiteUnitOfWork(self.factory) as uow:
            cursor = uow.connection.execute(
                "DELETE FROM run_snapshots WHERE run_id=?",
                (run_id,),
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()

    def delete_many(self, run_ids: tuple[str, ...]) -> int:
        if not run_ids or len(run_ids) != len(set(run_ids)):
            raise PersistenceValidationError()
        placeholders = ",".join("?" for _item in run_ids)
        with SQLiteUnitOfWork(self.factory) as uow:
            cursor = uow.connection.execute(
                f"DELETE FROM run_snapshots WHERE run_id IN ({placeholders})",
                run_ids,
            )
            if cursor.rowcount != len(run_ids):
                raise PersistenceValidationError()
            uow.commit()
        return len(run_ids)

    def clear_unpinned(self) -> int:
        with SQLiteUnitOfWork(self.factory) as uow:
            cursor = uow.connection.execute("DELETE FROM run_snapshots WHERE pinned=0")
            count = max(cursor.rowcount, 0)
            uow.commit()
        return count

    def export(self, run_id: str, format_name: str) -> bytes:
        snapshot = self.get(run_id)
        normalized = format_name.strip().lower()
        if normalized == "json":
            return export_history_json(snapshot)
        if normalized == "markdown":
            return _markdown(snapshot).encode()
        if normalized == "csv":
            return _csv_archive(snapshot)
        raise PersistenceValidationError()

    def publish(
        self,
        run_id: str,
        format_name: str,
        target: Path,
    ) -> None:
        content = self.export(run_id, format_name)
        _atomic_write(target, content)

    def publish_content(
        self,
        content: bytes,
        target: Path,
        *,
        cancellation_requested: Callable[[], bool],
        progress: Callable[[int, int], None],
    ) -> bool:
        if not isinstance(content, bytes) or not content:
            raise PersistenceValidationError()
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        completed = 0
        try:
            with os.fdopen(descriptor, "wb") as handle:
                for offset in range(0, len(content), 1024 * 1024):
                    if cancellation_requested():
                        return False
                    chunk = content[offset : offset + 1024 * 1024]
                    handle.write(chunk)
                    completed += len(chunk)
                    progress(completed, len(content))
                handle.flush()
                os.fsync(handle.fileno())
            if cancellation_requested():
                return False
            os.replace(temporary, target)
            return True
        finally:
            temporary.unlink(missing_ok=True)

    def import_json(self, content: bytes) -> HistorySnapshotRecord:
        parsed = parse_history_json(content)
        with SQLiteUnitOfWork(self.factory) as uow:
            duplicate = uow.connection.execute(
                "SELECT run_id FROM run_snapshots WHERE run_identifier=?",
                (parsed.header.run_identifier,),
            ).fetchone()
            if duplicate is not None:
                raise PersistenceValidationError()
            imported = _remap_import(
                parsed,
                imported_at=self._clock(),
                new_id=self._new_id,
            )
            HistoryRepository(uow.connection).insert_snapshot(imported)
            uow.commit()
        return imported


def _remap_import(
    snapshot: HistorySnapshotRecord,
    *,
    imported_at: datetime,
    new_id: Callable[[], str],
) -> HistorySnapshotRecord:
    run_id = new_id()
    range_ids = {item.run_range_id: new_id() for item in snapshot.ranges}
    member_ids = {item.id: new_id() for item in snapshot.members}
    return HistorySnapshotRecord(
        replace(
            snapshot.header,
            run_id=run_id,
            operation_id=None,
            source="IMPORTED",
            pinned=True,
            imported_at=imported_at,
            created_at=imported_at,
        ),
        tuple(
            replace(
                item,
                run_range_id=range_ids[item.run_range_id],
                run_id=run_id,
            )
            for item in snapshot.ranges
        ),
        tuple(replace(item, id=member_ids[item.id], run_id=run_id) for item in snapshot.members),
        tuple(
            replace(
                item,
                id=new_id(),
                run_id=run_id,
                run_member_id=member_ids[item.run_member_id],
                run_range_id=range_ids[item.run_range_id],
            )
            for item in snapshot.stock_results
        ),
        tuple(
            replace(
                item,
                id=new_id(),
                run_id=run_id,
                run_range_id=range_ids[item.run_range_id],
            )
            for item in snapshot.classification_period_results
        ),
        tuple(
            replace(item, id=new_id(), run_id=run_id) for item in snapshot.classification_results
        ),
        tuple(
            replace(
                item,
                id=new_id(),
                run_id=run_id,
                run_member_id=(
                    member_ids[item.run_member_id] if item.run_member_id is not None else None
                ),
                run_range_id=(
                    range_ids[item.run_range_id] if item.run_range_id is not None else None
                ),
            )
            for item in snapshot.failures
        ),
    )


def _markdown(snapshot: HistorySnapshotRecord) -> str:
    header = snapshot.header
    lines = [
        f"# {header.display_name}",
        "",
        f"- 状态：{header.status}",
        f"- 股票池：{header.watchlist_name}",
        f"- 基准：{header.benchmark_symbol}",
        f"- 实际结束日：{header.actual_end_date.isoformat()}",
        f"- Provider：{header.provider_display_name}",
        f"- 算法版本：{header.algorithm_version}",
        "",
        "## 个股结果",
        "",
        "| 证券 | 公司 | 参评分类 | 周期 | RS（百分点） |",
        "| --- | --- | --- | --- | ---: |",
    ]
    members = {item.id: item for item in snapshot.members}
    ranges = {item.run_range_id: item for item in snapshot.ranges}
    for stock_result in snapshot.stock_results:
        member = members[stock_result.run_member_id]
        run_range = ranges[stock_result.run_range_id]
        lines.append(
            f"| {member.canonical_symbol} | {member.company_name} | "
            f"{member.participating_classification_name} | "
            f"{run_range.label} | {stock_result.rs_percentage_points} |"
        )
    lines.extend(
        [
            "",
            "## 分类综合强度",
            "",
            "| 分类 | 综合分 | 状态 |",
            "| --- | ---: | --- |",
        ]
    )
    for classification_result in snapshot.classification_results:
        score = (
            ""
            if classification_result.composite_score is None
            else str(classification_result.composite_score)
        )
        lines.append(
            f"| {classification_result.classification_name} | {score} | "
            f"{classification_result.multi_period_status} |"
        )
    lines.extend(["", "## 失败明细", ""])
    if not snapshot.failures:
        lines.append("无。")
    else:
        lines.extend(
            f"- {item.canonical_symbol or '运行'} · {item.stage} · "
            f"{item.error_code} · {item.reason}"
            for item in snapshot.failures
        )
    return "\n".join(lines) + "\n"


def _csv_bytes(
    headers: tuple[str, ...],
    rows: Iterable[tuple[object, ...]],
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def _csv_archive(snapshot: HistorySnapshotRecord) -> bytes:
    header = snapshot.header
    members = {item.id: item for item in snapshot.members}
    ranges = {item.run_range_id: item for item in snapshot.ranges}
    files = {
        "metadata.csv": _csv_bytes(
            ("field", "value"),
            (
                ("run_identifier", header.run_identifier),
                ("status", header.status),
                ("watchlist", header.watchlist_name),
                ("benchmark", header.benchmark_symbol),
                ("actual_end_date", header.actual_end_date.isoformat()),
                ("algorithm_version", header.algorithm_version),
            ),
        ),
        "stocks.csv": _csv_bytes(
            (
                "symbol",
                "company",
                "classification",
                "range",
                "stock_return",
                "benchmark_return",
                "rs_percentage_points",
            ),
            (
                (
                    members[item.run_member_id].canonical_symbol,
                    members[item.run_member_id].company_name,
                    members[item.run_member_id].participating_classification_name,
                    ranges[item.run_range_id].label,
                    item.stock_return,
                    item.benchmark_return,
                    item.rs_percentage_points,
                )
                for item in snapshot.stock_results
            ),
        ),
        "classifications.csv": _csv_bytes(
            ("classification", "composite_score", "status", "reason"),
            (
                (
                    item.classification_name,
                    item.composite_score,
                    item.multi_period_status,
                    item.reason,
                )
                for item in snapshot.classification_results
            ),
        ),
        "failures.csv": _csv_bytes(
            ("symbol", "scope", "stage", "error_code", "reason"),
            (
                (
                    item.canonical_symbol,
                    item.scope,
                    item.stage,
                    item.error_code,
                    item.reason,
                )
                for item in snapshot.failures
            ),
        ),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return output.getvalue()


def _atomic_write(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
