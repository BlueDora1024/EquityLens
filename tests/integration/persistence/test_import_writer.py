from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.import_writer import (
    ImportCommitStatus,
    ReceiptBindingPlan,
    SecurityImportWritePort,
    ValidatedSecurityImportBatch,
)
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.records import (
    AIReceiptRecord,
    SecurityClassificationRecord,
)
from stock_toolbox.infrastructure.persistence.repositories import SecurityRepository
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork
from tests.integration.persistence.test_master_repositories import (
    classification,
    security,
    uid,
)

NOW = datetime(2026, 7, 25, tzinfo=UTC)


def factory(tmp_path: Path) -> SQLiteConnectionFactory:
    database = tmp_path / "db.sqlite3"
    MigrationRunner(
        database,
        app_version="0.1.0",
        now=lambda: NOW,
    ).bootstrap()
    return SQLiteConnectionFactory(database)


class Gate:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls = 0

    def try_enter_committing(self) -> bool:
        self.calls += 1
        return self.result


def test_batch_cancel_before_commit_rolls_back_all_new_master_data(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    batch = ValidatedSecurityImportBatch(
        securities=(security(),),
        classifications=(classification(),),
        receipt_plans=(),
    )
    gate = Gate(False)

    result = SecurityImportWritePort(connection_factory).commit_batch(batch, gate)

    assert result.status is ImportCommitStatus.CANCELED_BEFORE_COMMIT
    assert gate.calls == 1
    with SQLiteUnitOfWork(connection_factory) as uow:
        assert SecurityRepository(uow.connection).get_by_symbol("IREN.US") is None


def test_existing_security_is_skipped_without_overwrite(tmp_path: Path) -> None:
    connection_factory = factory(tmp_path)
    with SQLiteUnitOfWork(connection_factory) as uow:
        SecurityRepository(uow.connection).add(security())
        uow.commit()
    changed = replace(security(), display_name="Should Not Overwrite")
    batch = ValidatedSecurityImportBatch((changed,), (), ())

    result = SecurityImportWritePort(connection_factory).commit_batch(
        batch,
        Gate(True),
    )

    assert result.status is ImportCommitStatus.COMMITTED
    assert result.inserted_security_ids == ()
    assert result.skipped_symbols == ("IREN.US",)
    with SQLiteUnitOfWork(connection_factory) as uow:
        stored = SecurityRepository(uow.connection).get_by_symbol("IREN.US")
        assert stored is not None
        assert stored.display_name == "IREN Limited"


def test_any_invalid_receipt_binding_rolls_back_whole_batch(tmp_path: Path) -> None:
    connection_factory = factory(tmp_path)
    receipt = AIReceiptRecord(
        uid(20),
        "business_classification",
        "IREN.US",
        uid(1),
        "input",
        "prompt-v1",
        "ai-v1",
        "model-v1",
        "result",
        "APPLIED",
        {"applied": 1},
        NOW,
    )
    invalid_binding = SecurityClassificationRecord(
        uid(30),
        uid(999),
        uid(10),
        "AI",
        uid(20),
        Decimal("0.9"),
        (),
        (),
        "request",
        False,
        NOW,
        NOW,
    )
    batch = ValidatedSecurityImportBatch(
        (security(),),
        (classification(),),
        (ReceiptBindingPlan(receipt, (invalid_binding,)),),
    )

    result = SecurityImportWritePort(connection_factory).commit_batch(
        batch,
        Gate(True),
    )

    assert result.status is ImportCommitStatus.FAILED
    with SQLiteUnitOfWork(connection_factory) as uow:
        assert SecurityRepository(uow.connection).get_by_symbol("IREN.US") is None
