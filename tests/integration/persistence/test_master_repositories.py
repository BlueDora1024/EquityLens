from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import (
    ConcurrentModificationError,
    PersistenceConflictError,
    PersistenceValidationError,
)
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.records import (
    AIReceiptRecord,
    ClassificationRecord,
    SecurityClassificationRecord,
    SecurityRecord,
    WatchlistMembershipRecord,
    WatchlistRecord,
)
from stock_toolbox.infrastructure.persistence.repositories import (
    AIReceiptBindingRepository,
    ClassificationRepository,
    SecurityRepository,
    WatchlistRepository,
)
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


def uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def factory(tmp_path: Path) -> SQLiteConnectionFactory:
    database = tmp_path / "db.sqlite3"
    MigrationRunner(
        database,
        app_version="0.1.0",
        now=lambda: NOW,
    ).bootstrap()
    return SQLiteConnectionFactory(database)


def security(number: int = 1, symbol: str = "IREN.US") -> SecurityRecord:
    return SecurityRecord(
        id=uid(number),
        canonical_symbol=symbol,
        market="US",
        display_name="IREN Limited",
        asset_type="COMMON_STOCK",
        eligibility_source="PROVIDER",
        profile_provider_id="longbridge",
        exchange="NASDAQ",
        currency="USD",
        listing_country="US",
        description="Data center operator",
        business_profile={"segments": ["Data Center"]},
        source_updated_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        revision=0,
    )


def classification(number: int = 10, name: str = "AI Data Center") -> ClassificationRecord:
    return ClassificationRecord(
        id=uid(number),
        display_name=name,
        normalized_name=name.casefold(),
        aliases=("AI Infrastructure",),
        origin="HUMAN",
        created_at=NOW,
        updated_at=NOW,
        revision=0,
    )


def test_security_and_classification_roundtrip_and_optimistic_revision(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    with SQLiteUnitOfWork(connection_factory) as uow:
        securities = SecurityRepository(uow.connection)
        classifications = ClassificationRepository(uow.connection)
        securities.add(security())
        classifications.add(classification())
        uow.commit()

    with SQLiteUnitOfWork(connection_factory) as uow:
        securities = SecurityRepository(uow.connection)
        stored = securities.get_by_symbol("IREN.US")
        assert stored == security()
        updated = replace(security(), display_name="IREN", revision=1)
        securities.update(updated, expected_revision=0)
        with pytest.raises(ConcurrentModificationError):
            securities.update(updated, expected_revision=0)
        uow.commit()

    with SQLiteUnitOfWork(connection_factory) as uow:
        assert SecurityRepository(uow.connection).get(uid(1)).display_name == "IREN"  # type: ignore[union-attr]


def test_duplicate_symbol_is_stable_conflict_and_invalid_asset_is_validation(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    with SQLiteUnitOfWork(connection_factory) as uow:
        repository = SecurityRepository(uow.connection)
        repository.add(security())
        with pytest.raises(PersistenceConflictError):
            repository.add(security(2))

    with SQLiteUnitOfWork(connection_factory) as uow:
        invalid = replace(security(), asset_type="ETF")
        with pytest.raises(PersistenceValidationError):
            SecurityRepository(uow.connection).add(invalid)


def test_ai_receipt_and_binding_are_atomic_and_preserve_provenance(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    with SQLiteUnitOfWork(connection_factory) as uow:
        SecurityRepository(uow.connection).add(security())
        ClassificationRepository(uow.connection).add(classification())
        receipt = AIReceiptRecord(
            receipt_id=uid(20),
            task="business_classification",
            canonical_symbol="IREN.US",
            security_id=uid(1),
            input_fingerprint="input-sha",
            prompt_version="prompt-v1",
            schema_version="ai-v1",
            model_config_id="deepseek-flash-v1",
            result_fingerprint="result-sha",
            status="APPLIED",
            outcome_summary={"applied": 1},
            created_at=NOW,
        )
        binding = SecurityClassificationRecord(
            id=uid(30),
            security_id=uid(1),
            classification_id=uid(10),
            source="AI",
            ai_receipt_id=uid(20),
            confidence=Decimal("0.92"),
            evidence=("company operates data centers",),
            evidence_refs=("description",),
            source_request_id="request-1",
            human_protected=False,
            created_at=NOW,
            updated_at=NOW,
        )
        repository = AIReceiptBindingRepository(uow.connection)
        repository.insert_receipt_with_bindings(receipt, (binding,))
        uow.commit()

    with SQLiteUnitOfWork(connection_factory) as uow:
        repository = AIReceiptBindingRepository(uow.connection)
        assert repository.get_by_application_key(receipt.application_key) == receipt
        assert repository.list_bindings(uid(1)) == (binding,)


def test_human_binding_cannot_carry_ai_provenance(tmp_path: Path) -> None:
    connection_factory = factory(tmp_path)
    with SQLiteUnitOfWork(connection_factory) as uow:
        SecurityRepository(uow.connection).add(security())
        ClassificationRepository(uow.connection).add(classification())
        invalid = SecurityClassificationRecord(
            id=uid(30),
            security_id=uid(1),
            classification_id=uid(10),
            source="HUMAN",
            ai_receipt_id=uid(20),
            confidence=None,
            evidence=(),
            evidence_refs=(),
            source_request_id=None,
            human_protected=True,
            created_at=NOW,
            updated_at=NOW,
        )
        with pytest.raises(PersistenceValidationError):
            AIReceiptBindingRepository(uow.connection).add_human_binding(invalid)


def test_watchlist_membership_requires_binding_for_same_security_and_revisions(
    tmp_path: Path,
) -> None:
    connection_factory = factory(tmp_path)
    with SQLiteUnitOfWork(connection_factory) as uow:
        securities = SecurityRepository(uow.connection)
        classifications = ClassificationRepository(uow.connection)
        securities.add(security())
        securities.add(security(2, "NVDA.US"))
        classifications.add(classification())
        bindings = AIReceiptBindingRepository(uow.connection)
        human = SecurityClassificationRecord(
            id=uid(30),
            security_id=uid(1),
            classification_id=uid(10),
            source="HUMAN",
            ai_receipt_id=None,
            confidence=None,
            evidence=(),
            evidence_refs=(),
            source_request_id=None,
            human_protected=True,
            created_at=NOW,
            updated_at=NOW,
        )
        bindings.add_human_binding(human)
        watchlists = WatchlistRepository(uow.connection)
        watchlists.add(WatchlistRecord(uid(40), "Tech", "tech", NOW, NOW, 0))
        watchlists.replace_memberships(
            uid(40),
            expected_revision=0,
            memberships=(
                WatchlistMembershipRecord(
                    uid(50), uid(40), uid(1), uid(30), NOW, NOW
                ),
            ),
        )
        with pytest.raises(ConcurrentModificationError):
            watchlists.replace_memberships(
                uid(40),
                expected_revision=0,
                memberships=(),
            )
        uow.commit()

    with SQLiteUnitOfWork(connection_factory) as uow:
        watchlists = WatchlistRepository(uow.connection)
        assert len(watchlists.get_for_update(uid(40)).memberships) == 1  # type: ignore[union-attr]

    with (
        SQLiteUnitOfWork(connection_factory) as uow,
        pytest.raises(PersistenceConflictError),
    ):
        WatchlistRepository(uow.connection).replace_memberships(
            uid(40),
            expected_revision=1,
            memberships=(
                WatchlistMembershipRecord(
                    uid(51), uid(40), uid(2), uid(30), NOW, NOW
                ),
            ),
        )
