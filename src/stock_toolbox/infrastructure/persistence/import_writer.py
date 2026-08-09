"""Commit-gated atomic persistence for validated security imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.errors import PersistenceError
from stock_toolbox.infrastructure.persistence.records import (
    AIReceiptRecord,
    ClassificationRecord,
    SecurityClassificationRecord,
    SecurityRecord,
)
from stock_toolbox.infrastructure.persistence.repositories import (
    AIReceiptBindingRepository,
    ClassificationRepository,
    SecurityRepository,
)
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork


class CommitGate(Protocol):
    def try_enter_committing(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ReceiptBindingPlan:
    receipt: AIReceiptRecord
    bindings: tuple[SecurityClassificationRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", tuple(self.bindings))


@dataclass(frozen=True, slots=True)
class ValidatedSecurityImportBatch:
    securities: tuple[SecurityRecord, ...]
    classifications: tuple[ClassificationRecord, ...]
    receipt_plans: tuple[ReceiptBindingPlan, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "securities", tuple(self.securities))
        object.__setattr__(
            self,
            "classifications",
            tuple(self.classifications),
        )
        object.__setattr__(self, "receipt_plans", tuple(self.receipt_plans))


class ImportCommitStatus(StrEnum):
    COMMITTED = "COMMITTED"
    CANCELED_BEFORE_COMMIT = "CANCELED_BEFORE_COMMIT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SecurityImportCommitResult:
    status: ImportCommitStatus
    inserted_security_ids: tuple[str, ...] = ()
    skipped_symbols: tuple[str, ...] = ()
    error_code: str | None = None


class SecurityImportWritePort:
    def __init__(self, factory: SQLiteConnectionFactory) -> None:
        self._factory = factory

    def commit_batch(
        self,
        batch: ValidatedSecurityImportBatch,
        operation_control: CommitGate,
    ) -> SecurityImportCommitResult:
        inserted = []
        skipped = []
        try:
            with SQLiteUnitOfWork(self._factory) as uow:
                securities = SecurityRepository(uow.connection)
                classifications = ClassificationRepository(uow.connection)
                receipts = AIReceiptBindingRepository(uow.connection)
                for security in batch.securities:
                    existing_security = securities.get_by_symbol(security.canonical_symbol)
                    if existing_security is not None:
                        skipped.append(security.canonical_symbol)
                        continue
                    securities.add(security)
                    inserted.append(security.id)
                for classification in batch.classifications:
                    existing_classification = classifications.get_by_normalized_name(
                        classification.normalized_name
                    )
                    if existing_classification is None:
                        classifications.add(classification)
                    elif existing_classification.id != classification.id:
                        raise PersistenceError("Classification identity conflict")
                inserted_set = set(inserted)
                for plan in batch.receipt_plans:
                    if plan.receipt.security_id not in inserted_set:
                        continue
                    receipts.insert_receipt_with_bindings(
                        plan.receipt,
                        plan.bindings,
                    )
                if not operation_control.try_enter_committing():
                    return SecurityImportCommitResult(ImportCommitStatus.CANCELED_BEFORE_COMMIT)
                uow.commit()
            return SecurityImportCommitResult(
                ImportCommitStatus.COMMITTED,
                inserted_security_ids=tuple(inserted),
                skipped_symbols=tuple(skipped),
            )
        except PersistenceError as error:
            return SecurityImportCommitResult(
                ImportCommitStatus.FAILED,
                error_code=error.code,
            )
