from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from stock_toolbox.analyses.rs_strength.application.models import CompletedRun, RunRequest
from stock_toolbox.analyses.rs_strength.domain.engine import calculate_run
from stock_toolbox.analyses.rs_strength.domain.models import (
    ALGORITHM_VERSION,
    CalculationMember,
    PricePoint,
    PriceSeries,
    RequestedRange,
    RunCalculationInput,
)
from stock_toolbox.core.master_data.models import (
    WatchlistDTO,
    WatchlistMembershipDTO,
)
from stock_toolbox.core.operations.failure_policy import AnalysisReliability
from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.infrastructure.persistence.completed_run_store import (
    PersistentCompletedRunStore,
)
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.history_repository import HistoryRepository
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


def uid(number: int) -> str:
    return f"60000000-0000-4000-8000-{number:012d}"


def test_completed_application_run_is_frozen_and_saved_atomically(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    MigrationRunner(database, app_version="0.1.0", now=lambda: NOW).bootstrap()
    factory = SQLiteConnectionFactory(database)
    output = calculate_run(
        RunCalculationInput(
            ALGORITHM_VERSION,
            "SPY.US",
            (
                RequestedRange(
                    uid(2),
                    "3M",
                    "近 3 个月",
                    "PRESET_3M",
                    0,
                    date(2026, 4, 24),
                    date(2026, 7, 24),
                ),
            ),
            (
                CalculationMember(
                    uid(3),
                    0,
                    "IREN.US",
                    uid(7),
                    "AI Data Center",
                    "ai data center",
                ),
            ),
            {
                "SPY.US": PriceSeries(
                    "SPY.US",
                    (
                        PricePoint(date(2026, 4, 24), Decimal(100)),
                        PricePoint(date(2026, 7, 24), Decimal(110)),
                    ),
                ),
                "IREN.US": PriceSeries(
                    "IREN.US",
                    (
                        PricePoint(date(2026, 4, 24), Decimal(50)),
                        PricePoint(date(2026, 7, 24), Decimal(65)),
                    ),
                ),
            },
            (),
        )
    )
    assert not hasattr(output, "code")
    watchlist = WatchlistDTO(
        uid(4),
        "Tech",
        1,
        (
            WatchlistMembershipDTO(
                uid(5),
                uid(6),
                "IREN.US",
                "IREN",
                uid(8),
                uid(7),
                "AI Data Center",
            ),
        ),
    )
    completed = CompletedRun(
        uid(1),
        "op-1",
        NOW,
        NOW,
        RunRequest(uid(4), "SPY.US", date(2026, 7, 24), ("3M",), None),
        watchlist,
        "virtual",
        "Virtual",
        (uid(3),),
        output,  # type: ignore[arg-type]
        AnalysisReliability(
            succeeded_tasks=1,
            failed_tasks=0,
            unexecuted_tasks=0,
            success_rate=Decimal(1),
            circuit_opened=False,
            primary_failure_code=None,
        ),
    )
    registry = OperationRegistry(clock=lambda: NOW)
    registry.reserve("op-1", "key", "run")
    context = registry.begin_reserved("op-1")
    assert context is not None
    ids = iter(uid(number) for number in range(20, 100))

    assert PersistentCompletedRunStore(
        factory,
        new_id=lambda: next(ids),
    ).save(completed, operation_control=context.operation_control)

    with SQLiteUnitOfWork(factory) as uow:
        snapshot = HistoryRepository(uow.connection).get_snapshot(uid(1))
    assert snapshot is not None
    assert snapshot.header.status == "READY"
    assert snapshot.header.watchlist_name == "Tech"
    assert snapshot.members[0].participating_classification_name == "AI Data Center"
    assert snapshot.stock_results[0].rs_percentage_points == Decimal(20)
    assert snapshot.header.snapshot_extensions["reliability"] == {
        "succeeded_tasks": 1,
        "failed_tasks": 0,
        "unexecuted_tasks": 0,
        "success_rate": "1",
        "circuit_opened": False,
        "primary_failure_code": None,
    }
