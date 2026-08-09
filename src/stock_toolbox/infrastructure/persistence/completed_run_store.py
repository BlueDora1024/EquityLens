"""Freeze application run output into the immutable history schema."""

from __future__ import annotations

from collections.abc import Callable

from stock_toolbox.analyses.rs_strength.application.models import CompletedRun
from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
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
from stock_toolbox.infrastructure.persistence.history_writer import (
    CompletedRunSaveStatus,
    SaveCompletedRun,
)


class PersistentCompletedRunStore:
    def __init__(
        self,
        factory: SQLiteConnectionFactory,
        *,
        new_id: Callable[[], str],
    ) -> None:
        self._factory = factory
        self._new_id = new_id

    def save(
        self,
        completed: CompletedRun,
        *,
        operation_control: OperationControl,
    ) -> bool:
        snapshot = self._snapshot(completed)
        result = SaveCompletedRun(self._factory).save(
            snapshot,
            operation_control,
        )
        return result.status is CompletedRunSaveStatus.SAVED

    def _snapshot(self, completed: CompletedRun) -> HistorySnapshotRecord:
        output = completed.output
        reliability = completed.reliability
        members_by_ordinal = {
            ordinal: member
            for ordinal, member in enumerate(
                completed.watchlist.memberships
            )
        }
        history_members = tuple(
            HistoryMemberRecord(
                id=completed.run_member_ids[ordinal],
                run_id=completed.run_id,
                ordinal=ordinal,
                source_membership_id=member.id,
                source_security_id=member.security_id,
                source_binding_id=member.participating_binding_id,
                canonical_symbol=member.canonical_symbol,
                market="US",
                company_name=member.company_name,
                classification_snapshot_key=(
                    member.participating_classification_id
                ),
                source_classification_id=(
                    member.participating_classification_id
                ),
                participating_classification_name=(
                    member.participating_classification_name
                ),
                participating_classification_normalized_name=(
                    member.participating_classification_name.casefold()
                ),
            )
            for ordinal, member in members_by_ordinal.items()
        )
        member_id_by_ordinal = {
            item.ordinal: item.id for item in history_members
        }
        range_id_by_key = {
            item.key: item.run_range_id for item in output.resolved_ranges
        }
        header = HistorySnapshotHeader(
            run_id=completed.run_id,
            run_identifier=(
                f"{completed.watchlist.display_name}-"
                f"{completed.completed_at:%Y%m%d-%H%M%S}"
            ),
            operation_id=completed.operation_id,
            source="AUTO",
            status=(
                "PARTIAL" if output.failure_candidates else "READY"
            ),
            pinned=False,
            display_name=(
                f"{completed.watchlist.display_name} "
                f"{completed.completed_at:%Y-%m-%d %H:%M}"
            ),
            note="",
            original_run_name=completed.watchlist.display_name,
            started_at=completed.started_at,
            completed_at=completed.completed_at,
            created_at=completed.completed_at,
            imported_at=None,
            provider_id=completed.provider_id,
            provider_display_name=completed.provider_display_name,
            provider_contract_version="provider-v1",
            benchmark_symbol=completed.request.benchmark_symbol,
            watchlist_source_id=completed.watchlist.id,
            watchlist_name=completed.watchlist.display_name,
            watchlist_revision=completed.watchlist.revision,
            requested_end_date=completed.request.requested_end_date,
            actual_end_date=max(
                item.actual_end_date for item in output.resolved_ranges
            ),
            member_count=len(completed.watchlist.memberships),
            valid_member_count=output.valid_member_count,
            failed_member_count=output.failed_member_count,
            failed_member_range_count=output.failed_member_range_count,
            algorithm_version=output.algorithm_version,
            snapshot_format_version="rs-radar-history-v1",
            snapshot_extensions={
                "rs_unit": "percentage_points",
                "source_by_symbol": dict(completed.source_by_symbol),
                "requested_date_window": (
                    [
                        completed.requested_date_window[0].isoformat(),
                        completed.requested_date_window[1].isoformat(),
                    ]
                    if completed.requested_date_window is not None
                    else None
                ),
                "actual_date_window": (
                    [
                        completed.actual_date_window[0].isoformat(),
                        completed.actual_date_window[1].isoformat(),
                    ]
                    if completed.actual_date_window is not None
                    else None
                ),
                **(
                    {
                        "reliability": {
                            "succeeded_tasks": reliability.succeeded_tasks,
                            "failed_tasks": reliability.failed_tasks,
                            "unexecuted_tasks": reliability.unexecuted_tasks,
                            "success_rate": str(reliability.success_rate),
                            "circuit_opened": reliability.circuit_opened,
                            "primary_failure_code": (
                                reliability.primary_failure_code
                            ),
                        }
                    }
                    if reliability is not None
                    else {}
                ),
            },
        )
        return HistorySnapshotRecord(
            header=header,
            ranges=tuple(
                HistoryRangeRecord(
                    item.run_range_id,
                    completed.run_id,
                    item.ordinal,
                    item.key,
                    item.label,
                    item.kind,
                    item.requested_start_date,
                    item.requested_end_date,
                    item.actual_start_date,
                    item.actual_end_date,
                    item.benchmark_start_close,
                    item.benchmark_end_close,
                    item.base_weight,
                    item.normalized_weight,
                )
                for item in output.resolved_ranges
            ),
            members=history_members,
            stock_results=tuple(
                HistoryStockResultRecord(
                    self._new_id(),
                    completed.run_id,
                    member_id_by_ordinal[item.member_ordinal],
                    item.run_range_id,
                    item.stock_start_close,
                    item.stock_end_close,
                    item.benchmark_start_close,
                    item.benchmark_end_close,
                    item.stock_return,
                    item.benchmark_return,
                    item.rs,
                )
                for item in output.stock_results
            ),
            classification_period_results=tuple(
                HistoryClassificationPeriodRecord(
                    self._new_id(),
                    completed.run_id,
                    item.run_range_id,
                    item.classification_snapshot_key,
                    item.classification_name,
                    item.total_member_count,
                    item.valid_member_count,
                    item.coverage,
                    item.mean_rs,
                    item.median_rs,
                    item.positive_count,
                    item.strong_breadth,
                    tuple(
                        {
                            "run_member_id": member_id_by_ordinal[
                                member.member_ordinal
                            ],
                            "symbol": member.symbol,
                            "rs_percentage_points": str(member.rs),
                        }
                        for member in item.top_members
                    ),
                    tuple(
                        {
                            "run_member_id": member_id_by_ordinal[
                                member.member_ordinal
                            ],
                            "symbol": member.symbol,
                            "rs_percentage_points": str(member.rs),
                        }
                        for member in item.bottom_members
                    ),
                    item.eligibility,
                    item.eligibility_reason,
                    item.median_percentile,
                    item.breadth_percentile,
                    item.period_score,
                    item.score_unavailable_reason,
                )
                for item in output.classification_period_results
            ),
            classification_results=tuple(
                HistoryClassificationRecord(
                    self._new_id(),
                    completed.run_id,
                    item.classification_snapshot_key,
                    item.classification_name,
                    item.composite_score,
                    item.status,
                    item.reason,
                )
                for item in output.classification_results
            ),
            failures=tuple(
                HistoryFailureRecord(
                    self._new_id(),
                    completed.run_id,
                    member_id_by_ordinal[item.member_ordinal],
                    (
                        range_id_by_key[item.range_key]
                        if item.range_key is not None
                        else None
                    ),
                    item.scope,
                    item.symbol,
                    item.stage,
                    item.code,
                    self._failure_reason(
                        item.code,
                        item.reason_parameters,
                    ),
                    False,
                    item.stable_ordinal,
                )
                for item in output.failure_candidates
            ),
        )

    @staticmethod
    def _failure_reason(
        code: str,
        parameters: tuple[tuple[str, str], ...],
    ) -> str:
        details = ", ".join(f"{key}={value}" for key, value in parameters)
        return code if not details else f"{code}: {details}"
