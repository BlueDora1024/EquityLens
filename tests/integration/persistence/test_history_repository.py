from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
from stock_toolbox.infrastructure.persistence.history_repository import HistoryRepository
from stock_toolbox.infrastructure.persistence.history_writer import (
    CompletedRunSaveStatus,
    SaveCompletedRun,
)
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork

BASE_TIME = datetime(2026, 7, 25, 12, tzinfo=UTC)


def uid(number: int) -> str:
    return f"10000000-0000-4000-8000-{number:012d}"


def factory(tmp_path: Path) -> SQLiteConnectionFactory:
    database = tmp_path / "db.sqlite3"
    MigrationRunner(
        database,
        app_version="0.1.0",
        now=lambda: BASE_TIME,
    ).bootstrap()
    return SQLiteConnectionFactory(database)


def snapshot(
    number: int,
    *,
    source: str = "AUTO",
    pinned: bool = False,
    created_at: datetime | None = None,
) -> HistorySnapshotRecord:
    run_id = uid(number * 10 + 1)
    range_id = uid(number * 10 + 2)
    member_id = uid(number * 10 + 3)
    imported = source == "IMPORTED"
    timestamp = created_at or BASE_TIME + timedelta(microseconds=number)
    header = HistorySnapshotHeader(
        run_id=run_id,
        run_identifier=f"run-{number}",
        operation_id=None if imported else f"operation-{number}",
        source=source,
        status="READY",
        pinned=pinned,
        display_name=f"Run {number}",
        note="",
        original_run_name=f"Original {number}",
        started_at=timestamp - timedelta(seconds=1),
        completed_at=timestamp,
        created_at=timestamp,
        imported_at=timestamp if imported else None,
        provider_id="longbridge",
        provider_display_name="Longbridge",
        provider_contract_version="provider-v1",
        benchmark_symbol="SPY.US",
        watchlist_source_id="watchlist-source",
        watchlist_name="Tech",
        watchlist_revision=3,
        requested_end_date=date(2026, 7, 24),
        actual_end_date=date(2026, 7, 23),
        member_count=1,
        valid_member_count=1,
        failed_member_count=0,
        failed_member_range_count=0,
        algorithm_version="rs-algorithm-v1",
        snapshot_format_version="rs-radar-history-v1",
        snapshot_extensions={},
    )
    range_record = HistoryRangeRecord(
        run_range_id=range_id,
        run_id=run_id,
        ordinal=0,
        range_key="3M",
        label="近 3 个月",
        kind="PRESET_3M",
        requested_start_date=date(2026, 4, 24),
        requested_end_date=date(2026, 7, 24),
        actual_start_date=date(2026, 4, 24),
        actual_end_date=date(2026, 7, 23),
        benchmark_start_close=Decimal(100),
        benchmark_end_close=Decimal(110),
        base_weight=Decimal("1.00"),
        normalized_weight=Decimal(1),
    )
    member = HistoryMemberRecord(
        id=member_id,
        run_id=run_id,
        ordinal=0,
        source_membership_id="membership-source",
        source_security_id="security-source",
        source_binding_id="binding-source",
        canonical_symbol="IREN.US",
        market="US",
        company_name="IREN",
        classification_snapshot_key="AI_DATA_CENTER",
        source_classification_id="classification-source",
        participating_classification_name="AI Data Center",
        participating_classification_normalized_name="ai data center",
    )
    stock = HistoryStockResultRecord(
        id=uid(number * 10 + 4),
        run_id=run_id,
        run_member_id=member_id,
        run_range_id=range_id,
        stock_start_close=Decimal(50),
        stock_end_close=Decimal(65),
        benchmark_start_close=Decimal(100),
        benchmark_end_close=Decimal(110),
        stock_return=Decimal("0.3"),
        benchmark_return=Decimal("0.1"),
        rs_percentage_points=Decimal(20),
    )
    period = HistoryClassificationPeriodRecord(
        id=uid(number * 10 + 5),
        run_id=run_id,
        run_range_id=range_id,
        classification_snapshot_key="AI_DATA_CENTER",
        classification_name="AI Data Center",
        total_member_count=1,
        valid_member_count=1,
        coverage=Decimal(1),
        mean_rs=Decimal(20),
        median_rs=Decimal(20),
        positive_member_count=1,
        strong_breadth=Decimal(1),
        top_members=(
            {
                "run_member_id": member_id,
                "symbol": "IREN.US",
                "rs_percentage_points": "20",
            },
        ),
        bottom_members=(
            {
                "run_member_id": member_id,
                "symbol": "IREN.US",
                "rs_percentage_points": "20",
            },
        ),
        eligibility="INSUFFICIENT_SAMPLE",
        eligibility_reason="VALID_MEMBER_COUNT_LT_3",
        median_percentile=None,
        breadth_percentile=None,
        period_score=None,
        score_unavailable_reason=None,
    )
    overall = HistoryClassificationRecord(
        id=uid(number * 10 + 6),
        run_id=run_id,
        classification_snapshot_key="AI_DATA_CENTER",
        classification_name="AI Data Center",
        composite_score=None,
        multi_period_status="NOT_APPLICABLE",
        reason="RANGE_SCORE_UNAVAILABLE:3M:VALID_MEMBER_COUNT_LT_3",
    )
    return HistorySnapshotRecord(
        header=header,
        ranges=(range_record,),
        members=(member,),
        stock_results=(stock,),
        classification_period_results=(period,),
        classification_results=(overall,),
        failures=(),
    )


def test_complete_snapshot_roundtrips_every_frozen_and_management_field(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    expected = snapshot(1)
    with SQLiteUnitOfWork(connection_factory) as uow:
        HistoryRepository(uow.connection).insert_snapshot(expected)
        uow.commit()

    with SQLiteUnitOfWork(connection_factory) as uow:
        actual = HistoryRepository(uow.connection).get_snapshot(
            expected.header.run_id
        )

    assert actual == expected


def test_retention_keeps_latest_ten_unpinned_auto_only(tmp_path: Path) -> None:
    connection_factory = factory(tmp_path)
    inserted = [snapshot(number) for number in range(1, 12)]
    pinned_auto = snapshot(20, pinned=True)
    imported_unpinned = snapshot(21, source="IMPORTED", pinned=False)
    with SQLiteUnitOfWork(connection_factory) as uow:
        repository = HistoryRepository(uow.connection)
        for item in (*inserted, pinned_auto, imported_unpinned):
            repository.insert_snapshot(item)
        evicted = repository.evict_excess_unpinned_auto(keep=10)
        uow.commit()

    assert evicted == (inserted[0].header.run_id,)
    with SQLiteUnitOfWork(connection_factory) as uow:
        repository = HistoryRepository(uow.connection)
        assert repository.get_snapshot(inserted[0].header.run_id) is None
        assert repository.get_snapshot(pinned_auto.header.run_id) is not None
        assert repository.get_snapshot(imported_unpinned.header.run_id) is not None


def test_history_management_update_never_changes_original_run_name(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    expected = snapshot(1)
    with SQLiteUnitOfWork(connection_factory) as uow:
        repository = HistoryRepository(uow.connection)
        repository.insert_snapshot(expected)
        repository.update_management(
            expected.header.run_id,
            display_name="My Label",
            note="reviewed",
            pinned=True,
        )
        uow.commit()

    with SQLiteUnitOfWork(connection_factory) as uow:
        actual = HistoryRepository(uow.connection).get_snapshot(
            expected.header.run_id
        )

    assert actual is not None
    assert actual.header.display_name == "My Label"
    assert actual.header.note == "reviewed"
    assert actual.header.pinned is True
    assert actual.header.original_run_name == expected.header.original_run_name
    assert actual == replace(
        expected,
        header=replace(
            expected.header,
            display_name="My Label",
            note="reviewed",
            pinned=True,
        ),
    )


def partial_snapshot(number: int) -> HistorySnapshotRecord:
    base = snapshot(number)
    failed_member = replace(
        base.members[0],
        id=uid(number * 10 + 7),
        ordinal=1,
        canonical_symbol="MISS.US",
        company_name="Missing",
    )
    failure = HistoryFailureRecord(
        id=uid(number * 10 + 8),
        run_id=base.header.run_id,
        run_member_id=failed_member.id,
        run_range_id=None,
        scope="MEMBER",
        canonical_symbol="MISS.US",
        stage="FETCH",
        error_code="PROVIDER_TIMEOUT",
        reason="Provider timeout",
        fatal=False,
        ordinal=0,
    )
    period = replace(
        base.classification_period_results[0],
        total_member_count=2,
        coverage=Decimal("0.5"),
    )
    return replace(
        base,
        header=replace(
            base.header,
            status="PARTIAL",
            member_count=2,
            valid_member_count=1,
            failed_member_count=1,
        ),
        members=(*base.members, failed_member),
        classification_period_results=(period,),
        failures=(failure,),
    )


def test_partial_member_failure_roundtrips_without_fake_range_failures(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    expected = partial_snapshot(1)
    with SQLiteUnitOfWork(connection_factory) as uow:
        HistoryRepository(uow.connection).insert_snapshot(expected)
        uow.commit()

    with SQLiteUnitOfWork(connection_factory) as uow:
        actual = HistoryRepository(uow.connection).get_snapshot(
            expected.header.run_id
        )

    assert actual == expected
    assert actual is not None
    assert actual.header.failed_member_count == 1
    assert actual.header.failed_member_range_count == 0
    assert actual.failures[0].scope == "MEMBER"
    assert actual.failures[0].run_range_id is None


class Gate:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls = 0

    def try_enter_committing(self) -> bool:
        self.calls += 1
        return self.result


def test_save_completed_run_calls_gate_after_sql_and_rolls_back_when_cancel_wins(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    gate = Gate(False)

    result = SaveCompletedRun(connection_factory).save(snapshot(1), gate)

    assert result.status is CompletedRunSaveStatus.CANCELED_BEFORE_COMMIT
    assert gate.calls == 1
    with SQLiteUnitOfWork(connection_factory) as uow:
        assert HistoryRepository(uow.connection).get_snapshot(uid(11)) is None


def test_save_completed_run_commits_and_retains_in_the_same_transaction(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    writer = SaveCompletedRun(connection_factory)
    for number in range(1, 11):
        assert writer.save(snapshot(number), Gate(True)).status is (
            CompletedRunSaveStatus.SAVED
        )
    same_time = BASE_TIME + timedelta(seconds=1)
    result = writer.save(snapshot(11, created_at=same_time), Gate(True))

    assert result.status is CompletedRunSaveStatus.SAVED
    assert result.evicted_run_ids == (uid(11),)
    with SQLiteUnitOfWork(connection_factory) as uow:
        repository = HistoryRepository(uow.connection)
        assert repository.get_snapshot(uid(11)) is None
        assert repository.get_snapshot(uid(111)) is not None
