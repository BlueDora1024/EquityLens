from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.core.securities.models import (
    ProviderProfile,
    ValidatedClassification,
    ValidatedImportBatch,
    ValidatedSecurityImport,
)
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.repositories import (
    AIReceiptBindingRepository,
    ClassificationRepository,
    SecurityRepository,
)
from stock_toolbox.infrastructure.persistence.security_import_store import (
    PersistentSecurityImportStore,
)
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


def uid(number: int) -> str:
    return f"30000000-0000-4000-8000-{number:012d}"


def test_application_import_batch_maps_to_complete_persistence_graph(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    MigrationRunner(database, app_version="0.1.0", now=lambda: NOW).bootstrap()
    factory = SQLiteConnectionFactory(database)
    classification = ValidatedClassification(
        uid(3),
        uid(4),
        "AI Data Center",
        "ai data center",
        Decimal("0.95"),
    )
    item = ValidatedSecurityImport(
        id=uid(1),
        receipt_id=uid(2),
        profile=ProviderProfile(
            symbol="IREN.US",
            name="IREN",
            market="US",
            exchange="NASDAQ",
            currency="USD",
            listing_country="US",
            description="Data center operator",
            asset_hints=(),
            business_profile={"segments": ["Data Centers"]},
            source_updated_at=NOW,
        ),
        asset_type="COMMON_STOCK",
        eligibility_source="AI",
        classifications=(classification,),
    )
    registry = OperationRegistry(clock=lambda: NOW)
    registry.reserve("op-1", "key", "security_import")
    context = registry.begin_reserved("op-1")
    assert context is not None

    committed = PersistentSecurityImportStore(factory).commit(
        ValidatedImportBatch((item,), NOW, "virtual"),
        operation_control=context.operation_control,
    )

    assert committed
    with SQLiteUnitOfWork(factory) as uow:
        assert SecurityRepository(uow.connection).get(uid(1)) is not None
        assert ClassificationRepository(uow.connection).get(uid(3)) is not None
        receipt = AIReceiptBindingRepository(uow.connection).get_by_application_key(
            (
                "business_classification",
                "IREN.US",
                "import:IREN.US",
                "business-classification-v3",
                "ai-classification-v1",
                "global-ai-config",
            )
        )
        assert receipt is not None
