"""SQLite persistence for exact raw daily close envelopes."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime

from stock_toolbox.core.market_data.models import PricePoint, PriceSeries
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.types import (
    canonical_decimal_text,
    canonical_instant,
    parse_canonical_decimal,
)


class SQLiteDailySeriesCache:
    def __init__(
        self,
        factory: SQLiteConnectionFactory,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._factory = factory
        self._clock = clock

    def load(
        self,
        provider_id: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> PriceSeries | None:
        connection = self._factory.open_reader()
        try:
            row = connection.execute(
                "SELECT points_json FROM market_daily_series_cache "
                "WHERE provider_id=? AND symbol=? AND start_date=? AND end_date=?",
                (
                    provider_id.strip(),
                    symbol.strip().upper(),
                    start_date.isoformat(),
                    end_date.isoformat(),
                ),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        raw = json.loads(str(row["points_json"]))
        return PriceSeries(
            symbol.strip().upper(),
            tuple(
                PricePoint(
                    date.fromisoformat(str(item[0])),
                    parse_canonical_decimal(str(item[1])),
                )
                for item in raw
            ),
        )

    def upsert(
        self,
        provider_id: str,
        series: PriceSeries,
        start_date: date,
        end_date: date,
    ) -> None:
        payload = json.dumps(
            [
                [point.date.isoformat(), canonical_decimal_text(point.close)]
                for point in series.points
            ],
            separators=(",", ":"),
        )
        connection = self._factory.open_writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO market_daily_series_cache("
                "provider_id,symbol,start_date,end_date,points_json,cached_at_utc"
                ") VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(provider_id,symbol,start_date,end_date) DO UPDATE SET "
                "points_json=excluded.points_json,cached_at_utc=excluded.cached_at_utc",
                (
                    provider_id.strip(),
                    series.symbol,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    payload,
                    canonical_instant(self._clock()),
                ),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
