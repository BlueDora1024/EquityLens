"""Discover and download official EquityLens GitHub Releases."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from stock_toolbox.infrastructure.updates.models import ReleaseAsset, ReleaseInfo

RELEASE_API = "https://api.github.com/repos/BlueDora1024/EquityLens/releases/latest"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_MARKDOWN_LINK = re.compile(r"\[([^]]+)]\([^)]*\)")


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(value.strip())
    if match is None:
        return None
    major, minor, patch = map(int, match.groups())
    return major, minor, patch


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_value = _version_tuple(candidate)
    current_value = _version_tuple(current)
    return bool(candidate_value and current_value and candidate_value > current_value)


def asset_names_for(tag: str, architecture: str) -> tuple[str, str]:
    version = tag.removeprefix("v")
    archive = f"EquityLens-v{version}-{architecture}.zip"
    return archive, f"{archive}.sha256"


def summarize_release_notes(body: str, *, limit: int = 4) -> tuple[str, ...]:
    notes: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line.startswith(("- ", "* ")):
            continue
        line = line[2:].strip().replace("**", "").replace("`", "")
        line = _MARKDOWN_LINK.sub(r"\1", line)
        if line and line not in notes:
            notes.append(line)
        if len(notes) >= limit:
            break
    if notes:
        return tuple(notes)
    for raw in body.splitlines():
        line = raw.strip().lstrip("#").strip()
        if line:
            notes.append(line)
        if len(notes) >= limit:
            break
    return tuple(notes)


def _asset(raw: dict[str, Any]) -> ReleaseAsset:
    return ReleaseAsset(
        str(raw.get("name", "")),
        str(raw.get("browser_download_url", "")),
        int(raw.get("size", 0)),
    )


def parse_release(payload: dict[str, Any], *, architecture: str) -> ReleaseInfo:
    tag = str(payload.get("tag_name", ""))
    if payload.get("draft") or payload.get("prerelease") or not _version_tuple(tag):
        raise ValueError("release is not a stable version")
    archive_name, checksum_name = asset_names_for(tag, architecture)
    assets = {
        str(item.get("name", "")): _asset(item)
        for item in payload.get("assets", ())
        if isinstance(item, dict)
    }
    if archive_name not in assets or checksum_name not in assets:
        raise ValueError(f"release does not support {architecture}")
    archive = assets[archive_name]
    checksum = assets[checksum_name]
    if not archive.url.startswith("https://") or not checksum.url.startswith("https://"):
        raise ValueError("release asset URL is not trusted")
    return ReleaseInfo(
        tag=tag,
        version=tag.removeprefix("v"),
        title=str(payload.get("name") or tag),
        notes=summarize_release_notes(str(payload.get("body") or "")),
        published_at=str(payload.get("published_at") or ""),
        page_url=str(payload.get("html_url") or ""),
        archive=archive,
        checksum=checksum,
    )


def parse_sha256(content: str) -> str:
    candidate = content.strip().split()[0].casefold() if content.strip() else ""
    if not re.fullmatch(r"[0-9a-f]{64}", candidate):
        raise ValueError("invalid SHA256 sidecar")
    return candidate


class GitHubUpdateService:
    def __init__(
        self,
        *,
        client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self._client_factory = client_factory or (
            lambda: httpx.Client(
                timeout=httpx.Timeout(20.0, connect=8.0),
                follow_redirects=True,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "EquityLens-Updater",
                },
                trust_env=True,
            )
        )

    def latest_release(self, architecture: str) -> ReleaseInfo:
        with self._client_factory() as client:
            response = client.get(RELEASE_API)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("invalid GitHub response")
        return parse_release(payload, architecture=architecture)

    def download(
        self,
        release: ReleaseInfo,
        destination: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> tuple[Path, str]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._client_factory() as client:
            checksum_response = client.get(release.checksum.url)
            checksum_response.raise_for_status()
            expected = parse_sha256(checksum_response.text)
            with client.stream("GET", release.archive.url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length") or release.archive.size)
                received = 0
                with destination.open("wb") as stream:
                    for chunk in response.iter_bytes():
                        stream.write(chunk)
                        received += len(chunk)
                        if progress is not None:
                            progress(received, total)
        return destination, expected
