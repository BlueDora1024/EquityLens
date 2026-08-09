"""Transactional normalized OHLC cache shared by analysis tools."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from stock_toolbox.core.market_data.models import (
    CandleInterval,
    CandleSeries,
    MarketCandle,
)
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.types import (
    canonical_decimal_text,
    canonical_instant,
    parse_canonical_decimal,
    parse_canonical_instant,
)


class SQLiteCandleCache:
    def __init__(
        self,
        factory: SQLiteConnectionFactory,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._factory = factory
        self._clock = clock

    def upsert(self, provider_id: str, series: CandleSeries) -> None:
        provider = provider_id.strip()
        if not provider:
            raise ValueError("provider id must not be blank")
        cached_at = canonical_instant(self._clock())
        rows = tuple(
            (
                provider,
                series.symbol,
                series.interval.value,
                canonical_instant(candle.timestamp),
                "forward",
                1,
                canonical_decimal_text(candle.open),
                canonical_decimal_text(candle.high),
                canonical_decimal_text(candle.low),
                canonical_decimal_text(candle.close),
                candle.volume,
                cached_at,
            )
            for candle in series.candles
        )
        if not rows:
            return
        connection = self._factory.open_writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "INSERT INTO market_candle_cache("
                "provider_id,symbol,interval,timestamp_utc,adjustment,"
                "regular_session,open_text,high_text,low_text,close_text,"
                "volume,cached_at_utc"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(provider_id,symbol,interval,timestamp_utc,"
                "adjustment,regular_session) DO UPDATE SET "
                "open_text=excluded.open_text,high_text=excluded.high_text,"
                "low_text=excluded.low_text,close_text=excluded.close_text,"
                "volume=excluded.volume,cached_at_utc=excluded.cached_at_utc",
                rows,
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def load(
        self,
        provider_id: str,
        symbol: str,
        interval: CandleInterval,
        end_at: datetime,
        limit: int,
    ) -> tuple[MarketCandle, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        connection = self._factory.open_reader()
        try:
            rows = connection.execute(
                "SELECT timestamp_utc,open_text,high_text,low_text,close_text,volume "
                "FROM market_candle_cache "
                "WHERE provider_id=? AND symbol=? AND interval=? "
                "AND adjustment='forward' AND regular_session=1 "
                "AND timestamp_utc<=? "
                "ORDER BY timestamp_utc DESC LIMIT ?",
                (
                    provider_id.strip(),
                    symbol.strip().upper(),
                    interval.value,
                    canonical_instant(end_at),
                    limit,
                ),
            ).fetchall()
        finally:
            connection.close()
        candles = tuple(
            MarketCandle(
                parse_canonical_instant(row["timestamp_utc"]),
                parse_canonical_decimal(row["open_text"]),
                parse_canonical_decimal(row["high_text"]),
                parse_canonical_decimal(row["low_text"]),
                parse_canonical_decimal(row["close_text"]),
                int(row["volume"]),
            )
            for row in reversed(rows)
        )
        return candles

    def covered_through(
        self,
        provider_id: str,
        symbol: str,
        interval: CandleInterval,
    ) -> datetime | None:
        connection = self._factory.open_reader()
        try:
            row = connection.execute(
                "SELECT covered_through_utc FROM market_candle_coverage "
                "WHERE provider_id=? AND symbol=? AND interval=? "
                "AND adjustment='forward' AND regular_session=1",
                (
                    provider_id.strip(),
                    symbol.strip().upper(),
                    interval.value,
                ),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return parse_canonical_instant(row["covered_through_utc"])

    def mark_covered_through(
        self,
        provider_id: str,
        symbol: str,
        interval: CandleInterval,
        end_at: datetime,
    ) -> None:
        provider = provider_id.strip()
        normalized_symbol = symbol.strip().upper()
        if not provider or not normalized_symbol:
            raise ValueError("provider id and symbol must not be blank")
        cached_at = canonical_instant(self._clock())
        connection = self._factory.open_writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO market_candle_coverage("
                "provider_id,symbol,interval,adjustment,regular_session,"
                "covered_through_utc,cached_at_utc"
                ") VALUES (?,?,?,'forward',1,?,?) "
                "ON CONFLICT(provider_id,symbol,interval,adjustment,regular_session) "
                "DO UPDATE SET "
                "covered_through_utc=MAX("
                "market_candle_coverage.covered_through_utc,"
                "excluded.covered_through_utc),"
                "cached_at_utc=excluded.cached_at_utc",
                (
                    provider,
                    normalized_symbol,
                    interval.value,
                    canonical_instant(end_at),
                    cached_at,
                ),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
