"""Storage preflight that protects durable application data."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

READY_FREE_BYTES = 1024**3
CLEANUP_FREE_BYTES = 256 * 1024**2
STORAGE_UNAVAILABLE = "storage_unavailable"


class StorageState(StrEnum):
    READY = "READY"
    WARNING = "WARNING"
    CLEANUP_REQUIRED = "CLEANUP_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class StorageCheck:
    state: StorageState
    free_bytes: int
    cleaned: bool = False
    error_code: str = ""
    reusable_bytes: int = 0

    @property
    def effective_available_bytes(self) -> int:
        return max(0, self.free_bytes) + self.reusable_bytes


@dataclass(frozen=True, slots=True)
class CacheCleanupResult:
    reusable_bytes: int = 0


class RecomputableCacheCleaner(Protocol):
    def clear_recomputable(self) -> CacheCleanupResult: ...


class DiskUsageResult(Protocol):
    @property
    def free(self) -> int: ...


def _disk_usage(path: Path) -> DiskUsageResult:
    return shutil.disk_usage(path)


def evaluate_storage(
    free_bytes: int,
    *,
    cleaned: bool = False,
    reusable_bytes: int = 0,
) -> StorageCheck:
    """Pure threshold evaluation using available bytes."""

    if cleaned:
        if free_bytes + reusable_bytes < CLEANUP_FREE_BYTES:
            return StorageCheck(
                StorageState.BLOCKED,
                free_bytes,
                True,
                STORAGE_UNAVAILABLE,
                reusable_bytes,
            )
        return StorageCheck(
            StorageState.WARNING,
            free_bytes,
            True,
            reusable_bytes=reusable_bytes,
        )
    if free_bytes >= READY_FREE_BYTES:
        return StorageCheck(StorageState.READY, free_bytes)
    if free_bytes >= CLEANUP_FREE_BYTES:
        return StorageCheck(StorageState.WARNING, free_bytes)
    return StorageCheck(StorageState.CLEANUP_REQUIRED, free_bytes)


class StorageGuard:
    def __init__(
        self,
        data_directory: Path,
        cleaner: RecomputableCacheCleaner,
        *,
        disk_usage: Callable[[Path], DiskUsageResult] = _disk_usage,
    ) -> None:
        self._data_directory = data_directory
        self._cleaner = cleaner
        self._disk_usage = disk_usage

    def inspect(self) -> StorageCheck:
        try:
            return evaluate_storage(
                int(self._disk_usage(self._data_directory).free)
            )
        except OSError:
            return StorageCheck(
                StorageState.BLOCKED,
                0,
                error_code=STORAGE_UNAVAILABLE,
            )

    def prepare_run(self) -> StorageCheck:
        initial = self.inspect()
        if initial.state is not StorageState.CLEANUP_REQUIRED:
            return initial
        try:
            cleanup = self._cleaner.clear_recomputable()
        except Exception as error:  # noqa: BLE001 - stable cleanup boundary
            return StorageCheck(
                StorageState.BLOCKED,
                initial.free_bytes,
                error_code=_stable_cleanup_error(error),
            )
        try:
            free_bytes = int(self._disk_usage(self._data_directory).free)
        except OSError:
            return StorageCheck(
                StorageState.BLOCKED,
                -1,
                True,
                STORAGE_UNAVAILABLE,
                cleanup.reusable_bytes,
            )
        return evaluate_storage(
            free_bytes,
            cleaned=True,
            reusable_bytes=cleanup.reusable_bytes,
        )


_PERSISTENCE_CODES = frozenset(
    {
        "concurrent_modification",
        "data_validation_failed",
        "database_busy",
        "database_corrupt",
        "migration_incompatible",
        "persistence_conflict",
        "persistence_data_error",
        "persistence_internal",
        "storage_unavailable",
    }
)


def _stable_cleanup_error(error: Exception) -> str:
    code = str(getattr(error, "code", ""))
    return code if code in _PERSISTENCE_CODES else STORAGE_UNAVAILABLE
