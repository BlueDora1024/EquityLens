"""Immutable DTOs and narrow ports for security import."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from stock_toolbox.core.operations.registry import OperationControl


@dataclass(frozen=True, slots=True)
class AssetHint:
    normalized_type: str
    reliability: str


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    symbol: str
    name: str | None
    market: str
    exchange: str | None
    currency: str | None
    listing_country: str | None
    description: str | None
    asset_hints: tuple[AssetHint, ...]
    business_profile: Mapping[str, Any]
    source_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProviderProfileError:
    symbol: str
    code: str


@dataclass(frozen=True, slots=True)
class ProviderProfilesResult:
    profiles: tuple[ProviderProfile, ...]
    errors: tuple[ProviderProfileError, ...]
    provider_id: str = "provider"


@dataclass(frozen=True, slots=True)
class StoredClassification:
    id: str
    display_name: str
    normalized_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AIClassification:
    canonical_name: str
    existing_classification_id: str | None
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class AICompanyAnalysis:
    eligible: bool
    asset_type: str
    classifications: tuple[AIClassification, ...]


@dataclass(frozen=True, slots=True)
class ValidatedClassification:
    id: str
    binding_id: str
    display_name: str
    normalized_name: str
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class ValidatedSecurityImport:
    id: str
    receipt_id: str
    profile: ProviderProfile
    asset_type: str
    eligibility_source: str
    classifications: tuple[ValidatedClassification, ...]


@dataclass(frozen=True, slots=True)
class ValidatedImportBatch:
    items: tuple[ValidatedSecurityImport, ...]
    created_at: datetime
    provider_id: str


class SecurityProfilesPort(Protocol):
    def get_security_profiles(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> ProviderProfilesResult: ...


class AICompanyAnalysisPort(Protocol):
    def analyze_company(
        self,
        profile: ProviderProfile,
        existing: tuple[StoredClassification, ...],
        *,
        operation_control: OperationControl,
    ) -> AICompanyAnalysis: ...


class SecurityImportStorePort(Protocol):
    def existing_symbols(self, symbols: tuple[str, ...]) -> frozenset[str]: ...

    def list_classifications(self) -> tuple[StoredClassification, ...]: ...

    def commit(
        self,
        batch: ValidatedImportBatch,
        *,
        operation_control: OperationControl,
    ) -> bool: ...


Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]
