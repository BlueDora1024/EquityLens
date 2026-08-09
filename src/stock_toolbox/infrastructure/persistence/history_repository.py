"""Atomic persistence and reconstruction of frozen run snapshots."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from stock_toolbox.infrastructure.persistence.errors import PersistenceValidationError
from stock_toolbox.infrastructure.persistence.history_records import (
    HistoryClassificationPeriodRecord,
    HistoryClassificationRecord,
    HistoryFailureRecord,
    HistoryMemberRecord,
    HistoryRangeRecord,
    HistorySnapshotHeader,
    HistorySnapshotRecord,
    HistoryStockResultRecord,
)
from stock_toolbox.infrastructure.persistence.repositories import _mapped
from stock_toolbox.infrastructure.persistence.types import (
    canonical_date,
    canonical_decimal_text,
    canonical_instant,
    canonical_json,
    parse_canonical_date,
    parse_canonical_decimal,
    parse_canonical_instant,
    parse_canonical_json,
    parse_uuid4,
)


def _uuid(value: str) -> str:
    return str(parse_uuid4(value))


def _decimal_or_none(value: Any) -> Any:
    return canonical_decimal_text(value) if value is not None else None


def _parse_decimal_or_none(value: Any) -> Any:
    return parse_canonical_decimal(value) if value is not None else None


class HistoryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert_snapshot(self, snapshot: HistorySnapshotRecord) -> None:
        self._validate(snapshot)
        header = snapshot.header
        _mapped(
            lambda: self._connection.execute(
                "INSERT INTO run_snapshots("
                "run_id,run_identifier,operation_id,source,status,pinned,"
                "display_name,note,original_run_name,started_at_utc,"
                "completed_at_utc,created_at_utc,imported_at_utc,provider_id,"
                "provider_display_name,provider_contract_version,"
                "benchmark_symbol,watchlist_source_id,watchlist_name,"
                "watchlist_revision,requested_end_date,actual_end_date,"
                "member_count,valid_member_count,failed_member_count,"
                "failed_member_range_count,algorithm_version,"
                "snapshot_format_version,snapshot_extensions_json"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _uuid(header.run_id),
                    header.run_identifier,
                    header.operation_id,
                    header.source,
                    header.status,
                    int(header.pinned),
                    header.display_name,
                    header.note,
                    header.original_run_name,
                    canonical_instant(header.started_at),
                    canonical_instant(header.completed_at),
                    canonical_instant(header.created_at),
                    (
                        canonical_instant(header.imported_at)
                        if header.imported_at is not None
                        else None
                    ),
                    header.provider_id,
                    header.provider_display_name,
                    header.provider_contract_version,
                    header.benchmark_symbol,
                    header.watchlist_source_id,
                    header.watchlist_name,
                    header.watchlist_revision,
                    canonical_date(header.requested_end_date),
                    canonical_date(header.actual_end_date),
                    header.member_count,
                    header.valid_member_count,
                    header.failed_member_count,
                    header.failed_member_range_count,
                    header.algorithm_version,
                    header.snapshot_format_version,
                    canonical_json(dict(header.snapshot_extensions)),
                ),
            )
        )
        _mapped(
            lambda: self._connection.execute(
                "INSERT INTO analysis_runs("
                "run_id,analysis_type,analysis_version,operation_id,status,"
                "provider_id,watchlist_snapshot_json,started_at_utc,"
                "completed_at_utc,result_schema_version"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    _uuid(header.run_id),
                    "rs_strength",
                    "1.0.0",
                    header.operation_id,
                    header.status,
                    header.provider_id,
                    canonical_json(
                        {
                            "source_id": header.watchlist_source_id,
                            "name": header.watchlist_name,
                            "revision": header.watchlist_revision,
                            "member_count": header.member_count,
                        }
                    ),
                    canonical_instant(header.started_at),
                    canonical_instant(header.completed_at),
                    1,
                ),
            )
        )
        self._insert_ranges(snapshot.ranges)
        self._insert_members(snapshot.members)
        self._insert_stock_results(snapshot.stock_results)
        self._insert_period_results(snapshot.classification_period_results)
        self._insert_classification_results(snapshot.classification_results)
        self._insert_failures(snapshot.failures)

    def evict_excess_unpinned_auto(
        self,
        *,
        keep: int = 10,
    ) -> tuple[str, ...]:
        if keep < 0:
            raise ValueError("keep must not be negative")
        rows = _mapped(
            lambda: self._connection.execute(
                "SELECT run_id FROM run_snapshots "
                "WHERE source='AUTO' AND pinned=0 "
                "ORDER BY created_at_utc DESC,run_id DESC "
                "LIMIT -1 OFFSET ?",
                (keep,),
            ).fetchall()
        )
        run_ids = tuple(str(row[0]) for row in rows)
        if run_ids:
            _mapped(
                lambda: self._connection.executemany(
                    "DELETE FROM run_snapshots WHERE run_id=?",
                    ((run_id,) for run_id in run_ids),
                )
            )
        return run_ids

    def update_management(
        self,
        run_id: str,
        *,
        display_name: str,
        note: str,
        pinned: bool,
    ) -> None:
        cursor = _mapped(
            lambda: self._connection.execute(
                "UPDATE run_snapshots "
                "SET display_name=?,note=?,pinned=? WHERE run_id=?",
                (display_name, note, int(pinned), run_id),
            )
        )
        if cursor.rowcount != 1:
            raise PersistenceValidationError()

    def get_snapshot(self, run_id: str) -> HistorySnapshotRecord | None:
        row = _mapped(
            lambda: self._connection.execute(
                "SELECT * FROM run_snapshots WHERE run_id=?",
                (run_id,),
            ).fetchone()
        )
        if row is None:
            return None
        header = self._header_from_row(row)
        ranges = tuple(
            self._range_from_row(item)
            for item in self._rows(
                "run_ranges",
                run_id,
                "ordinal,range_key,run_range_id",
            )
        )
        members = tuple(
            self._member_from_row(item)
            for item in self._rows(
                "run_members",
                run_id,
                "ordinal,canonical_symbol,id",
            )
        )
        stocks = tuple(
            self._stock_from_row(item)
            for item in self._rows(
                "run_stock_results",
                run_id,
                "run_member_id,run_range_id",
            )
        )
        periods = tuple(
            self._period_from_row(item)
            for item in self._rows(
                "run_classification_period_results",
                run_id,
                "run_range_id,classification_snapshot_key",
            )
        )
        classifications = tuple(
            self._classification_from_row(item)
            for item in self._rows(
                "run_classification_results",
                run_id,
                "classification_snapshot_key",
            )
        )
        failures = tuple(
            self._failure_from_row(item)
            for item in self._rows("run_failures", run_id, "ordinal")
        )
        output = HistorySnapshotRecord(
            header,
            ranges,
            members,
            stocks,
            periods,
            classifications,
            failures,
        )
        self._validate(output)
        return output

    def _rows(
        self,
        table: str,
        run_id: str,
        order_by: str,
    ) -> list[sqlite3.Row]:
        allowed = {
            "run_ranges",
            "run_members",
            "run_stock_results",
            "run_classification_period_results",
            "run_classification_results",
            "run_failures",
        }
        if table not in allowed:
            raise ValueError("table is not allowed")
        # Both identifiers come from the fixed whitelist/call sites above.
        return _mapped(
            lambda: self._connection.execute(
                f"SELECT * FROM {table} WHERE run_id=? ORDER BY {order_by}",
                (run_id,),
            ).fetchall()
        )

    @staticmethod
    def _validate(snapshot: HistorySnapshotRecord) -> None:
        header = snapshot.header
        if len(snapshot.members) != header.member_count:
            raise PersistenceValidationError()
        if header.valid_member_count + header.failed_member_count != header.member_count:
            raise PersistenceValidationError()
        child_collections: tuple[Iterable[Any], ...] = (
            snapshot.ranges,
            snapshot.members,
            snapshot.stock_results,
            snapshot.classification_period_results,
            snapshot.classification_results,
            snapshot.failures,
        )
        if any(
            child.run_id != header.run_id
            for collection in child_collections
            for child in collection
        ):
            raise PersistenceValidationError()
        member_ids = {member.id for member in snapshot.members}
        range_ids = {item.run_range_id for item in snapshot.ranges}
        failures_by_member: dict[str, list[HistoryFailureRecord]] = {}
        for failure in snapshot.failures:
            if failure.fatal or failure.scope not in {"MEMBER", "MEMBER_RANGE"}:
                raise PersistenceValidationError()
            if failure.run_member_id is None:
                raise PersistenceValidationError()
            failures_by_member.setdefault(failure.run_member_id, []).append(
                failure
            )
        if len(failures_by_member) != header.failed_member_count:
            raise PersistenceValidationError()
        range_failure_count = sum(
            failure.scope == "MEMBER_RANGE"
            for failure in snapshot.failures
        )
        if range_failure_count != header.failed_member_range_count:
            raise PersistenceValidationError()
        result_members = {
            result.run_member_id for result in snapshot.stock_results
        }
        result_pairs = {
            (result.run_member_id, result.run_range_id)
            for result in snapshot.stock_results
        }
        for member_id, failures in failures_by_member.items():
            scopes = {failure.scope for failure in failures}
            if "MEMBER" in scopes and (
                len(failures) != 1 or member_id in result_members
            ):
                raise PersistenceValidationError()
        valid_members = {
            member.id
            for member in snapshot.members
            if member.id not in failures_by_member
            and all(
                (member.id, range_id) in result_pairs
                for range_id in range_ids
            )
        }
        if len(valid_members) != header.valid_member_count:
            raise PersistenceValidationError()
        if sorted(failure.ordinal for failure in snapshot.failures) != list(
            range(len(snapshot.failures))
        ):
            raise PersistenceValidationError()
        if any(
            result.run_member_id not in member_ids
            or result.run_range_id not in range_ids
            for result in snapshot.stock_results
        ):
            raise PersistenceValidationError()
        if any(
            result.run_range_id not in range_ids
            for result in snapshot.classification_period_results
        ):
            raise PersistenceValidationError()
        if any(
            failure.run_member_id is not None
            and failure.run_member_id not in member_ids
            or failure.run_range_id is not None
            and failure.run_range_id not in range_ids
            for failure in snapshot.failures
        ):
            raise PersistenceValidationError()
        if header.status == "READY":
            if snapshot.failures or len(snapshot.stock_results) != (
                len(snapshot.members) * len(snapshot.ranges)
            ):
                raise PersistenceValidationError()
        elif header.status == "PARTIAL":
            if not snapshot.stock_results or not snapshot.failures:
                raise PersistenceValidationError()
        else:
            raise PersistenceValidationError()

    def _insert_ranges(self, records: tuple[HistoryRangeRecord, ...]) -> None:
        self._executemany(
            "INSERT INTO run_ranges VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    _uuid(item.run_range_id),
                    _uuid(item.run_id),
                    item.ordinal,
                    item.range_key,
                    item.label,
                    item.kind,
                    canonical_date(item.requested_start_date),
                    canonical_date(item.requested_end_date),
                    canonical_date(item.actual_start_date),
                    canonical_date(item.actual_end_date),
                    canonical_decimal_text(item.benchmark_start_close),
                    canonical_decimal_text(item.benchmark_end_close),
                    canonical_decimal_text(item.base_weight),
                    canonical_decimal_text(item.normalized_weight),
                )
                for item in records
            ),
        )

    def _insert_members(self, records: tuple[HistoryMemberRecord, ...]) -> None:
        self._executemany(
            "INSERT INTO run_members VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    _uuid(item.id),
                    _uuid(item.run_id),
                    item.ordinal,
                    item.source_membership_id,
                    item.source_security_id,
                    item.source_binding_id,
                    item.canonical_symbol,
                    item.market,
                    item.company_name,
                    item.classification_snapshot_key,
                    item.source_classification_id,
                    item.participating_classification_name,
                    item.participating_classification_normalized_name,
                )
                for item in records
            ),
        )

    def _insert_stock_results(
        self,
        records: tuple[HistoryStockResultRecord, ...],
    ) -> None:
        self._executemany(
            "INSERT INTO run_stock_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    _uuid(item.id),
                    _uuid(item.run_id),
                    _uuid(item.run_member_id),
                    _uuid(item.run_range_id),
                    canonical_decimal_text(item.stock_start_close),
                    canonical_decimal_text(item.stock_end_close),
                    canonical_decimal_text(item.benchmark_start_close),
                    canonical_decimal_text(item.benchmark_end_close),
                    canonical_decimal_text(item.stock_return),
                    canonical_decimal_text(item.benchmark_return),
                    canonical_decimal_text(item.rs_percentage_points),
                )
                for item in records
            ),
        )

    def _insert_period_results(
        self,
        records: tuple[HistoryClassificationPeriodRecord, ...],
    ) -> None:
        self._executemany(
            "INSERT INTO run_classification_period_results VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    _uuid(item.id),
                    _uuid(item.run_id),
                    _uuid(item.run_range_id),
                    item.classification_snapshot_key,
                    item.classification_name,
                    item.total_member_count,
                    item.valid_member_count,
                    canonical_decimal_text(item.coverage),
                    _decimal_or_none(item.mean_rs),
                    _decimal_or_none(item.median_rs),
                    item.positive_member_count,
                    _decimal_or_none(item.strong_breadth),
                    canonical_json([dict(member) for member in item.top_members]),
                    canonical_json(
                        [dict(member) for member in item.bottom_members]
                    ),
                    item.eligibility,
                    item.eligibility_reason,
                    _decimal_or_none(item.median_percentile),
                    _decimal_or_none(item.breadth_percentile),
                    _decimal_or_none(item.period_score),
                    item.score_unavailable_reason,
                )
                for item in records
            ),
        )

    def _insert_classification_results(
        self,
        records: tuple[HistoryClassificationRecord, ...],
    ) -> None:
        self._executemany(
            "INSERT INTO run_classification_results VALUES (?,?,?,?,?,?,?)",
            (
                (
                    _uuid(item.id),
                    _uuid(item.run_id),
                    item.classification_snapshot_key,
                    item.classification_name,
                    _decimal_or_none(item.composite_score),
                    item.multi_period_status,
                    item.reason,
                )
                for item in records
            ),
        )

    def _insert_failures(
        self,
        records: tuple[HistoryFailureRecord, ...],
    ) -> None:
        self._executemany(
            "INSERT INTO run_failures VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    _uuid(item.id),
                    _uuid(item.run_id),
                    _uuid(item.run_member_id)
                    if item.run_member_id is not None
                    else None,
                    _uuid(item.run_range_id)
                    if item.run_range_id is not None
                    else None,
                    item.scope,
                    item.canonical_symbol,
                    item.stage,
                    item.error_code,
                    item.reason,
                    int(item.fatal),
                    item.ordinal,
                )
                for item in records
            ),
        )

    def _executemany(
        self,
        statement: str,
        values: Iterable[tuple[Any, ...]],
    ) -> None:
        _mapped(lambda: self._connection.executemany(statement, values))

    @staticmethod
    def _header_from_row(row: sqlite3.Row) -> HistorySnapshotHeader:
        extensions = parse_canonical_json(row["snapshot_extensions_json"])
        if not isinstance(extensions, dict):
            raise PersistenceValidationError()
        return HistorySnapshotHeader(
            run_id=_uuid(row["run_id"]),
            run_identifier=str(row["run_identifier"]),
            operation_id=row["operation_id"],
            source=str(row["source"]),
            status=str(row["status"]),
            pinned=bool(row["pinned"]),
            display_name=str(row["display_name"]),
            note=str(row["note"]),
            original_run_name=str(row["original_run_name"]),
            started_at=parse_canonical_instant(row["started_at_utc"]),
            completed_at=parse_canonical_instant(row["completed_at_utc"]),
            created_at=parse_canonical_instant(row["created_at_utc"]),
            imported_at=(
                parse_canonical_instant(row["imported_at_utc"])
                if row["imported_at_utc"] is not None
                else None
            ),
            provider_id=str(row["provider_id"]),
            provider_display_name=str(row["provider_display_name"]),
            provider_contract_version=str(row["provider_contract_version"]),
            benchmark_symbol=str(row["benchmark_symbol"]),
            watchlist_source_id=row["watchlist_source_id"],
            watchlist_name=str(row["watchlist_name"]),
            watchlist_revision=row["watchlist_revision"],
            requested_end_date=parse_canonical_date(row["requested_end_date"]),
            actual_end_date=parse_canonical_date(row["actual_end_date"]),
            member_count=int(row["member_count"]),
            valid_member_count=int(row["valid_member_count"]),
            failed_member_count=int(row["failed_member_count"]),
            failed_member_range_count=int(row["failed_member_range_count"]),
            algorithm_version=str(row["algorithm_version"]),
            snapshot_format_version=str(row["snapshot_format_version"]),
            snapshot_extensions=extensions,
        )

    @staticmethod
    def _range_from_row(row: sqlite3.Row) -> HistoryRangeRecord:
        return HistoryRangeRecord(
            _uuid(row["run_range_id"]),
            _uuid(row["run_id"]),
            int(row["ordinal"]),
            str(row["range_key"]),
            str(row["label"]),
            str(row["kind"]),
            parse_canonical_date(row["requested_start_date"]),
            parse_canonical_date(row["requested_end_date"]),
            parse_canonical_date(row["actual_start_date"]),
            parse_canonical_date(row["actual_end_date"]),
            parse_canonical_decimal(row["benchmark_start_close_text"]),
            parse_canonical_decimal(row["benchmark_end_close_text"]),
            parse_canonical_decimal(row["base_weight_text"]),
            parse_canonical_decimal(row["normalized_weight_text"]),
        )

    @staticmethod
    def _member_from_row(row: sqlite3.Row) -> HistoryMemberRecord:
        return HistoryMemberRecord(
            _uuid(row["id"]),
            _uuid(row["run_id"]),
            int(row["ordinal"]),
            row["source_membership_id"],
            row["source_security_id"],
            row["source_binding_id"],
            str(row["canonical_symbol"]),
            str(row["market"]),
            str(row["company_name"]),
            str(row["classification_snapshot_key"]),
            row["source_classification_id"],
            str(row["participating_classification_name"]),
            str(row["participating_classification_normalized_name"]),
        )

    @staticmethod
    def _stock_from_row(row: sqlite3.Row) -> HistoryStockResultRecord:
        return HistoryStockResultRecord(
            _uuid(row["id"]),
            _uuid(row["run_id"]),
            _uuid(row["run_member_id"]),
            _uuid(row["run_range_id"]),
            parse_canonical_decimal(row["stock_start_close_text"]),
            parse_canonical_decimal(row["stock_end_close_text"]),
            parse_canonical_decimal(row["benchmark_start_close_text"]),
            parse_canonical_decimal(row["benchmark_end_close_text"]),
            parse_canonical_decimal(row["stock_return_text"]),
            parse_canonical_decimal(row["benchmark_return_text"]),
            parse_canonical_decimal(row["rs_percentage_points_text"]),
        )

    @staticmethod
    def _period_from_row(
        row: sqlite3.Row,
    ) -> HistoryClassificationPeriodRecord:
        top = parse_canonical_json(row["top_members_json"])
        bottom = parse_canonical_json(row["bottom_members_json"])
        if not isinstance(top, list) or not isinstance(bottom, list):
            raise PersistenceValidationError()
        return HistoryClassificationPeriodRecord(
            _uuid(row["id"]),
            _uuid(row["run_id"]),
            _uuid(row["run_range_id"]),
            str(row["classification_snapshot_key"]),
            str(row["classification_name"]),
            int(row["total_member_count"]),
            int(row["valid_member_count"]),
            parse_canonical_decimal(row["coverage_text"]),
            _parse_decimal_or_none(row["mean_rs_pp_text"]),
            _parse_decimal_or_none(row["median_rs_pp_text"]),
            int(row["positive_member_count"]),
            _parse_decimal_or_none(row["strong_breadth_text"]),
            tuple(item for item in top if isinstance(item, Mapping)),
            tuple(item for item in bottom if isinstance(item, Mapping)),
            str(row["eligibility"]),
            row["eligibility_reason"],
            _parse_decimal_or_none(row["median_percentile_text"]),
            _parse_decimal_or_none(row["breadth_percentile_text"]),
            _parse_decimal_or_none(row["period_score_text"]),
            row["score_unavailable_reason"],
        )

    @staticmethod
    def _classification_from_row(
        row: sqlite3.Row,
    ) -> HistoryClassificationRecord:
        return HistoryClassificationRecord(
            _uuid(row["id"]),
            _uuid(row["run_id"]),
            str(row["classification_snapshot_key"]),
            str(row["classification_name"]),
            _parse_decimal_or_none(row["composite_score_text"]),
            str(row["multi_period_status"]),
            row["reason"],
        )

    @staticmethod
    def _failure_from_row(row: sqlite3.Row) -> HistoryFailureRecord:
        return HistoryFailureRecord(
            _uuid(row["id"]),
            _uuid(row["run_id"]),
            _uuid(row["run_member_id"])
            if row["run_member_id"] is not None
            else None,
            _uuid(row["run_range_id"])
            if row["run_range_id"] is not None
            else None,
            str(row["scope"]),
            row["canonical_symbol"],
            str(row["stage"]),
            str(row["error_code"]),
            str(row["reason"]),
            bool(row["fatal"]),
            int(row["ordinal"]),
        )
