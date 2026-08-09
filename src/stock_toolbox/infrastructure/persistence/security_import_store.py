"""Map application import DTOs to the atomic SQLite import writer."""

from __future__ import annotations

from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.core.securities.models import (
    StoredClassification,
    ValidatedImportBatch,
)
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.import_writer import (
    ImportCommitStatus,
    ReceiptBindingPlan,
    SecurityImportWritePort,
    ValidatedSecurityImportBatch,
)
from stock_toolbox.infrastructure.persistence.records import (
    AIReceiptRecord,
    ClassificationRecord,
    SecurityClassificationRecord,
    SecurityRecord,
)
from stock_toolbox.infrastructure.persistence.repositories import (
    ClassificationRepository,
    SecurityRepository,
)
from stock_toolbox.infrastructure.persistence.uow import SQLiteUnitOfWork


class PersistentSecurityImportStore:
    def __init__(self, factory: SQLiteConnectionFactory) -> None:
        self._factory = factory

    def existing_symbols(self, symbols: tuple[str, ...]) -> frozenset[str]:
        with SQLiteUnitOfWork(self._factory) as uow:
            repository = SecurityRepository(uow.connection)
            return frozenset(
                symbol
                for symbol in symbols
                if repository.get_by_symbol(symbol) is not None
            )

    def list_classifications(self) -> tuple[StoredClassification, ...]:
        with SQLiteUnitOfWork(self._factory) as uow:
            return tuple(
                StoredClassification(
                    item.id,
                    item.display_name,
                    item.normalized_name,
                    item.aliases,
                )
                for item in ClassificationRepository(
                    uow.connection
                ).list_all()
            )

    def commit(
        self,
        batch: ValidatedImportBatch,
        *,
        operation_control: OperationControl,
    ) -> bool:
        classifications: dict[str, ClassificationRecord] = {}
        securities: list[SecurityRecord] = []
        plans: list[ReceiptBindingPlan] = []
        for item in batch.items:
            securities.append(
                SecurityRecord(
                    id=item.id,
                    canonical_symbol=item.profile.symbol,
                    market=item.profile.market,
                    display_name=item.profile.name or item.profile.symbol,
                    asset_type=item.asset_type,
                    eligibility_source=item.eligibility_source,
                    profile_provider_id=batch.provider_id,
                    exchange=item.profile.exchange,
                    currency=item.profile.currency,
                    listing_country=item.profile.listing_country,
                    description=item.profile.description,
                    business_profile=item.profile.business_profile,
                    source_updated_at=item.profile.source_updated_at,
                    created_at=batch.created_at,
                    updated_at=batch.created_at,
                    revision=0,
                )
            )
            bindings = []
            for classification in item.classifications:
                classifications.setdefault(
                    classification.id,
                    ClassificationRecord(
                        id=classification.id,
                        display_name=classification.display_name,
                        normalized_name=classification.normalized_name,
                        aliases=(),
                        origin="AI",
                        created_at=batch.created_at,
                        updated_at=batch.created_at,
                        revision=0,
                    ),
                )
                bindings.append(
                    SecurityClassificationRecord(
                        id=classification.binding_id,
                        security_id=item.id,
                        classification_id=classification.id,
                        source="AI",
                        ai_receipt_id=item.receipt_id,
                        confidence=classification.confidence,
                        evidence=(),
                        evidence_refs=(),
                        source_request_id=item.receipt_id,
                        human_protected=False,
                        created_at=batch.created_at,
                        updated_at=batch.created_at,
                    )
                )
            if bindings:
                receipt = AIReceiptRecord(
                    receipt_id=item.receipt_id,
                    task="business_classification",
                    canonical_symbol=item.profile.symbol,
                    security_id=item.id,
                    input_fingerprint=f"import:{item.profile.symbol}",
                    prompt_version="business-classification-v3",
                    schema_version="ai-classification-v1",
                    model_config_id="global-ai-config",
                    result_fingerprint=(
                        "classifications:"
                        + ",".join(
                            binding.classification_id for binding in bindings
                        )
                    ),
                    status="APPLIED",
                    outcome_summary={
                        "classification_count": len(bindings),
                    },
                    created_at=batch.created_at,
                )
                plans.append(ReceiptBindingPlan(receipt, tuple(bindings)))
        result = SecurityImportWritePort(self._factory).commit_batch(
            ValidatedSecurityImportBatch(
                tuple(securities),
                tuple(classifications.values()),
                tuple(plans),
            ),
            operation_control,
        )
        return result.status is ImportCommitStatus.COMMITTED
