"""Single-user global OpenAI-compatible configuration in SQLite."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stock_toolbox.infrastructure.ai.openai_compatible import normalize_chat_endpoint
from stock_toolbox.infrastructure.persistence.errors import (
    PersistenceDataError,
    PersistenceError,
    PersistenceValidationError,
)
from stock_toolbox.infrastructure.persistence.types import (
    canonical_instant,
    parse_canonical_instant,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS global_ai_configuration (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    model_config_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    timeout_seconds INTEGER NOT NULL CHECK(timeout_seconds BETWEEN 5 AND 180),
    max_retries INTEGER NOT NULL CHECK(max_retries BETWEEN 0 AND 5),
    structured_mode_policy TEXT NOT NULL,
    api_key TEXT NOT NULL CHECK(length(api_key) > 0),
    updated_at_utc TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class GlobalAIConfig:
    model_config_id: str
    revision: int
    base_url: str
    model: str
    timeout_seconds: int
    max_retries: int
    structured_mode_policy: str
    updated_at: datetime


class GlobalAIConfigStore:
    """Own the one mutable AI configuration shared by real app modes."""

    def __init__(
        self,
        database_path: Path,
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
    ) -> None:
        self.database_path = database_path.expanduser().resolve()
        self._clock = clock
        self._new_id = new_id
        self.ensure_schema()

    def load(self) -> GlobalAIConfig | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT model_config_id,revision,base_url,model,"
                    "timeout_seconds,max_retries,structured_mode_policy,"
                    "updated_at_utc FROM global_ai_configuration "
                    "WHERE singleton_id=1"
                ).fetchone()
        except sqlite3.Error as error:
            raise PersistenceError() from error
        return None if row is None else self._map(row)

    def save(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: int,
        max_retries: int,
        api_key: bytearray | None,
        expected_revision: int | None = None,
    ) -> GlobalAIConfig:
        try:
            normalized_url = self._validate(
                base_url,
                model,
                timeout_seconds,
                max_retries,
            )
            key_text = self._decode_key(api_key)
            now = self._clock()
            with self._connect() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    current = connection.execute(
                        "SELECT revision,api_key FROM global_ai_configuration "
                        "WHERE singleton_id=1"
                    ).fetchone()
                    if current is None:
                        if expected_revision is not None or key_text is None:
                            raise PersistenceValidationError()
                        revision = 1
                    else:
                        current_revision = int(current["revision"])
                        if (
                            expected_revision is not None
                            and expected_revision != current_revision
                        ):
                            raise PersistenceValidationError()
                        revision = current_revision + 1
                        if key_text is None:
                            key_text = str(current["api_key"])
                    connection.execute(
                        "INSERT INTO global_ai_configuration("
                        "singleton_id,model_config_id,revision,base_url,model,"
                        "timeout_seconds,max_retries,structured_mode_policy,"
                        "api_key,updated_at_utc"
                        ") VALUES (1,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(singleton_id) DO UPDATE SET "
                        "model_config_id=excluded.model_config_id,"
                        "revision=excluded.revision,"
                        "base_url=excluded.base_url,"
                        "model=excluded.model,"
                        "timeout_seconds=excluded.timeout_seconds,"
                        "max_retries=excluded.max_retries,"
                        "structured_mode_policy=excluded.structured_mode_policy,"
                        "api_key=excluded.api_key,"
                        "updated_at_utc=excluded.updated_at_utc",
                        (
                            self._new_id(),
                            revision,
                            normalized_url,
                            model.strip(),
                            timeout_seconds,
                            max_retries,
                            "auto",
                            key_text,
                            canonical_instant(now),
                        ),
                    )
                    connection.commit()
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
            self._secure_runtime_files()
            loaded = self.load()
            if loaded is None:
                raise PersistenceError()
            return loaded
        except PersistenceError:
            raise
        except (UnicodeDecodeError, sqlite3.Error, ValueError) as error:
            raise PersistenceValidationError() from error
        finally:
            if api_key is not None:
                api_key[:] = b"\x00" * len(api_key)

    def read_secret(self, expected_revision: int) -> bytearray:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT api_key FROM global_ai_configuration "
                    "WHERE singleton_id=1 AND revision=?",
                    (expected_revision,),
                ).fetchone()
        except sqlite3.Error as error:
            raise PersistenceError() from error
        if row is None:
            raise PersistenceValidationError()
        return bytearray(str(row["api_key"]).encode("utf-8"))

    def read(self, reference: str | int) -> bytearray:
        if not isinstance(reference, int):
            raise PersistenceValidationError()
        return self.read_secret(reference)

    def delete(self, *, expected_revision: int | None = None) -> None:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT revision FROM global_ai_configuration "
                    "WHERE singleton_id=1"
                ).fetchone()
                if current is not None and (
                    expected_revision is None
                    or int(current["revision"]) == expected_revision
                ):
                    connection.execute(
                        "DELETE FROM global_ai_configuration WHERE singleton_id=1"
                    )
                elif current is not None:
                    raise PersistenceValidationError()
                connection.commit()
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except PersistenceError:
            raise
        except sqlite3.Error as error:
            raise PersistenceError() from error
        self._secure_runtime_files()

    def ensure_schema(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(self.database_path.parent, 0o700)
            connection = sqlite3.connect(self.database_path, isolation_level=None)
            try:
                connection.executescript(_SCHEMA)
                connection.execute("PRAGMA secure_delete=ON")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations("
                    "version,name,applied_at_utc"
                    ") VALUES (1,'global_ai_configuration',?)",
                    (canonical_instant(self._clock()),),
                )
                quick_check = connection.execute("PRAGMA quick_check").fetchone()
                if quick_check is None or quick_check[0] != "ok":
                    raise PersistenceDataError()
            finally:
                connection.close()
            self._secure_runtime_files()
        except PersistenceError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise PersistenceError() from error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            isolation_level=None,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def _secure_runtime_files(self) -> None:
        os.chmod(self.database_path.parent, 0o700)
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)

    @staticmethod
    def _validate(
        base_url: str,
        model: str,
        timeout_seconds: int,
        max_retries: int,
    ) -> str:
        normalize_chat_endpoint(base_url)
        normalized = base_url.rstrip("/")
        if (
            not model.strip()
            or not 5 <= timeout_seconds <= 180
            or not 0 <= max_retries <= 5
        ):
            raise PersistenceValidationError()
        return normalized

    @staticmethod
    def _decode_key(api_key: bytearray | None) -> str | None:
        if api_key is None:
            return None
        decoded = api_key.decode("utf-8")
        if not decoded or decoded != decoded.strip():
            raise PersistenceValidationError()
        return decoded

    @staticmethod
    def _map(row: sqlite3.Row) -> GlobalAIConfig:
        try:
            revision = int(row["revision"])
            timeout_seconds = int(row["timeout_seconds"])
            max_retries = int(row["max_retries"])
            model_config_id = str(row["model_config_id"])
            base_url = str(row["base_url"])
            model = str(row["model"])
            policy = str(row["structured_mode_policy"])
            if (
                revision <= 0
                or not model_config_id
                or not model
                or policy != "auto"
                or not 5 <= timeout_seconds <= 180
                or not 0 <= max_retries <= 5
            ):
                raise PersistenceDataError()
            normalize_chat_endpoint(base_url)
            return GlobalAIConfig(
                model_config_id,
                revision,
                base_url,
                model,
                timeout_seconds,
                max_retries,
                policy,
                parse_canonical_instant(row["updated_at_utc"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PersistenceDataError() from error
