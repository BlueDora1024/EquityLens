from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from stock_toolbox.core.securities.models import ProviderProfile
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import PersistenceConflictError
from stock_toolbox.infrastructure.persistence.master_data_store import SQLiteMasterDataStore
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.records import SecurityRecord
from stock_toolbox.infrastructure.persistence.repositories import SecurityRepository
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


def uid(number: int) -> str:
    return f"40000000-0000-4000-8000-{number:012d}"


def store(tmp_path: Path) -> tuple[SQLiteMasterDataStore, SQLiteConnectionFactory]:
    database = tmp_path / "db.sqlite3"
    MigrationRunner(database, app_version="0.1.0", now=lambda: NOW).bootstrap()
    factory = SQLiteConnectionFactory(database)
    ids = iter(uid(number) for number in range(1, 100))
    return SQLiteMasterDataStore(factory, clock=lambda: NOW, new_id=lambda: next(ids)), factory


def seed_security(factory: SQLiteConnectionFactory) -> str:
    record = SecurityRecord(
        uid(90),
        "IREN.US",
        "US",
        "IREN",
        "COMMON_STOCK",
        "PROVIDER",
        "virtual",
        "NASDAQ",
        "USD",
        "US",
        "Data center operator",
        {},
        NOW,
        NOW,
        NOW,
        0,
    )
    with SQLiteUnitOfWork(factory) as uow:
        SecurityRepository(uow.connection).add(record)
        uow.commit()
    return record.id


def test_global_classifications_bindings_and_watchlists_are_shared(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    ai = service.create_classification("AI Data Center")
    mining = service.create_classification("Bitcoin Mining")

    detail = service.set_security_classifications(
        security_id,
        (ai.id, mining.id),
    )
    watchlist = service.create_watchlist("Growth")
    updated = service.add_watchlist_members(
        watchlist.id,
        ((security_id, detail.bindings[0].id),),
    )

    assert tuple(item.display_name for item in service.list_classifications()) == (
        "AI Data Center",
        "Bitcoin Mining",
    )
    assert tuple(item.canonical_symbol for item in service.list_securities()) == (
        "IREN.US",
    )
    assert len(updated.memberships) == 1
    assert updated.memberships[0].participating_classification_name == "AI Data Center"


def test_one_security_can_join_multiple_watchlists_with_different_binding(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    first = service.create_classification("AI Data Center")
    second = service.create_classification("Bitcoin Mining")
    detail = service.set_security_classifications(security_id, (first.id, second.id))
    pool_a = service.create_watchlist("A")
    pool_b = service.create_watchlist("B")

    a = service.add_watchlist_members(pool_a.id, ((security_id, detail.bindings[0].id),))
    b = service.add_watchlist_members(pool_b.id, ((security_id, detail.bindings[1].id),))

    assert a.memberships[0].participating_classification_name == "AI Data Center"
    assert b.memberships[0].participating_classification_name == "Bitcoin Mining"


def test_watchlist_member_can_change_its_participating_binding_atomically(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    first = service.create_classification("AI Data Center")
    second = service.create_classification("Bitcoin Mining")
    detail = service.set_security_classifications(
        security_id,
        (first.id, second.id),
    )
    watchlist = service.create_watchlist("Growth")
    added = service.add_watchlist_members(
        watchlist.id,
        ((security_id, detail.bindings[0].id),),
    )

    updated = service.set_watchlist_member_binding(
        watchlist.id,
        security_id,
        detail.bindings[1].id,
    )

    assert updated.memberships[0].id == added.memberships[0].id
    assert (
        updated.memberships[0].participating_classification_name
        == "Bitcoin Mining"
    )


def test_security_binding_limit_and_watchlist_member_cap_are_atomic(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    classifications = tuple(
        service.create_classification(f"Class {number}") for number in range(4)
    )

    with pytest.raises(PersistenceConflictError):
        service.set_security_classifications(
            security_id,
            tuple(item.id for item in classifications),
        )

    assert service.get_security(security_id).bindings == ()


def test_manage_classifications_members_watchlists_and_security(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    classification = service.create_classification("AI Data Center")
    renamed = service.rename_classification(
        classification.id,
        "AI Infrastructure",
    )
    detail = service.set_security_classifications(
        security_id,
        (renamed.id,),
    )
    watchlist = service.create_watchlist("Growth")
    watchlist = service.add_watchlist_members(
        watchlist.id,
        ((security_id, detail.bindings[0].id),),
    )

    renamed_pool = service.rename_watchlist(watchlist.id, "Core Growth")
    assert renamed_pool.display_name == "Core Growth"
    assert service.security_watchlist_count(security_id) == 1

    emptied = service.remove_watchlist_members(
        watchlist.id,
        (security_id,),
    )
    assert emptied.memberships == ()
    service.delete_watchlist(watchlist.id)
    service.set_security_classifications(security_id, ())
    service.delete_classification(classification.id)
    service.delete_security(security_id)

    assert service.list_watchlists() == ()
    assert service.list_classifications() == ()
    assert service.list_securities() == ()


def test_removing_a_participating_classification_rebinds_to_remaining_label(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    old = service.create_classification("Old Theme")
    replacement = service.create_classification("Replacement Theme")
    detail = service.set_security_classifications(
        security_id,
        (old.id, replacement.id),
    )
    old_binding = next(
        item for item in detail.bindings if item.classification_id == old.id
    )
    replacement_binding = next(
        item for item in detail.bindings if item.classification_id == replacement.id
    )
    first = service.create_watchlist("First Pool")
    second = service.create_watchlist("Second Pool")
    service.add_watchlist_members(
        first.id,
        ((security_id, old_binding.id),),
    )
    service.add_watchlist_members(
        second.id,
        ((security_id, old_binding.id),),
    )

    updated = service.set_security_classifications(
        security_id,
        (replacement.id,),
    )

    assert tuple(item.classification_id for item in updated.bindings) == (
        replacement.id,
    )
    assert service.binding_watchlist_names(old_binding.id) == ()
    assert (
        service.get_watchlist(first.id).memberships[0].participating_binding_id
        == replacement_binding.id
    )
    assert (
        service.get_watchlist(second.id).memberships[0].participating_binding_id
        == replacement_binding.id
    )


def test_removing_the_only_participating_classification_removes_pool_membership(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    classification = service.create_classification("Only Theme")
    detail = service.set_security_classifications(
        security_id,
        (classification.id,),
    )
    watchlist = service.create_watchlist("Pool")
    service.add_watchlist_members(
        watchlist.id,
        ((security_id, detail.bindings[0].id),),
    )

    updated = service.set_security_classifications(security_id, ())

    assert updated.bindings == ()
    assert service.get_watchlist(watchlist.id).memberships == ()


def test_replacing_the_only_label_keeps_the_security_in_its_pool(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    old = service.create_classification("Old")
    replacement = service.create_classification("New")
    detail = service.set_security_classifications(security_id, (old.id,))
    watchlist = service.create_watchlist("Pool")
    service.add_watchlist_members(
        watchlist.id,
        ((security_id, detail.bindings[0].id),),
    )

    updated = service.set_security_classifications(
        security_id,
        (replacement.id,),
    )

    assert tuple(item.classification_id for item in updated.bindings) == (
        replacement.id,
    )
    membership = service.get_watchlist(watchlist.id).memberships[0]
    assert membership.participating_binding_id == updated.bindings[0].id
    assert membership.participating_classification_name == "New"


def test_delete_security_removes_current_pool_membership_but_not_other_data(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    classification = service.create_classification("AI")
    detail = service.set_security_classifications(
        security_id,
        (classification.id,),
    )
    watchlist = service.create_watchlist("Pool")
    service.add_watchlist_members(
        watchlist.id,
        ((security_id, detail.bindings[0].id),),
    )

    service.delete_security(security_id)

    assert service.list_securities() == ()
    assert service.get_watchlist(watchlist.id).memberships == ()
    assert service.list_classifications() == (classification,)


def test_classification_aliases_are_normalized_unique_and_searchable_data(
    tmp_path: Path,
) -> None:
    service, _factory = store(tmp_path)
    classification = service.create_classification("AI Data Center")

    updated = service.set_classification_aliases(
        classification.id,
        (" AI Cloud ", "Compute Infrastructure", "ai cloud"),
    )

    assert updated.aliases == ("AI Cloud", "Compute Infrastructure")
    assert service.list_classifications()[0].aliases == updated.aliases

    other = service.create_classification("Bitcoin Mining")
    with pytest.raises(PersistenceConflictError):
        service.set_classification_aliases(other.id, ("AI Cloud",))


def test_profile_refresh_preserves_bindings_and_pool_membership(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    classification = service.create_classification("AI Infrastructure")
    security = service.set_security_classifications(
        security_id,
        (classification.id,),
    )
    pool = service.create_watchlist("Refresh")
    service.add_watchlist_members(
        pool.id,
        ((security_id, security.bindings[0].id),),
    )
    refreshed_at = datetime(2026, 7, 26, 12, tzinfo=UTC)

    updated = service.refresh_security_profile(
        security_id,
        ProviderProfile(
            "IREN.US",
            "IREN Limited",
            "US",
            "NASDAQ",
            "USD",
            "US",
            "Updated AI cloud and data-center description",
            (),
            {"source": "fresh"},
            refreshed_at,
        ),
        provider_id="longbridge",
    )

    assert updated.display_name == "IREN Limited"
    assert updated.description == "Updated AI cloud and data-center description"
    assert updated.bindings == security.bindings
    assert len(service.get_watchlist(pool.id).memberships) == 1


def test_ai_reanalysis_only_adds_into_free_slots_and_reuses_aliases(
    tmp_path: Path,
) -> None:
    service, factory = store(tmp_path)
    security_id = seed_security(factory)
    human = service.create_classification("Bitcoin Mining")
    aliased = service.create_classification("AI Data Center")
    service.set_classification_aliases(aliased.id, ("AI Cloud",))
    service.set_security_classifications(security_id, (human.id,))

    updated = service.add_ai_classifications(
        security_id,
        (
            (None, "AI Cloud", Decimal("0.91")),
            (None, "Energy Infrastructure", Decimal("0.82")),
            (None, "Fourth Is Ignored", Decimal("0.75")),
        ),
    )

    assert len(updated.bindings) == 3
    assert updated.bindings[0].source == "HUMAN"
    assert {item.classification_name for item in updated.bindings} == {
        "Bitcoin Mining",
        "AI Data Center",
        "Energy Infrastructure",
    }
    assert "AI Cloud" not in {
        item.display_name
        for item in service.list_classifications()
    }
