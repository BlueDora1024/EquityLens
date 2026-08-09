"""Provider health and capacity values shared by settings and analyses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    provider_id: str
    display_name: str
    configured: bool = True

    def __post_init__(self) -> None:
        provider_id = self.provider_id.strip().casefold()
        display_name = self.display_name.strip()
        if not provider_id or not display_name:
            raise ValueError("provider identity must not be blank")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "display_name", display_name)


@dataclass(frozen=True, slots=True)
class HistoryQuotaSnapshot:
    used: int
    remaining: int
    reusable_symbols: frozenset[str]

    def __post_init__(self) -> None:
        if self.used < 0 or self.remaining < 0:
            raise ValueError("history quota cannot be negative")
        object.__setattr__(
            self,
            "reusable_symbols",
            frozenset(
                symbol.strip().upper()
                for symbol in self.reusable_symbols
                if symbol.strip()
            ),
        )

    @property
    def total(self) -> int:
        return self.used + self.remaining


@dataclass(frozen=True, slots=True)
class ProviderQualityResult:
    provider_id: str
    ok: bool
    code: str
    completed_checks: tuple[str, ...]
    details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider_id = self.provider_id.strip().casefold()
        code = self.code.strip()
        if not provider_id or not code:
            raise ValueError("provider quality identity must not be blank")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(
            self,
            "completed_checks",
            tuple(
                dict.fromkeys(
                    check.strip()
                    for check in self.completed_checks
                    if check.strip()
                )
            ),
        )
        object.__setattr__(self, "details", tuple(self.details))
