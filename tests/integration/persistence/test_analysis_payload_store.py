from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
    ExtremeDeviationRun,
)
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
    TurningPointRun,
)
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.operations.failure_policy import AnalysisReliability
from stock_toolbox.infrastructure.persistence.analysis_payload_store import (
    AnalysisPayloadStore,
)
from stock_toolbox.infrastructure.persistence.connections import (
    SQLiteConnectionFactory,
)
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner

NOW = datetime(2026, 7, 30, 12, tzinfo=UTC)
RELIABILITY = AnalysisReliability(
    succeeded_tasks=80,
    failed_tasks=0,
    unexecuted_tasks=20,
    success_rate=Decimal("0.8"),
    circuit_opened=True,
    primary_failure_code="circuit_open",
)


def store(tmp_path: Path) -> AnalysisPayloadStore:
    database = tmp_path / "payloads.sqlite3"
    MigrationRunner(
        database,
        app_version="0.9.4",
        now=lambda: NOW,
    ).bootstrap()
    return AnalysisPayloadStore(SQLiteConnectionFactory(database))


def test_turning_point_reliability_is_frozen_as_stable_json_scalars(
    tmp_path: Path,
) -> None:
    history = store(tmp_path)
    run = TurningPointRun(
        "turning-run",
        "turning-op",
        NOW,
        NOW,
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 29),
        ),
        "Tech",
        1,
        "virtual",
        "Virtual",
        (),
        reliability=RELIABILITY,
    )

    history.save_turning_point(run)

    assert history.get_payload("turning-run", "turning_point")[
        "reliability"
    ] == {
        "succeeded_tasks": 80,
        "failed_tasks": 0,
        "unexecuted_tasks": 20,
        "success_rate": "0.8",
        "circuit_opened": True,
        "primary_failure_code": "circuit_open",
    }


def test_extreme_reliability_is_frozen_as_stable_json_scalars(
    tmp_path: Path,
) -> None:
    history = store(tmp_path)
    run = ExtremeDeviationRun(
        "extreme-run",
        "extreme-op",
        NOW,
        NOW,
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 29),
        ),
        "Tech",
        1,
        (),
        "virtual",
        "Virtual",
        0,
        80,
        (),
        reliability=RELIABILITY,
    )

    history.save_extreme_deviation(run)

    assert history.get_payload("extreme-run", "extreme_deviation")[
        "reliability"
    ] == {
        "succeeded_tasks": 80,
        "failed_tasks": 0,
        "unexecuted_tasks": 20,
        "success_rate": "0.8",
        "circuit_opened": True,
        "primary_failure_code": "circuit_open",
    }


def test_pre_094_payload_without_reliability_still_loads(
    tmp_path: Path,
) -> None:
    history = store(tmp_path)
    legacy_payload = {
        "run_id": "legacy-run",
        "results": [],
        "algorithm_version": "turning-point-v2",
    }
    history._save(
        "legacy-run",
        "turning_point",
        "1.0.0",
        "legacy-op",
        "READY",
        "virtual",
        "Legacy",
        NOW,
        legacy_payload,
    )

    loaded = history.get_payload("legacy-run", "turning_point")

    assert loaded == legacy_payload
    assert "reliability" not in loaded


def test_payload_transaction_failure_leaves_no_half_record(
    tmp_path: Path,
) -> None:
    history = store(tmp_path)
    for index in range(10):
        history._save(
            f"old-{index}",
            "turning_point",
            "2.0.0",
            f"old-op-{index}",
            "READY",
            "virtual",
            f"Old {index}",
            NOW,
            {"run_id": f"old-{index}", "results": []},
        )
    connection = history._factory.open_writer()
    try:
        connection.execute(
            "CREATE TRIGGER reject_payload_eviction "
            "BEFORE DELETE ON analysis_payload_runs "
            "BEGIN SELECT RAISE(ABORT, 'retention failed'); END"
        )
    finally:
        connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="retention failed"):
        history._save(
            "new-run",
            "turning_point",
            "2.0.0",
            "new-op",
            "READY",
            "virtual",
            "New",
            NOW,
            {"run_id": "new-run", "results": []},
        )

    assert len(history.list("turning_point", limit=20)) == 10
    with pytest.raises(KeyError):
        history.get_payload("new-run", "turning_point")
