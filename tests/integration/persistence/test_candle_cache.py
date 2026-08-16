from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from stock_toolbox.core.market_data.models import (
    CandleInterval,
    CandleSeries,
    MarketCandle,
)
from stock_toolbox.infrastructure.persistence.candle_cache import SQLiteCandleCache
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


def _series(
    symbol: str,
    interval: CandleInterval,
    *,
    start: int,
    count: int,
) -> CandleSeries:
    candles = tuple(
        MarketCandle(
            NOW + timedelta(hours=index),
            Decimal(100 + index),
            Decimal(101 + index),
            Decimal(99 + index),
            Decimal(100 + index),
            1000 + index,
        )
        for index in range(start, start + count)
    )
    return CandleSeries(symbol, interval, candles)


def _cache(tmp_path: Path) -> SQLiteCandleCache:
    database = tmp_path / "cache.sqlite3"
    MigrationRunner(database, app_version="0.4.0", now=lambda: NOW).bootstrap()
    return SQLiteCandleCache(SQLiteConnectionFactory(database), clock=lambda: NOW)


def test_cache_upsert_deduplicates_overlapping_page_boundaries(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.upsert("longbridge", _series("IREN.US", CandleInterval.MIN_30, start=0, count=3))
    cache.upsert("longbridge", _series("IREN.US", CandleInterval.MIN_30, start=2, count=3))

    loaded = cache.load(
        "longbridge",
        "IREN.US",
        CandleInterval.MIN_30,
        NOW + timedelta(hours=10),
        650,
    )

    assert tuple(item.timestamp for item in loaded) == tuple(
        NOW + timedelta(hours=index) for index in range(5)
    )


def test_cache_isolated_by_provider_symbol_interval_and_cutoff(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.upsert("longbridge", _series("IREN.US", CandleInterval.DAY, start=0, count=4))
    cache.upsert("virtual", _series("IREN.US", CandleInterval.DAY, start=0, count=4))
    cache.upsert("longbridge", _series("NVDA.US", CandleInterval.DAY, start=0, count=4))

    loaded = cache.load(
        "longbridge",
        "IREN.US",
        CandleInterval.DAY,
        NOW + timedelta(hours=2),
        650,
    )

    assert len(loaded) == 3
    assert loaded[-1].timestamp == NOW + timedelta(hours=2)


def test_cache_returns_latest_limit_in_ascending_order(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.upsert("longbridge", _series("IREN.US", CandleInterval.WEEK, start=0, count=8))

    loaded = cache.load(
        "longbridge",
        "IREN.US",
        CandleInterval.WEEK,
        NOW + timedelta(hours=20),
        3,
    )

    assert tuple(item.timestamp for item in loaded) == (
        NOW + timedelta(hours=5),
        NOW + timedelta(hours=6),
        NOW + timedelta(hours=7),
    )


def test_cache_persists_completed_bar_coverage_watermark(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    target = NOW + timedelta(days=3)

    assert cache.covered_through("longbridge", "IREN.US", CandleInterval.DAY) is None

    cache.mark_covered_through(
        "longbridge",
        "IREN.US",
        CandleInterval.DAY,
        target,
        requested_count=650,
        returned_count=635,
    )

    assert (
        cache.covered_through(
            "longbridge",
            "IREN.US",
            CandleInterval.DAY,
        )
        == target
    )
    coverage = cache.request_coverage(
        "longbridge", "IREN.US", CandleInterval.DAY
    )
    assert coverage is not None
    assert coverage.requested_count == 650
    assert coverage.returned_count == 635


def test_same_watermark_keeps_the_largest_authoritative_request(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    target = NOW + timedelta(days=3)
    cache.mark_covered_through(
        "longbridge",
        "IREN.US",
        CandleInterval.DAY,
        target,
        requested_count=650,
        returned_count=635,
    )

    cache.mark_covered_through(
        "longbridge",
        "IREN.US",
        CandleInterval.DAY,
        target,
        requested_count=220,
        returned_count=220,
    )

    coverage = cache.request_coverage(
        "longbridge", "IREN.US", CandleInterval.DAY
    )
    assert coverage is not None
    assert coverage.requested_count == 650
    assert coverage.returned_count == 635
