from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import pytest

from stock_toolbox.core.operations.storage_guard import (
    CLEANUP_FREE_BYTES,
    READY_FREE_BYTES,
    CacheCleanupResult,
    StorageGuard,
    StorageState,
    evaluate_storage,
)
from stock_toolbox.infrastructure.persistence.errors import DatabaseBusyError


@pytest.mark.parametrize(
    ("free_bytes", "expected"),
    [
        (READY_FREE_BYTES, StorageState.READY),
        (READY_FREE_BYTES - 1, StorageState.WARNING),
        (CLEANUP_FREE_BYTES, StorageState.WARNING),
        (CLEANUP_FREE_BYTES - 1, StorageState.CLEANUP_REQUIRED),
        (0, StorageState.CLEANUP_REQUIRED),
    ],
)
def test_storage_thresholds_use_exact_free_byte_boundaries(
    free_bytes: int,
    expected: StorageState,
) -> None:
    check = evaluate_storage(free_bytes)

    assert check.state is expected
    assert check.free_bytes == free_bytes
    assert check.cleaned is False
    assert check.error_code == ""


def test_cleanup_rechecks_once_and_becomes_warning_when_space_recovers(
    tmp_path: Path,
) -> None:
    cleaner = Cleaner()
    disk_usage = DiskUsage(
        CLEANUP_FREE_BYTES - 1,
        CLEANUP_FREE_BYTES,
    )

    check = StorageGuard(
        tmp_path,
        cleaner,
        disk_usage=disk_usage,
    ).prepare_run()

    assert check.state is StorageState.WARNING
    assert check.free_bytes == CLEANUP_FREE_BYTES
    assert check.cleaned is True
    assert check.reusable_bytes == 0
    assert check.effective_available_bytes == CLEANUP_FREE_BYTES
    assert cleaner.calls == 1
    assert disk_usage.calls == 2


def test_cleanup_rechecks_once_and_blocks_when_space_stays_low(
    tmp_path: Path,
) -> None:
    cleaner = Cleaner()
    disk_usage = DiskUsage(
        CLEANUP_FREE_BYTES - 1,
        CLEANUP_FREE_BYTES - 2,
    )

    check = StorageGuard(
        tmp_path,
        cleaner,
        disk_usage=disk_usage,
    ).prepare_run()

    assert check.state is StorageState.BLOCKED
    assert check.free_bytes == CLEANUP_FREE_BYTES - 2
    assert check.cleaned is True
    assert check.error_code == "storage_unavailable"
    assert cleaner.calls == 1
    assert disk_usage.calls == 2


def test_disk_usage_os_error_is_a_stable_blocked_check(
    tmp_path: Path,
) -> None:
    def unavailable(_path: Path) -> object:
        raise OSError("sensitive operating system detail")

    check = StorageGuard(
        tmp_path,
        Cleaner(),
        disk_usage=unavailable,
    ).prepare_run()

    assert check.state is StorageState.BLOCKED
    assert check.error_code == "storage_unavailable"
    assert "sensitive" not in repr(check)


def test_reusable_sqlite_capacity_allows_run_after_cleanup(
    tmp_path: Path,
) -> None:
    reusable_bytes = 16 * 1024**2
    physical_free = CLEANUP_FREE_BYTES - reusable_bytes
    cleaner = Cleaner(reusable_bytes)

    check = StorageGuard(
        tmp_path,
        cleaner,
        disk_usage=DiskUsage(
            CLEANUP_FREE_BYTES - 1,
            physical_free,
        ),
    ).prepare_run()

    assert check.state is StorageState.WARNING
    assert check.free_bytes == physical_free
    assert check.reusable_bytes == reusable_bytes
    assert check.effective_available_bytes == CLEANUP_FREE_BYTES
    assert check.cleaned is True


def test_combined_capacity_below_cleanup_threshold_stays_blocked(
    tmp_path: Path,
) -> None:
    cleaner = Cleaner(100)

    check = StorageGuard(
        tmp_path,
        cleaner,
        disk_usage=DiskUsage(
            CLEANUP_FREE_BYTES - 1,
            CLEANUP_FREE_BYTES - 101,
        ),
    ).prepare_run()

    assert check.state is StorageState.BLOCKED
    assert check.effective_available_bytes == CLEANUP_FREE_BYTES - 1


def test_cleaner_failure_preserves_initial_free_and_persistence_code(
    tmp_path: Path,
) -> None:
    initial_free = CLEANUP_FREE_BYTES - 1

    check = StorageGuard(
        tmp_path,
        FailingCleaner(DatabaseBusyError()),
        disk_usage=DiskUsage(initial_free),
    ).prepare_run()

    assert check.state is StorageState.BLOCKED
    assert check.free_bytes == initial_free
    assert check.reusable_bytes == 0
    assert check.cleaned is False
    assert check.error_code == "database_busy"


def test_post_cleanup_disk_error_retains_reusable_capacity(
    tmp_path: Path,
) -> None:
    initial_free = CLEANUP_FREE_BYTES - 1
    cleaner = Cleaner(4096)

    def usage(path: Path) -> object:
        if not hasattr(usage, "called"):
            usage.called = True
            return DiskUsage._Usage(0, 0, initial_free)
        raise OSError(f"cannot inspect {path}")

    check = StorageGuard(
        tmp_path,
        cleaner,
        disk_usage=usage,
    ).prepare_run()

    assert check.state is StorageState.BLOCKED
    assert check.free_bytes == -1
    assert check.reusable_bytes == 4096
    assert check.cleaned is True
    assert check.error_code == "storage_unavailable"


def test_inspection_never_cleans_before_a_run_is_requested(
    tmp_path: Path,
) -> None:
    cleaner = Cleaner()

    check = StorageGuard(
        tmp_path,
        cleaner,
        disk_usage=DiskUsage(CLEANUP_FREE_BYTES - 1),
    ).inspect()

    assert check.state is StorageState.CLEANUP_REQUIRED
    assert cleaner.calls == 0


class Cleaner:
    def __init__(self, reusable_bytes: int = 0) -> None:
        self.calls = 0
        self.reusable_bytes = reusable_bytes

    def clear_recomputable(self) -> CacheCleanupResult:
        self.calls += 1
        return CacheCleanupResult(self.reusable_bytes)


class FailingCleaner:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def clear_recomputable(self) -> CacheCleanupResult:
        raise self.error


class DiskUsage:
    _Usage = namedtuple("usage", "total used free")

    def __init__(self, *free_bytes: int) -> None:
        self._values = iter(free_bytes)
        self.calls = 0

    def __call__(self, _path: Path) -> object:
        self.calls += 1
        return self._Usage(0, 0, next(self._values))
