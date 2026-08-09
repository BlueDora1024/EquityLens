"""Persistent cache for compact server-side indicator results."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime

from stock_toolbox.core.market_data.quant import QuantSeries, QuantSeriesRequest
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.types import (
    canonical_instant,
    canonical_json,
    parse_canonical_instant,
)


class SQLiteQuantResultCache:
    def __init__(
        self,
        factory: SQLiteConnectionFactory,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._factory = factory
        self._clock = clock

    def load_many(
        self,
        provider_id: str,
        symbols: tuple[str, ...],
        request: QuantSeriesRequest,
    ) -> Mapping[str, QuantSeries]:
        normalized = tuple(
            dict.fromkeys(
                symbol.strip().upper()
                for symbol in symbols
                if symbol.strip()
            )
        )
        if not normalized:
            return {}
        placeholders = ",".join("?" for _symbol in normalized)
        request_key = self._request_key(provider_id, request)
        connection = self._factory.open_reader()
        try:
            rows = connection.execute(
                "SELECT symbol,result_json FROM quant_result_cache "
                "WHERE provider_id=? AND interval=? AND start_at_utc=? "
                "AND end_at_utc=? AND script_version=? "
                f"AND symbol IN ({placeholders})",
                (*request_key, *normalized),
            ).fetchall()
        finally:
            connection.close()
        return {
            str(row["symbol"]): self._decode(
                str(row["symbol"]),
                request,
                str(row["result_json"]),
            )
            for row in rows
        }

    @staticmethod
    def _decode(
        symbol: str,
        request: QuantSeriesRequest,
        raw_payload: str,
    ) -> QuantSeries:
        payload = json.loads(raw_payload)
        timestamps = tuple(
            parse_canonical_instant(value)
            for value in payload["timestamps"]
        )
        values = {
            name: tuple(
                None if item is None else float(item)
                for item in series
            )
            for name, series in payload["values"].items()
        }
        return QuantSeries(
            symbol,
            request.interval,
            timestamps,
            values,
            int(payload.get("source_count", len(timestamps))),
        )

    def upsert_many(
        self,
        provider_id: str,
        request: QuantSeriesRequest,
        series: tuple[QuantSeries, ...],
    ) -> None:
        if not series:
            return
        cached_at = canonical_instant(self._clock())
        rows = tuple(
            (
                *self._key(provider_id, item.symbol, request),
                canonical_json(
                    {
                        "timestamps": tuple(
                            canonical_instant(timestamp)
                            for timestamp in item.timestamps
                        ),
                        "values": dict(item.values),
                        "source_count": item.source_count,
                    }
                ),
                cached_at,
            )
            for item in series
        )
        connection = self._factory.open_writer()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "INSERT INTO quant_result_cache("
                "provider_id,symbol,interval,start_at_utc,end_at_utc,"
                "script_version,result_json,cached_at_utc"
                ") VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(provider_id,symbol,interval,start_at_utc,"
                "end_at_utc,script_version) DO UPDATE SET "
                "result_json=excluded.result_json,"
                "cached_at_utc=excluded.cached_at_utc",
                rows,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _key(
        provider_id: str,
        symbol: str,
        request: QuantSeriesRequest,
    ) -> tuple[str, str, str, str, str, str]:
        return (
            provider_id.strip(),
            symbol.strip().upper(),
            *SQLiteQuantResultCache._request_key(
                provider_id,
                request,
            )[1:],
        )

    @staticmethod
    def _request_key(
        provider_id: str,
        request: QuantSeriesRequest,
    ) -> tuple[str, str, str, str, str]:
        return (
            provider_id.strip(),
            request.interval.value,
            canonical_instant(request.start_at),
            canonical_instant(request.end_at),
            request.script_version.strip(),
        )
