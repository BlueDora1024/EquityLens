"""Transactional SQLite implementation of global master-data workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from stock_toolbox.core.master_data.models import (
    ClassificationDTO,
    SecurityBindingDTO,
    SecurityDetailDTO,
    WatchlistDTO,
    WatchlistMembershipDTO,
)
from stock_toolbox.core.securities.models import ProviderProfile
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import (
    PersistenceConflictError,
    PersistenceValidationError,
)
from stock_toolbox.infrastructure.persistence.records import (
    AIReceiptRecord,
    ClassificationRecord,
    SecurityClassificationRecord,
    WatchlistMembershipRecord,
    WatchlistRecord,
)
from stock_toolbox.infrastructure.persistence.repositories import (
    AIReceiptBindingRepository,
    ClassificationRepository,
    SecurityRepository,
    WatchlistRepository,
    _mapped,
)
from stock_toolbox.infrastructure.persistence.types import canonical_instant, canonical_json
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork


class SQLiteMasterDataStore:
    def __init__(
        self,
        factory: SQLiteConnectionFactory,
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
    ) -> None:
        self._factory = factory
        self._clock = clock
        self._new_id = new_id

    def create_classification(self, display_name: str) -> ClassificationDTO:
        name = " ".join(display_name.split())
        if not name or len(name) > 40:
            raise PersistenceValidationError()
        now = self._clock()
        record = ClassificationRecord(
            self._new_id(),
            name,
            name.casefold(),
            (),
            "HUMAN",
            now,
            now,
            0,
        )
        with SQLiteUnitOfWork(self._factory) as uow:
            ClassificationRepository(uow.connection).add(record)
            uow.commit()
        return self._classification_dto(record)

    def list_classifications(self) -> tuple[ClassificationDTO, ...]:
        with SQLiteUnitOfWork(self._factory) as uow:
            records = ClassificationRepository(uow.connection).list_all()
        return tuple(self._classification_dto(record) for record in records)

    def rename_classification(
        self,
        classification_id: str,
        display_name: str,
    ) -> ClassificationDTO:
        name = " ".join(display_name.split())
        if not name or len(name) > 40:
            raise PersistenceValidationError()
        with SQLiteUnitOfWork(self._factory) as uow:
            cursor = _mapped(
                lambda: uow.connection.execute(
                    "UPDATE classifications SET display_name=?,"
                    "normalized_name=?,updated_at_utc=?,revision=revision+1 "
                    "WHERE id=?",
                    (
                        name,
                        name.casefold(),
                        canonical_instant(self._clock()),
                        classification_id,
                    ),
                )
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()
        record = next(
            (item for item in self.list_classifications() if item.id == classification_id),
            None,
        )
        if record is None:
            raise PersistenceValidationError()
        return record

    def set_classification_aliases(
        self,
        classification_id: str,
        aliases: tuple[str, ...],
    ) -> ClassificationDTO:
        normalized_aliases: dict[str, str] = {}
        for raw_alias in aliases:
            alias = " ".join(raw_alias.split())
            if not alias or len(alias) > 40:
                raise PersistenceValidationError()
            normalized_aliases.setdefault(alias.casefold(), alias)
        if len(normalized_aliases) > 20:
            raise PersistenceValidationError()
        with SQLiteUnitOfWork(self._factory) as uow:
            repository = ClassificationRepository(uow.connection)
            current = repository.get(classification_id)
            if current is None:
                raise PersistenceValidationError()
            normalized_aliases.pop(current.normalized_name, None)
            reserved: set[str] = set()
            for record in repository.list_all():
                if record.id == classification_id:
                    continue
                reserved.add(record.normalized_name)
                reserved.update(alias.casefold() for alias in record.aliases)
            if set(normalized_aliases) & reserved:
                raise PersistenceConflictError()
            ordered = tuple(
                normalized_aliases[key]
                for key in sorted(normalized_aliases)
            )
            cursor = uow.connection.execute(
                "UPDATE classifications SET aliases_json=?,updated_at_utc=?,"
                "revision=revision+1 WHERE id=?",
                (
                    canonical_json(list(ordered)),
                    canonical_instant(self._clock()),
                    classification_id,
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()
        updated = next(
            (
                item
                for item in self.list_classifications()
                if item.id == classification_id
            ),
            None,
        )
        if updated is None:
            raise PersistenceValidationError()
        return updated

    def delete_classification(self, classification_id: str) -> None:
        with SQLiteUnitOfWork(self._factory) as uow:
            references = int(
                uow.connection.execute(
                    "SELECT count(*) FROM security_classifications WHERE classification_id=?",
                    (classification_id,),
                ).fetchone()[0]
            )
            if references:
                raise PersistenceConflictError()
            cursor = uow.connection.execute(
                "DELETE FROM classifications WHERE id=?",
                (classification_id,),
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()

    def merge_classification(
        self,
        source_classification_id: str,
        target_classification_id: str,
    ) -> tuple[int, int]:
        if (
            not source_classification_id
            or not target_classification_id
            or source_classification_id == target_classification_id
        ):
            raise PersistenceValidationError()
        with SQLiteUnitOfWork(self._factory) as uow:
            classifications = ClassificationRepository(uow.connection)
            if (
                classifications.get(source_classification_id) is None
                or classifications.get(target_classification_id) is None
            ):
                raise PersistenceValidationError()
            source_bindings = uow.connection.execute(
                "SELECT id,security_id FROM security_classifications "
                "WHERE classification_id=? ORDER BY security_id",
                (source_classification_id,),
            ).fetchall()
            affected_memberships = 0
            affected_watchlists: set[str] = set()
            for source_binding in source_bindings:
                source_binding_id = str(source_binding["id"])
                security_id = str(source_binding["security_id"])
                target_binding = uow.connection.execute(
                    "SELECT id FROM security_classifications "
                    "WHERE security_id=? AND classification_id=?",
                    (security_id, target_classification_id),
                ).fetchone()
                membership_rows = uow.connection.execute(
                    "SELECT watchlist_id FROM watchlist_memberships "
                    "WHERE participating_binding_id=?",
                    (source_binding_id,),
                ).fetchall()
                affected_watchlists.update(str(row["watchlist_id"]) for row in membership_rows)
                affected_memberships += len(membership_rows)
                if target_binding is None:
                    uow.connection.execute(
                        "UPDATE security_classifications "
                        "SET classification_id=?,updated_at_utc=? "
                        "WHERE id=?",
                        (
                            target_classification_id,
                            canonical_instant(self._clock()),
                            source_binding_id,
                        ),
                    )
                    continue
                target_binding_id = str(target_binding["id"])
                uow.connection.execute(
                    "UPDATE watchlist_memberships "
                    "SET participating_binding_id=?,updated_at_utc=? "
                    "WHERE participating_binding_id=?",
                    (
                        target_binding_id,
                        canonical_instant(self._clock()),
                        source_binding_id,
                    ),
                )
                self._delete_binding(uow, source_binding_id)
            for watchlist_id in affected_watchlists:
                uow.connection.execute(
                    "UPDATE calculation_watchlists "
                    "SET revision=revision+1,updated_at_utc=? WHERE id=?",
                    (canonical_instant(self._clock()), watchlist_id),
                )
            cursor = uow.connection.execute(
                "DELETE FROM classifications WHERE id=?",
                (source_classification_id,),
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()
        return len(source_bindings), affected_memberships

    def classification_usage(
        self,
        classification_id: str,
    ) -> tuple[int, int]:
        with SQLiteUnitOfWork(self._factory) as uow:
            security_count = int(
                uow.connection.execute(
                    "SELECT count(*) FROM security_classifications WHERE classification_id=?",
                    (classification_id,),
                ).fetchone()[0]
            )
            membership_count = int(
                uow.connection.execute(
                    "SELECT count(*) FROM watchlist_memberships wm "
                    "JOIN security_classifications sc "
                    "ON sc.id=wm.participating_binding_id "
                    "WHERE sc.classification_id=?",
                    (classification_id,),
                ).fetchone()[0]
            )
        return security_count, membership_count

    def list_securities(self) -> tuple[SecurityDetailDTO, ...]:
        with SQLiteUnitOfWork(self._factory) as uow:
            rows = _mapped(
                lambda: uow.connection.execute(
                    "SELECT id FROM global_securities ORDER BY canonical_symbol"
                ).fetchall()
            )
            return tuple(self._security_detail(uow, str(row["id"])) for row in rows)

    def get_security(self, security_id: str) -> SecurityDetailDTO:
        with SQLiteUnitOfWork(self._factory) as uow:
            return self._security_detail(uow, security_id)

    def refresh_security_profile(
        self,
        security_id: str,
        profile: ProviderProfile,
        *,
        provider_id: str,
    ) -> SecurityDetailDTO:
        if not provider_id.strip() or profile.market != "US":
            raise PersistenceValidationError()
        with SQLiteUnitOfWork(self._factory) as uow:
            current = SecurityRepository(uow.connection).get(security_id)
            if current is None or current.canonical_symbol != profile.symbol:
                raise PersistenceValidationError()
            display_name = (profile.name or current.display_name).strip()
            if not display_name:
                raise PersistenceValidationError()
            cursor = uow.connection.execute(
                "UPDATE global_securities SET display_name=?,"
                "profile_provider_id=?,exchange=?,currency=?,"
                "listing_country=?,description=?,business_profile_json=?,"
                "source_updated_at_utc=?,updated_at_utc=?,revision=revision+1 "
                "WHERE id=?",
                (
                    display_name,
                    provider_id,
                    profile.exchange,
                    (
                        profile.currency.upper()
                        if profile.currency is not None
                        else None
                    ),
                    profile.listing_country,
                    profile.description,
                    canonical_json(dict(profile.business_profile)),
                    (
                        canonical_instant(profile.source_updated_at)
                        if profile.source_updated_at is not None
                        else None
                    ),
                    canonical_instant(self._clock()),
                    security_id,
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()
        return self.get_security(security_id)

    def record_security_refresh(
        self,
        security_id: str,
        *,
        availability_status: str,
        error_code: str = "",
        last_price: str = "",
        market_value: str = "",
    ) -> SecurityDetailDTO:
        if availability_status not in {
            "ACTIVE",
            "UNAVAILABLE",
            "CHECK_FAILED",
        }:
            raise PersistenceValidationError()
        with SQLiteUnitOfWork(self._factory) as uow:
            current = SecurityRepository(uow.connection).get(security_id)
            if current is None:
                raise PersistenceValidationError()
            profile = dict(current.business_profile)
            previous_refresh = profile.get("refresh")
            previous = (
                dict(previous_refresh)
                if isinstance(previous_refresh, dict)
                else {}
            )
            refresh = {
                "status": availability_status,
                "error": error_code,
                "checked_at": canonical_instant(self._clock()),
            }
            effective_last_price = last_price or str(
                previous.get("last_price") or ""
            )
            effective_market_value = market_value or str(
                previous.get("market_value") or ""
            )
            if effective_last_price:
                refresh["last_price"] = effective_last_price
            if effective_market_value:
                refresh["market_value"] = effective_market_value
            profile["refresh"] = refresh
            cursor = _mapped(
                lambda: uow.connection.execute(
                    "UPDATE global_securities SET business_profile_json=?,"
                    "updated_at_utc=?,revision=revision+1 WHERE id=?",
                    (
                        canonical_json(profile),
                        canonical_instant(self._clock()),
                        security_id,
                    ),
                )
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()
        return self.get_security(security_id)

    def add_ai_classifications(
        self,
        security_id: str,
        proposals: tuple[tuple[str | None, str, Decimal], ...],
    ) -> SecurityDetailDTO:
        now = self._clock()
        with SQLiteUnitOfWork(self._factory) as uow:
            security = SecurityRepository(uow.connection).get(security_id)
            if security is None:
                raise PersistenceValidationError()
            bindings = AIReceiptBindingRepository(uow.connection)
            current = bindings.list_bindings(security_id)
            free_slots = 3 - len(current)
            if free_slots <= 0:
                return self._security_detail(uow, security_id)
            classifications = ClassificationRepository(uow.connection)
            stored = classifications.list_all()
            by_id = {item.id: item for item in stored}
            by_name = {
                normalized: item
                for item in stored
                for normalized in (
                    item.normalized_name,
                    *(alias.casefold() for alias in item.aliases),
                )
            }
            existing_ids = {item.classification_id for item in current}
            additions: list[tuple[ClassificationRecord, Decimal]] = []
            seen_ids = set(existing_ids)
            for classification_id, raw_name, confidence in proposals:
                if len(additions) >= free_slots:
                    break
                name = " ".join(raw_name.split())
                if (
                    not name
                    or len(name) > 40
                    or not confidence.is_finite()
                    or not Decimal(0) <= confidence <= Decimal(1)
                ):
                    continue
                classification = (
                    by_id.get(classification_id)
                    if classification_id is not None
                    else None
                )
                if classification is None:
                    classification = by_name.get(name.casefold())
                if classification is None:
                    classification = ClassificationRecord(
                        self._new_id(),
                        name,
                        name.casefold(),
                        (),
                        "AI",
                        now,
                        now,
                        0,
                    )
                    classifications.add(classification)
                    by_id[classification.id] = classification
                    by_name[classification.normalized_name] = classification
                if classification.id in seen_ids:
                    continue
                seen_ids.add(classification.id)
                additions.append((classification, confidence))
            if not additions:
                return self._security_detail(uow, security_id)
            receipt_id = self._new_id()
            receipt = AIReceiptRecord(
                receipt_id,
                "business_classification",
                security.canonical_symbol,
                security_id,
                f"reanalyze:{receipt_id}",
                "business-classification-v3",
                "ai-classification-v1",
                "global-ai-config",
                "classifications:"
                + ",".join(item.id for item, _confidence in additions),
                "APPLIED",
                {"classification_count": len(additions)},
                now,
            )
            bindings.insert_receipt_with_bindings(
                receipt,
                tuple(
                    SecurityClassificationRecord(
                        self._new_id(),
                        security_id,
                        classification.id,
                        "AI",
                        receipt_id,
                        confidence,
                        (),
                        (),
                        receipt_id,
                        False,
                        now,
                        now,
                    )
                    for classification, confidence in additions
                ),
            )
            uow.commit()
        return self.get_security(security_id)

    def security_watchlist_count(self, security_id: str) -> int:
        with SQLiteUnitOfWork(self._factory) as uow:
            return int(
                uow.connection.execute(
                    "SELECT count(*) FROM watchlist_memberships WHERE security_id=?",
                    (security_id,),
                ).fetchone()[0]
            )

    def binding_watchlist_names(
        self,
        binding_id: str,
    ) -> tuple[str, ...]:
        with SQLiteUnitOfWork(self._factory) as uow:
            rows = uow.connection.execute(
                "SELECT w.display_name FROM watchlist_memberships m "
                "JOIN calculation_watchlists w ON w.id=m.watchlist_id "
                "WHERE m.participating_binding_id=? "
                "ORDER BY w.normalized_name,w.id",
                (binding_id,),
            ).fetchall()
        return tuple(str(row["display_name"]) for row in rows)

    def delete_security(self, security_id: str) -> None:
        with SQLiteUnitOfWork(self._factory) as uow:
            uow.connection.execute(
                "DELETE FROM watchlist_memberships WHERE security_id=?",
                (security_id,),
            )
            cursor = uow.connection.execute(
                "DELETE FROM global_securities WHERE id=?",
                (security_id,),
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()

    def set_security_classifications(
        self,
        security_id: str,
        classification_ids: tuple[str, ...],
    ) -> SecurityDetailDTO:
        if len(classification_ids) > 3 or len(classification_ids) != len(set(classification_ids)):
            raise PersistenceConflictError()
        now = self._clock()
        with SQLiteUnitOfWork(self._factory) as uow:
            if SecurityRepository(uow.connection).get(security_id) is None:
                raise PersistenceValidationError()
            classifications = ClassificationRepository(uow.connection)
            if any(
                classifications.get(classification_id) is None
                for classification_id in classification_ids
            ):
                raise PersistenceValidationError()
            bindings = AIReceiptBindingRepository(uow.connection)
            current = bindings.list_bindings(security_id)
            by_classification = {binding.classification_id: binding for binding in current}
            removing = [
                binding
                for binding in current
                if binding.classification_id not in classification_ids
            ]
            affected_watchlists: set[str] = set()

            # When every current label is replaced in one operation, keep one
            # binding id alive so existing pool membership remains meaningful.
            retained = {
                classification_id: by_classification[classification_id]
                for classification_id in classification_ids
                if classification_id in by_classification
            }
            missing = [
                classification_id
                for classification_id in classification_ids
                if classification_id not in retained
            ]
            if removing and not retained and missing:
                reused = removing.pop(0)
                classification_id = missing.pop(0)
                uow.connection.execute(
                    "UPDATE security_classifications SET "
                    "classification_id=?,source='HUMAN',ai_receipt_id=NULL,"
                    "confidence_text=NULL,evidence_json='[]',evidence_refs_json='[]',"
                    "source_request_id=NULL,human_protected=1,updated_at_utc=? "
                    "WHERE id=?",
                    (
                        classification_id,
                        canonical_instant(now),
                        reused.id,
                    ),
                )
                retained[classification_id] = replace(
                    reused,
                    classification_id=classification_id,
                    source="HUMAN",
                    ai_receipt_id=None,
                    confidence=None,
                    evidence=(),
                    evidence_refs=(),
                    source_request_id=None,
                    human_protected=True,
                    updated_at=now,
                )

            replacement = next(
                (
                    retained[classification_id]
                    for classification_id in classification_ids
                    if classification_id in retained
                ),
                None,
            )
            for binding in removing:
                rows = uow.connection.execute(
                    "SELECT watchlist_id FROM watchlist_memberships "
                    "WHERE participating_binding_id=?",
                    (binding.id,),
                ).fetchall()
                affected_watchlists.update(
                    str(row["watchlist_id"]) for row in rows
                )
                if replacement is None:
                    uow.connection.execute(
                        "DELETE FROM watchlist_memberships "
                        "WHERE participating_binding_id=?",
                        (binding.id,),
                    )
                else:
                    uow.connection.execute(
                        "UPDATE watchlist_memberships "
                        "SET participating_binding_id=?,updated_at_utc=? "
                        "WHERE participating_binding_id=?",
                        (
                            replacement.id,
                            canonical_instant(now),
                            binding.id,
                        ),
                    )
                self._delete_binding(uow, binding.id)
            for classification_id in missing:
                bindings.add_human_binding(
                    SecurityClassificationRecord(
                        self._new_id(),
                        security_id,
                        classification_id,
                        "HUMAN",
                        None,
                        None,
                        (),
                        (),
                        None,
                        True,
                        now,
                        now,
                    )
                )
            for watchlist_id in affected_watchlists:
                uow.connection.execute(
                    "UPDATE calculation_watchlists "
                    "SET revision=revision+1,updated_at_utc=? WHERE id=?",
                    (canonical_instant(now), watchlist_id),
                )
            uow.commit()
        return self.get_security(security_id)

    def create_watchlist(self, display_name: str) -> WatchlistDTO:
        name = " ".join(display_name.split())
        if not name:
            raise PersistenceValidationError()
        now = self._clock()
        record = WatchlistRecord(
            self._new_id(),
            name,
            name.casefold(),
            now,
            now,
            0,
        )
        with SQLiteUnitOfWork(self._factory) as uow:
            WatchlistRepository(uow.connection).add(record)
            uow.commit()
        return WatchlistDTO(record.id, record.display_name, 0, ())

    def list_watchlists(self) -> tuple[WatchlistDTO, ...]:
        with SQLiteUnitOfWork(self._factory) as uow:
            rows = _mapped(
                lambda: uow.connection.execute(
                    "SELECT id FROM calculation_watchlists ORDER BY normalized_name,id"
                ).fetchall()
            )
            return tuple(
                self._watchlist_dto(
                    uow,
                    self._require_watchlist(uow, str(row["id"])),
                )
                for row in rows
            )

    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO:
        with SQLiteUnitOfWork(self._factory) as uow:
            return self._watchlist_dto(
                uow,
                self._require_watchlist(uow, watchlist_id),
            )

    def rename_watchlist(
        self,
        watchlist_id: str,
        display_name: str,
    ) -> WatchlistDTO:
        name = " ".join(display_name.split())
        if not name:
            raise PersistenceValidationError()
        with SQLiteUnitOfWork(self._factory) as uow:
            cursor = uow.connection.execute(
                "UPDATE calculation_watchlists SET display_name=?,"
                "normalized_name=?,updated_at_utc=?,revision=revision+1 "
                "WHERE id=?",
                (
                    name,
                    name.casefold(),
                    canonical_instant(self._clock()),
                    watchlist_id,
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()
        return self.get_watchlist(watchlist_id)

    def delete_watchlist(self, watchlist_id: str) -> None:
        with SQLiteUnitOfWork(self._factory) as uow:
            cursor = uow.connection.execute(
                "DELETE FROM calculation_watchlists WHERE id=?",
                (watchlist_id,),
            )
            if cursor.rowcount != 1:
                raise PersistenceValidationError()
            uow.commit()

    def remove_watchlist_members(
        self,
        watchlist_id: str,
        security_ids: tuple[str, ...],
    ) -> WatchlistDTO:
        if len(security_ids) != len(set(security_ids)):
            raise PersistenceConflictError()
        with SQLiteUnitOfWork(self._factory) as uow:
            repository = WatchlistRepository(uow.connection)
            watchlist = self._require_watchlist(uow, watchlist_id)
            remaining = tuple(
                item for item in watchlist.memberships if item.security_id not in set(security_ids)
            )
            if len(remaining) == len(watchlist.memberships):
                raise PersistenceValidationError()
            repository.replace_memberships(
                watchlist_id,
                expected_revision=watchlist.revision,
                memberships=remaining,
            )
            uow.commit()
        return self.get_watchlist(watchlist_id)

    def set_watchlist_member_binding(
        self,
        watchlist_id: str,
        security_id: str,
        binding_id: str,
    ) -> WatchlistDTO:
        now = self._clock()
        with SQLiteUnitOfWork(self._factory) as uow:
            repository = WatchlistRepository(uow.connection)
            watchlist = self._require_watchlist(uow, watchlist_id)
            found = False
            memberships: list[WatchlistMembershipRecord] = []
            for item in watchlist.memberships:
                if item.security_id != security_id:
                    memberships.append(item)
                    continue
                found = True
                memberships.append(
                    WatchlistMembershipRecord(
                        item.id,
                        item.watchlist_id,
                        item.security_id,
                        binding_id,
                        item.created_at,
                        now,
                    )
                )
            if not found:
                raise PersistenceValidationError()
            repository.replace_memberships(
                watchlist_id,
                expected_revision=watchlist.revision,
                memberships=tuple(memberships),
            )
            uow.commit()
        return self.get_watchlist(watchlist_id)

    def add_watchlist_members(
        self,
        watchlist_id: str,
        selections: tuple[tuple[str, str], ...],
    ) -> WatchlistDTO:
        now = self._clock()
        with SQLiteUnitOfWork(self._factory) as uow:
            repository = WatchlistRepository(uow.connection)
            watchlist = self._require_watchlist(uow, watchlist_id)
            existing_security_ids = {item.security_id for item in watchlist.memberships}
            if len({security_id for security_id, _binding in selections}) != len(selections):
                raise PersistenceConflictError()
            additions = tuple(
                WatchlistMembershipRecord(
                    self._new_id(),
                    watchlist_id,
                    security_id,
                    binding_id,
                    now,
                    now,
                )
                for security_id, binding_id in selections
                if security_id not in existing_security_ids
            )
            merged = (*watchlist.memberships, *additions)
            if len(merged) > 600:
                raise PersistenceConflictError()
            repository.replace_memberships(
                watchlist_id,
                expected_revision=watchlist.revision,
                memberships=merged,
            )
            uow.commit()
        return self.get_watchlist(watchlist_id)

    @staticmethod
    def _binding_reference_count(
        uow: SQLiteUnitOfWork,
        binding_id: str,
    ) -> int:
        return int(
            _mapped(
                lambda: uow.connection.execute(
                    "SELECT count(*) FROM watchlist_memberships WHERE participating_binding_id=?",
                    (binding_id,),
                ).fetchone()[0]
            )
        )

    @staticmethod
    def _delete_binding(
        uow: SQLiteUnitOfWork,
        binding_id: str,
    ) -> None:
        _mapped(
            lambda: uow.connection.execute(
                "DELETE FROM security_classifications WHERE id=?",
                (binding_id,),
            )
        )

    @staticmethod
    def _classification_dto(
        record: ClassificationRecord,
    ) -> ClassificationDTO:
        return ClassificationDTO(
            record.id,
            record.display_name,
            record.normalized_name,
            record.origin,
            record.aliases,
        )

    @staticmethod
    def _require_watchlist(
        uow: SQLiteUnitOfWork,
        watchlist_id: str,
    ) -> WatchlistRecord:
        watchlist = WatchlistRepository(uow.connection).get_for_update(watchlist_id)
        if watchlist is None:
            raise PersistenceValidationError()
        return watchlist

    @staticmethod
    def _security_detail(
        uow: SQLiteUnitOfWork,
        security_id: str,
    ) -> SecurityDetailDTO:
        security = SecurityRepository(uow.connection).get(security_id)
        if security is None:
            raise PersistenceValidationError()
        classifications = ClassificationRepository(uow.connection)
        bindings = tuple(
            SecurityBindingDTO(
                binding.id,
                binding.classification_id,
                (
                    classification.display_name
                    if (classification := classifications.get(binding.classification_id))
                    is not None
                    else "未分类"
                ),
                binding.source,
            )
            for binding in AIReceiptBindingRepository(uow.connection).list_bindings(security_id)
        )
        return SecurityDetailDTO(
            security.id,
            security.canonical_symbol,
            security.display_name,
            security.exchange,
            security.currency,
            security.listing_country,
            security.description,
            security.business_profile,
            security.asset_type,
            bindings,
        )

    @staticmethod
    def _watchlist_dto(
        uow: SQLiteUnitOfWork,
        watchlist: WatchlistRecord,
    ) -> WatchlistDTO:
        securities = SecurityRepository(uow.connection)
        classifications = ClassificationRepository(uow.connection)
        binding_repository = AIReceiptBindingRepository(uow.connection)
        projected = []
        for member in watchlist.memberships:
            security = securities.get(member.security_id)
            binding = next(
                (
                    item
                    for item in binding_repository.list_bindings(member.security_id)
                    if item.id == member.participating_binding_id
                ),
                None,
            )
            if security is None or binding is None:
                raise PersistenceValidationError()
            classification = classifications.get(binding.classification_id)
            if classification is None:
                raise PersistenceValidationError()
            projected.append(
                WatchlistMembershipDTO(
                    member.id,
                    security.id,
                    security.canonical_symbol,
                    security.display_name,
                    binding.id,
                    classification.id,
                    classification.display_name,
                )
            )
        return WatchlistDTO(
            watchlist.id,
            watchlist.display_name,
            watchlist.revision,
            tuple(projected),
        )
