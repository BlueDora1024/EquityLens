"""Atomic cleanup for data that can be fetched or calculated again."""

from __future__ import annotations

import sqlite3

from stock_toolbox.core.operations.storage_guard import CacheCleanupResult
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.uow import (
    SQLiteUnitOfWork,
    map_sqlite_error,
)


class SQLiteRecomputableCacheCleaner:
    def __init__(self, factory: SQLiteConnectionFactory) -> None:
        self._factory = factory

    def clear_recomputable(self) -> CacheCleanupResult:
        try:
            with SQLiteUnitOfWork(self._factory) as uow:
                page_size = int(uow.connection.execute("PRAGMA page_size").fetchone()[0])
                before = int(uow.connection.execute("PRAGMA freelist_count").fetchone()[0])
                uow.connection.execute("DELETE FROM market_candle_cache")
                uow.connection.execute("DELETE FROM market_candle_coverage")
                uow.connection.execute("DELETE FROM market_daily_series_cache")
                uow.connection.execute("DELETE FROM quant_result_cache")
                after = int(uow.connection.execute("PRAGMA freelist_count").fetchone()[0])
                result = CacheCleanupResult(max(0, after - before) * page_size)
                uow.commit()
                return result
        except sqlite3.Error as error:
            raise map_sqlite_error(error) from error
