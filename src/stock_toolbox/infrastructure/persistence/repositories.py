"""Narrow repositories for current SQLite master data."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any, cast

from stock_toolbox.infrastructure.persistence.errors import (
    ConcurrentModificationError,
    PersistenceConflictError,
    PersistenceError,
)
from stock_toolbox.infrastructure.persistence.records import (
    AIReceiptRecord,
    ClassificationRecord,
    SecurityClassificationRecord,
    SecurityRecord,
    WatchlistMembershipRecord,
    WatchlistRecord,
)
from stock_toolbox.infrastructure.persistence.types import (
    canonical_decimal_text,
    canonical_instant,
    canonical_json,
    parse_canonical_decimal,
    parse_canonical_instant,
    parse_canonical_json,
    parse_uuid4,
)
from stock_toolbox.infrastructure.persistence.uow import (
    map_sqlite_error,
    require_revision_update,
)


def _mapped[ResultT](call: Callable[[], ResultT]) -> ResultT:
    try:
        return call()
    except sqlite3.Error as error:
        raise map_sqlite_error(error) from error


def _uuid(value: str) -> str:
    return str(parse_uuid4(value))


class SecurityRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, security: SecurityRecord) -> None:
        values = self._values(security)
        _mapped(
            lambda: self._connection.execute(
                "INSERT INTO global_securities("
                "id,canonical_symbol,market,display_name,asset_type,"
                "eligibility_source,profile_provider_id,exchange,currency,"
                "listing_country,description,business_profile_json,"
                "source_updated_at_utc,created_at_utc,updated_at_utc,revision"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )
        )

    def get(self, security_id: str) -> SecurityRecord | None:
        row = _mapped(
            lambda: self._connection.execute(
                "SELECT * FROM global_securities WHERE id=?",
                (security_id,),
            ).fetchone()
        )
        return None if row is None else self._from_row(row)

    def get_by_symbol(self, symbol: str) -> SecurityRecord | None:
        row = _mapped(
            lambda: self._connection.execute(
                "SELECT * FROM global_securities "
                "WHERE canonical_symbol=? AND market='US'",
                (symbol,),
            ).fetchone()
        )
        return None if row is None else self._from_row(row)

    def update(
        self,
        security: SecurityRecord,
        *,
        expected_revision: int,
    ) -> None:
        values = self._values(security)

        def execute() -> sqlite3.Cursor:
            return self._connection.execute(
                "UPDATE global_securities SET "
                "canonical_symbol=?,market=?,display_name=?,asset_type=?,"
                "eligibility_source=?,profile_provider_id=?,exchange=?,currency=?,"
                "listing_country=?,description=?,business_profile_json=?,"
                "source_updated_at_utc=?,created_at_utc=?,updated_at_utc=?,revision=? "
                "WHERE id=? AND revision=?",
                (*values[1:], values[0], expected_revision),
            )

        cursor = _mapped(execute)
        require_revision_update(cursor.rowcount)

    def remove(self, security_id: str) -> None:
        _mapped(
            lambda: self._connection.execute(
                "DELETE FROM global_securities WHERE id=?",
                (security_id,),
            )
        )

    @staticmethod
    def _values(security: SecurityRecord) -> tuple[Any, ...]:
        return (
            _uuid(security.id),
            security.canonical_symbol,
            security.market,
            security.display_name,
            security.asset_type,
            security.eligibility_source,
            security.profile_provider_id,
            security.exchange,
            security.currency,
            security.listing_country,
            security.description,
            canonical_json(dict(security.business_profile)),
            (
                canonical_instant(security.source_updated_at)
                if security.source_updated_at is not None
                else None
            ),
            canonical_instant(security.created_at),
            canonical_instant(security.updated_at),
            security.revision,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> SecurityRecord:
        profile = parse_canonical_json(row["business_profile_json"])
        if not isinstance(profile, dict):
            raise PersistenceError("Stored security profile is invalid")
        return SecurityRecord(
            id=_uuid(row["id"]),
            canonical_symbol=str(row["canonical_symbol"]),
            market=str(row["market"]),
            display_name=str(row["display_name"]),
            asset_type=str(row["asset_type"]),
            eligibility_source=str(row["eligibility_source"]),
            profile_provider_id=str(row["profile_provider_id"]),
            exchange=row["exchange"],
            currency=row["currency"],
            listing_country=row["listing_country"],
            description=row["description"],
            business_profile=profile,
            source_updated_at=(
                parse_canonical_instant(row["source_updated_at_utc"])
                if row["source_updated_at_utc"] is not None
                else None
            ),
            created_at=parse_canonical_instant(row["created_at_utc"]),
            updated_at=parse_canonical_instant(row["updated_at_utc"]),
            revision=int(row["revision"]),
        )


class ClassificationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, classification: ClassificationRecord) -> None:
        _mapped(
            lambda: self._connection.execute(
                "INSERT INTO classifications("
                "id,display_name,normalized_name,aliases_json,origin,"
                "created_at_utc,updated_at_utc,revision"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    _uuid(classification.id),
                    classification.display_name,
                    classification.normalized_name,
                    canonical_json(list(classification.aliases)),
                    classification.origin,
                    canonical_instant(classification.created_at),
                    canonical_instant(classification.updated_at),
                    classification.revision,
                ),
            )
        )

    def get(self, classification_id: str) -> ClassificationRecord | None:
        row = _mapped(
            lambda: self._connection.execute(
                "SELECT * FROM classifications WHERE id=?",
                (classification_id,),
            ).fetchone()
        )
        if row is None:
            return None
        aliases = parse_canonical_json(row["aliases_json"])
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) for alias in aliases
        ):
            raise PersistenceError("Stored classification aliases are invalid")
        return ClassificationRecord(
            id=_uuid(row["id"]),
            display_name=str(row["display_name"]),
            normalized_name=str(row["normalized_name"]),
            aliases=tuple(aliases),
            origin=str(row["origin"]),
            created_at=parse_canonical_instant(row["created_at_utc"]),
            updated_at=parse_canonical_instant(row["updated_at_utc"]),
            revision=int(row["revision"]),
        )

    def get_by_normalized_name(
        self,
        normalized_name: str,
    ) -> ClassificationRecord | None:
        row = _mapped(
            lambda: self._connection.execute(
                "SELECT id FROM classifications WHERE normalized_name=?",
                (normalized_name,),
            ).fetchone()
        )
        return None if row is None else self.get(str(row["id"]))

    def list_all(self) -> tuple[ClassificationRecord, ...]:
        rows = _mapped(
            lambda: self._connection.execute(
                "SELECT id FROM classifications "
                "ORDER BY normalized_name,id"
            ).fetchall()
        )
        output = tuple(self.get(str(row["id"])) for row in rows)
        return cast(
            tuple[ClassificationRecord, ...],
            output,
        )


class AIReceiptBindingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_application_key(
        self,
        key: tuple[str, str, str, str, str, str],
    ) -> AIReceiptRecord | None:
        row = _mapped(
            lambda: self._connection.execute(
                "SELECT * FROM ai_application_receipts "
                "WHERE task=? AND canonical_symbol=? AND input_fingerprint=? "
                "AND prompt_version=? AND schema_version=? AND model_config_id=?",
                key,
            ).fetchone()
        )
        return None if row is None else self._receipt_from_row(row)

    def insert_receipt_with_bindings(
        self,
        receipt: AIReceiptRecord,
        bindings: tuple[SecurityClassificationRecord, ...],
    ) -> None:
        if len(bindings) > 3:
            raise PersistenceConflictError()
        _mapped(
            lambda: self._connection.execute(
                "INSERT INTO ai_application_receipts("
                "receipt_id,task,canonical_symbol,security_id,input_fingerprint,"
                "prompt_version,schema_version,model_config_id,result_fingerprint,"
                "status,outcome_summary_json,created_at_utc"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _uuid(receipt.receipt_id),
                    receipt.task,
                    receipt.canonical_symbol,
                    _uuid(receipt.security_id),
                    receipt.input_fingerprint,
                    receipt.prompt_version,
                    receipt.schema_version,
                    receipt.model_config_id,
                    receipt.result_fingerprint,
                    receipt.status,
                    canonical_json(dict(receipt.outcome_summary)),
                    canonical_instant(receipt.created_at),
                ),
            )
        )
        for binding in bindings:
            if binding.ai_receipt_id != receipt.receipt_id:
                raise PersistenceConflictError()
            self._add_binding(binding)

    def add_human_binding(
        self,
        binding: SecurityClassificationRecord,
    ) -> None:
        self._add_binding(binding)

    def _add_binding(self, binding: SecurityClassificationRecord) -> None:
        current_count = _mapped(
            lambda: self._connection.execute(
                "SELECT count(*) FROM security_classifications WHERE security_id=?",
                (binding.security_id,),
            ).fetchone()[0]
        )
        if int(current_count) >= 3:
            raise PersistenceConflictError()
        _mapped(
            lambda: self._connection.execute(
                "INSERT INTO security_classifications("
                "id,security_id,classification_id,source,ai_receipt_id,"
                "confidence_text,evidence_json,evidence_refs_json,"
                "source_request_id,human_protected,created_at_utc,updated_at_utc"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _uuid(binding.id),
                    _uuid(binding.security_id),
                    _uuid(binding.classification_id),
                    binding.source,
                    (
                        _uuid(binding.ai_receipt_id)
                        if binding.ai_receipt_id is not None
                        else None
                    ),
                    (
                        canonical_decimal_text(binding.confidence)
                        if binding.confidence is not None
                        else None
                    ),
                    canonical_json(list(binding.evidence)),
                    canonical_json(list(binding.evidence_refs)),
                    binding.source_request_id,
                    int(binding.human_protected),
                    canonical_instant(binding.created_at),
                    canonical_instant(binding.updated_at),
                ),
            )
        )

    def list_bindings(
        self,
        security_id: str,
    ) -> tuple[SecurityClassificationRecord, ...]:
        rows = _mapped(
            lambda: self._connection.execute(
                "SELECT * FROM security_classifications "
                "WHERE security_id=? ORDER BY created_at_utc,id",
                (security_id,),
            ).fetchall()
        )
        return tuple(self._binding_from_row(row) for row in rows)

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> AIReceiptRecord:
        summary = parse_canonical_json(row["outcome_summary_json"])
        if not isinstance(summary, dict):
            raise PersistenceError("Stored AI outcome is invalid")
        return AIReceiptRecord(
            receipt_id=_uuid(row["receipt_id"]),
            task=str(row["task"]),
            canonical_symbol=str(row["canonical_symbol"]),
            security_id=_uuid(row["security_id"]),
            input_fingerprint=str(row["input_fingerprint"]),
            prompt_version=str(row["prompt_version"]),
            schema_version=str(row["schema_version"]),
            model_config_id=str(row["model_config_id"]),
            result_fingerprint=str(row["result_fingerprint"]),
            status=str(row["status"]),
            outcome_summary=summary,
            created_at=parse_canonical_instant(row["created_at_utc"]),
        )

    @staticmethod
    def _binding_from_row(row: sqlite3.Row) -> SecurityClassificationRecord:
        evidence = parse_canonical_json(row["evidence_json"])
        evidence_refs = parse_canonical_json(row["evidence_refs_json"])
        if not isinstance(evidence, list) or not isinstance(evidence_refs, list):
            raise PersistenceError("Stored binding evidence is invalid")
        return SecurityClassificationRecord(
            id=_uuid(row["id"]),
            security_id=_uuid(row["security_id"]),
            classification_id=_uuid(row["classification_id"]),
            source=str(row["source"]),
            ai_receipt_id=(
                _uuid(row["ai_receipt_id"])
                if row["ai_receipt_id"] is not None
                else None
            ),
            confidence=(
                parse_canonical_decimal(row["confidence_text"])
                if row["confidence_text"] is not None
                else None
            ),
            evidence=tuple(str(item) for item in evidence),
            evidence_refs=tuple(str(item) for item in evidence_refs),
            source_request_id=row["source_request_id"],
            human_protected=bool(row["human_protected"]),
            created_at=parse_canonical_instant(row["created_at_utc"]),
            updated_at=parse_canonical_instant(row["updated_at_utc"]),
        )


class WatchlistRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, watchlist: WatchlistRecord) -> None:
        _mapped(
            lambda: self._connection.execute(
                "INSERT INTO calculation_watchlists("
                "id,display_name,normalized_name,created_at_utc,"
                "updated_at_utc,revision) VALUES (?,?,?,?,?,?)",
                (
                    _uuid(watchlist.id),
                    watchlist.display_name,
                    watchlist.normalized_name,
                    canonical_instant(watchlist.created_at),
                    canonical_instant(watchlist.updated_at),
                    watchlist.revision,
                ),
            )
        )

    def get_for_update(self, watchlist_id: str) -> WatchlistRecord | None:
        row = _mapped(
            lambda: self._connection.execute(
                "SELECT * FROM calculation_watchlists WHERE id=?",
                (watchlist_id,),
            ).fetchone()
        )
        if row is None:
            return None
        membership_rows = _mapped(
            lambda: self._connection.execute(
                "SELECT * FROM watchlist_memberships "
                "WHERE watchlist_id=? ORDER BY created_at_utc,id",
                (watchlist_id,),
            ).fetchall()
        )
        memberships = tuple(
            WatchlistMembershipRecord(
                id=_uuid(item["id"]),
                watchlist_id=_uuid(item["watchlist_id"]),
                security_id=_uuid(item["security_id"]),
                participating_binding_id=_uuid(
                    item["participating_binding_id"]
                ),
                created_at=parse_canonical_instant(item["created_at_utc"]),
                updated_at=parse_canonical_instant(item["updated_at_utc"]),
            )
            for item in membership_rows
        )
        return WatchlistRecord(
            id=_uuid(row["id"]),
            display_name=str(row["display_name"]),
            normalized_name=str(row["normalized_name"]),
            created_at=parse_canonical_instant(row["created_at_utc"]),
            updated_at=parse_canonical_instant(row["updated_at_utc"]),
            revision=int(row["revision"]),
            memberships=memberships,
        )

    def replace_memberships(
        self,
        watchlist_id: str,
        *,
        expected_revision: int,
        memberships: tuple[WatchlistMembershipRecord, ...],
    ) -> None:
        if len(memberships) > 600:
            raise PersistenceConflictError()
        security_ids = [item.security_id for item in memberships]
        if len(security_ids) != len(set(security_ids)):
            raise PersistenceConflictError()
        row = _mapped(
            lambda: self._connection.execute(
                "SELECT revision,updated_at_utc FROM calculation_watchlists WHERE id=?",
                (watchlist_id,),
            ).fetchone()
        )
        if row is None or int(row[0]) != expected_revision:
            raise ConcurrentModificationError()
        for membership in memberships:
            valid = self._binding_exists(membership)
            if valid is None or membership.watchlist_id != watchlist_id:
                raise PersistenceConflictError()
        _mapped(
            lambda: self._connection.execute(
                "DELETE FROM watchlist_memberships WHERE watchlist_id=?",
                (watchlist_id,),
            )
        )
        for membership in memberships:
            self._insert_membership(membership)
        cursor = _mapped(
            lambda: self._connection.execute(
                "UPDATE calculation_watchlists "
                "SET revision=revision+1,updated_at_utc=? "
                "WHERE id=? AND revision=?",
                (
                    canonical_instant(
                        max(
                            (item.updated_at for item in memberships),
                            default=parse_canonical_instant(row[1]),
                        )
                    ),
                    watchlist_id,
                    expected_revision,
                ),
            )
        )
        require_revision_update(cursor.rowcount)

    def _binding_exists(
        self,
        membership: WatchlistMembershipRecord,
    ) -> sqlite3.Row | None:
        return cast(
            "sqlite3.Row | None",
            _mapped(
                lambda: self._connection.execute(
                    "SELECT 1 FROM security_classifications "
                    "WHERE id=? AND security_id=?",
                    (
                        membership.participating_binding_id,
                        membership.security_id,
                    ),
                ).fetchone()
            ),
        )

    def _insert_membership(
        self,
        membership: WatchlistMembershipRecord,
    ) -> None:
        _mapped(
            lambda: self._connection.execute(
                "INSERT INTO watchlist_memberships("
                "id,watchlist_id,security_id,participating_binding_id,"
                "created_at_utc,updated_at_utc) VALUES (?,?,?,?,?,?)",
                (
                    _uuid(membership.id),
                    _uuid(membership.watchlist_id),
                    _uuid(membership.security_id),
                    _uuid(membership.participating_binding_id),
                    canonical_instant(membership.created_at),
                    canonical_instant(membership.updated_at),
                ),
            )
        )
