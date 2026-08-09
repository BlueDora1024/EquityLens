"""Non-sensitive business settings repository."""

from __future__ import annotations

import sqlite3

from stock_toolbox.infrastructure.persistence.records import SettingRecord
from stock_toolbox.infrastructure.persistence.repositories import _mapped
from stock_toolbox.infrastructure.persistence.types import (
    canonical_instant,
    canonical_json,
    parse_canonical_instant,
    parse_canonical_json,
)


class SettingsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert_setting(self, setting: SettingRecord) -> None:
        _mapped(
            lambda: self._connection.execute(
                "INSERT INTO settings("
                "key,value_type,value_json,schema_version,updated_at_utc"
                ") VALUES (?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value_type=excluded.value_type,"
                "value_json=excluded.value_json,"
                "schema_version=excluded.schema_version,"
                "updated_at_utc=excluded.updated_at_utc",
                (
                    setting.key,
                    setting.value_type,
                    canonical_json(setting.value),
                    setting.schema_version,
                    canonical_instant(setting.updated_at),
                ),
            )
        )

    def get_setting(self, key: str) -> SettingRecord | None:
        row = _mapped(
            lambda: self._connection.execute(
                "SELECT * FROM settings WHERE key=?",
                (key,),
            ).fetchone()
        )
        if row is None:
            return None
        return SettingRecord(
            key=str(row["key"]),
            value_type=str(row["value_type"]),
            value=parse_canonical_json(row["value_json"]),
            schema_version=int(row["schema_version"]),
            updated_at=parse_canonical_instant(row["updated_at_utc"]),
        )
