"""Read-only projections used by desktop and CLI master-data workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ClassificationDTO:
    id: str
    display_name: str
    normalized_name: str
    origin: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SecurityBindingDTO:
    id: str
    classification_id: str
    classification_name: str
    source: str


@dataclass(frozen=True, slots=True)
class SecurityDetailDTO:
    id: str
    canonical_symbol: str
    display_name: str
    exchange: str | None
    currency: str | None
    listing_country: str | None
    description: str | None
    business_profile: Mapping[str, Any]
    asset_type: str
    bindings: tuple[SecurityBindingDTO, ...]


@dataclass(frozen=True, slots=True)
class WatchlistMembershipDTO:
    id: str
    security_id: str
    canonical_symbol: str
    company_name: str
    participating_binding_id: str
    participating_classification_id: str
    participating_classification_name: str


@dataclass(frozen=True, slots=True)
class WatchlistDTO:
    id: str
    display_name: str
    revision: int
    memberships: tuple[WatchlistMembershipDTO, ...]
