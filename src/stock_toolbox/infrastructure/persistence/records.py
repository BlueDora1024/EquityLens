"""Immutable persistence records used by SQLite repositories."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class SecurityRecord:
    id: str
    canonical_symbol: str
    market: str
    display_name: str
    asset_type: str
    eligibility_source: str
    profile_provider_id: str
    exchange: str | None
    currency: str | None
    listing_country: str | None
    description: str | None
    business_profile: Mapping[str, Any]
    source_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    revision: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "business_profile",
            MappingProxyType(dict(self.business_profile)),
        )


@dataclass(frozen=True, slots=True)
class ClassificationRecord:
    id: str
    display_name: str
    normalized_name: str
    aliases: tuple[str, ...]
    origin: str
    created_at: datetime
    updated_at: datetime
    revision: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", tuple(self.aliases))


@dataclass(frozen=True, slots=True)
class AIReceiptRecord:
    receipt_id: str
    task: str
    canonical_symbol: str
    security_id: str
    input_fingerprint: str
    prompt_version: str
    schema_version: str
    model_config_id: str
    result_fingerprint: str
    status: str
    outcome_summary: Mapping[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "outcome_summary",
            MappingProxyType(dict(self.outcome_summary)),
        )

    @property
    def application_key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.task,
            self.canonical_symbol,
            self.input_fingerprint,
            self.prompt_version,
            self.schema_version,
            self.model_config_id,
        )


@dataclass(frozen=True, slots=True)
class SecurityClassificationRecord:
    id: str
    security_id: str
    classification_id: str
    source: str
    ai_receipt_id: str | None
    confidence: Decimal | None
    evidence: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_request_id: str | None
    human_protected: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))


@dataclass(frozen=True, slots=True)
class WatchlistMembershipRecord:
    id: str
    watchlist_id: str
    security_id: str
    participating_binding_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WatchlistRecord:
    id: str
    display_name: str
    normalized_name: str
    created_at: datetime
    updated_at: datetime
    revision: int
    memberships: tuple[WatchlistMembershipRecord, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "memberships", tuple(self.memberships))


@dataclass(frozen=True, slots=True)
class SettingRecord:
    key: str
    value_type: str
    value: Any
    schema_version: int
    updated_at: datetime
