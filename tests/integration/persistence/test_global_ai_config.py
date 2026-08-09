from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stock_toolbox.infrastructure.persistence.errors import (
    PersistenceValidationError,
)
from stock_toolbox.infrastructure.persistence.global_ai_config import (
    GlobalAIConfigStore,
)

NOW = datetime(2026, 7, 26, 12, tzinfo=UTC)


def uid(number: int) -> str:
    return f"90000000-0000-4000-8000-{number:012d}"


def store(tmp_path: Path) -> GlobalAIConfigStore:
    identifiers = iter((uid(1), uid(2), uid(3)))
    return GlobalAIConfigStore(
        tmp_path / "Application Support" / "RS Radar" / "RSRadar.config.sqlite3",
        clock=lambda: NOW,
        new_id=lambda: next(identifiers),
    )


def test_save_load_and_read_secret_from_singleton_database(
    tmp_path: Path,
) -> None:
    config_store = store(tmp_path)
    secret = bytearray(b"sk-test-global-config")

    saved = config_store.save(
        base_url="https://api.deepseek.com/",
        model="deepseek-chat",
        timeout_seconds=30,
        max_retries=1,
        api_key=secret,
    )

    assert secret == bytearray(len(secret))
    assert saved.model_config_id == uid(1)
    assert saved.revision == 1
    assert saved.base_url == "https://api.deepseek.com"
    assert saved.model == "deepseek-chat"
    assert config_store.load() == saved
    assert config_store.read_secret(saved.revision) == bytearray(
        b"sk-test-global-config"
    )

    with sqlite3.connect(config_store.database_path) as connection:
        rows = connection.execute(
            "SELECT singleton_id, COUNT(*) FROM global_ai_configuration"
        ).fetchall()
        assert rows == [(1, 1)]


def test_metadata_update_retains_key_and_replacement_is_atomic(
    tmp_path: Path,
) -> None:
    config_store = store(tmp_path)
    first_key = bytearray(b"sk-test-first")
    first = config_store.save(
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=30,
        max_retries=1,
        api_key=first_key,
    )

    second = config_store.save(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-reasoner",
        timeout_seconds=45,
        max_retries=2,
        api_key=None,
        expected_revision=first.revision,
    )

    assert second.model_config_id == uid(2)
    assert second.revision == 2
    assert config_store.read_secret(second.revision) == bytearray(
        b"sk-test-first"
    )
    with pytest.raises(PersistenceValidationError):
        config_store.read_secret(first.revision)

    replacement = bytearray(b"sk-test-replacement")
    third = config_store.save(
        base_url=second.base_url,
        model=second.model,
        timeout_seconds=second.timeout_seconds,
        max_retries=second.max_retries,
        api_key=replacement,
        expected_revision=second.revision,
    )
    assert replacement == bytearray(len(replacement))
    assert third.revision == 3
    assert config_store.read_secret(third.revision) == bytearray(
        b"sk-test-replacement"
    )


def test_save_rejects_missing_key_stale_revision_and_invalid_values(
    tmp_path: Path,
) -> None:
    config_store = store(tmp_path)

    with pytest.raises(PersistenceValidationError):
        config_store.save(
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            timeout_seconds=30,
            max_retries=1,
            api_key=None,
        )

    first = config_store.save(
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=30,
        max_retries=1,
        api_key=bytearray(b"sk-test-valid"),
    )
    with pytest.raises(PersistenceValidationError):
        config_store.save(
            base_url="http://insecure.example",
            model="",
            timeout_seconds=1,
            max_retries=99,
            api_key=bytearray(b"sk-test-invalid"),
            expected_revision=first.revision - 1,
        )

    assert config_store.load() == first


def test_delete_removes_singleton_and_old_revision_cannot_be_read(
    tmp_path: Path,
) -> None:
    config_store = store(tmp_path)
    saved = config_store.save(
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=30,
        max_retries=1,
        api_key=bytearray(b"sk-test-delete"),
    )

    config_store.delete(expected_revision=saved.revision)

    assert config_store.load() is None
    with pytest.raises(PersistenceValidationError):
        config_store.read_secret(saved.revision)


def test_database_and_runtime_files_are_current_user_only(
    tmp_path: Path,
) -> None:
    config_store = store(tmp_path)
    config_store.save(
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=30,
        max_retries=1,
        api_key=bytearray(b"sk-test-permissions"),
    )

    directory_mode = stat.S_IMODE(config_store.database_path.parent.stat().st_mode)
    database_mode = stat.S_IMODE(config_store.database_path.stat().st_mode)
    assert directory_mode == 0o700
    assert database_mode == 0o600
    for suffix in ("-wal", "-shm"):
        runtime_file = Path(f"{config_store.database_path}{suffix}")
        if runtime_file.exists():
            assert stat.S_IMODE(runtime_file.stat().st_mode) == 0o600
