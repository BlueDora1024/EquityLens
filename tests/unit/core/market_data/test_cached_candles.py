from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from stock_toolbox.core.market_data.cache import CachedCandleService
from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    CandleSeries,
    MarketCandle,
)
from stock_toolbox.core.market_data.service import SharedMarketDataService
from stock_toolbox.core.operations.registry import OperationRegistry

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


def _candles(count: int, *, offset: int = 0) -> tuple[MarketCandle, ...]:
    return tuple(
        MarketCandle(
            NOW + timedelta(minutes=index),
            Decimal(100 + index),
            Decimal(101 + index),
            Decimal(99 + index),
            Decimal(100 + index),
            index,
        )
        for index in range(offset, offset + count)
    )


class MemoryCache:
    def __init__(
        self,
        candles: tuple[MarketCandle, ...],
        *,
        covered_through: datetime | None = None,
    ) -> None:
        self.candles = candles
        self.coverage = covered_through
        self.upserts = 0
        self.coverage_updates = 0

    def load(self, provider_id, symbol, interval, end_at, limit):
        del provider_id, symbol, interval
        return tuple(item for item in self.candles if item.timestamp <= end_at)[-limit:]

    def upsert(self, provider_id, series):
        del provider_id
        self.upserts += 1
        by_time = {item.timestamp: item for item in (*self.candles, *series.candles)}
        self.candles = tuple(by_time[key] for key in sorted(by_time))

    def covered_through(self, provider_id, symbol, interval):
        del provider_id, symbol, interval
        return self.coverage

    def mark_covered_through(self, provider_id, symbol, interval, end_at):
        del provider_id, symbol, interval
        self.coverage_updates += 1
        self.coverage = end_at


class Provider:
    provider_id = "virtual"

    def __init__(self, candles: tuple[MarketCandle, ...]) -> None:
        self.candles = candles
        self.calls = 0
        self.requested_counts: list[int] = []

    def get_candle_series(
        self,
        symbols,
        interval,
        count,
        end_at,
        *,
        operation_control,
    ):
        del end_at, operation_control
        self.calls += 1
        self.requested_counts.append(count)
        return CandleDataset(
            "virtual",
            "Virtual",
            interval,
            {symbol: CandleSeries(symbol, interval, self.candles[-count:]) for symbol in symbols},
            {},
        )

    def get_daily_series(self, *args, **kwargs):
        raise AssertionError("not used")

    def get_security_snapshots(self, *args, **kwargs):
        raise AssertionError("not used")


def _control():
    registry = OperationRegistry(clock=lambda: NOW)
    registry.reserve("op", "test", "test")
    context = registry.begin_reserved("op")
    assert context is not None
    return context.operation_control


def test_full_cache_hit_does_not_call_provider() -> None:
    target = NOW + timedelta(days=1)
    cache = MemoryCache(_candles(650), covered_through=target)
    provider = Provider(_candles(650))
    service = CachedCandleService(SharedMarketDataService(provider), cache, "virtual")

    result = service.get(
        ("IREN.US",),
        CandleInterval.MIN_30,
        650,
        target,
        operation_control=_control(),
    )

    assert provider.calls == 0
    assert result.stats.cache_hits == 1
    assert len(result.dataset.series_by_symbol["IREN.US"].candles) == 650


def test_partial_cache_is_completed_and_persisted() -> None:
    cache = MemoryCache(_candles(500))
    provider = Provider(_candles(650))
    service = CachedCandleService(SharedMarketDataService(provider), cache, "virtual")

    result = service.get(
        ("IREN.US",),
        CandleInterval.DAY,
        650,
        NOW + timedelta(days=1),
        operation_control=_control(),
    )

    assert provider.calls == 1
    assert cache.upserts == 1
    assert result.stats.fetched == 1
    assert len(result.dataset.series_by_symbol["IREN.US"].candles) == 650
    assert cache.coverage == NOW + timedelta(days=1)


def test_full_but_stale_cache_fetches_missing_tail_and_advances_watermark() -> None:
    old_target = NOW + timedelta(days=1)
    new_target = NOW + timedelta(days=2)
    old_candles = _candles(650)
    current_candles = tuple(
        MarketCandle(
            item.timestamp + timedelta(days=1),
            item.open,
            item.high,
            item.low,
            item.close,
            item.volume,
        )
        for item in old_candles
    )
    cache = MemoryCache(old_candles, covered_through=old_target)
    provider = Provider(current_candles)
    service = CachedCandleService(SharedMarketDataService(provider), cache, "virtual")

    result = service.get(
        ("IREN.US",),
        CandleInterval.MIN_30,
        650,
        new_target,
        operation_control=_control(),
    )

    assert provider.calls == 1
    assert provider.requested_counts[0] < 650
    assert cache.coverage == new_target
    assert cache.coverage_updates == 1
    assert result.stats.cache_hits == 0
    assert (
        result.dataset.series_by_symbol["IREN.US"].candles[-1].timestamp > old_candles[-1].timestamp
    )
