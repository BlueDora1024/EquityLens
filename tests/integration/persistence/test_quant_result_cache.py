from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.market_data.quant import QuantSeries, QuantSeriesRequest
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.quant_result_cache import (
    SQLiteQuantResultCache,
)


def test_quant_result_cache_round_trips_one_versioned_completed_range(
    tmp_path: Path,
) -> None:
    database = tmp_path / "quant.sqlite3"
    now = lambda: datetime(2026, 7, 29, tzinfo=UTC)
    MigrationRunner(database, app_version="0.6.0", now=now).bootstrap()
    cache = SQLiteQuantResultCache(
        SQLiteConnectionFactory(database),
        clock=now,
    )
    request = QuantSeriesRequest(
        "extreme-v2",
        CandleInterval.MIN_120,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        'indicator("x");',
        ("buy_raw", "sell_raw"),
    )
    series = QuantSeries(
        "NVDA.US",
        CandleInterval.MIN_120,
        (
            datetime(2025, 12, 31, 18, tzinfo=UTC),
            datetime(2025, 12, 31, 20, tzinfo=UTC),
        ),
        {
            "buy_raw": (0.0, 12.5),
            "sell_raw": (1.0, None),
        },
        source_count=650,
    )

    cache.upsert_many("longbridge", request, (series,))

    assert cache.load_many(
        "longbridge",
        ("NVDA.US", "MISSING.US"),
        request,
    ) == {"NVDA.US": series}
    changed = QuantSeriesRequest(
        "extreme-v3",
        request.interval,
        request.start_at,
        request.end_at,
        request.script,
        request.series_names,
    )
    assert cache.load_many("longbridge", ("NVDA.US",), changed) == {}

    connection = SQLiteConnectionFactory(database).open_reader()
    try:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT result_json FROM quant_result_cache "
            "WHERE provider_id=? AND symbol=? AND interval=? "
            "AND start_at_utc=? AND end_at_utc=? AND script_version=?",
            (
                "longbridge",
                "NVDA.US",
                request.interval.value,
                request.start_at.isoformat(),
                request.end_at.isoformat(),
                request.script_version,
            ),
        ).fetchone()
    finally:
        connection.close()
    assert plan is not None
    assert "sqlite_autoindex_quant_result_cache_1" in str(plan["detail"])
