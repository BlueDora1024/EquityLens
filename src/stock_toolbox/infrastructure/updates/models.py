"""Immutable update data passed between infrastructure and UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    version: str
    tag: str
    git_sha: str
    architecture: str

    @property
    def short_sha(self) -> str:
        return self.git_sha[:12] if self.git_sha else "unknown"


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    size: int


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    tag: str
    version: str
    title: str
    notes: tuple[str, ...]
    published_at: str
    page_url: str
    archive: ReleaseAsset
    checksum: ReleaseAsset

