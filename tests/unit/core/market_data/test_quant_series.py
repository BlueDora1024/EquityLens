from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.market_data.quant import (
    CachedQuantMarketDataService,
    QuantSeries,
    QuantSeriesDataset,
    QuantSeriesRequest,
)
from stock_toolbox.core.operations.registry import OperationRegistry


def test_quant_request_rejects_duplicate_or_blank_series_names() -> None:
    with pytest.raises(ValueError, match="series"):
        QuantSeriesRequest(
            "turning-v2",
            CandleInterval.MIN_30,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
            "indicator();",
            ("close", "close"),
        )


def test_quant_dataset_is_immutable_and_requires_aligned_series() -> None:
    timestamps = (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    result = QuantSeries(
        "NVDA.US",
        CandleInterval.DAY,
        timestamps,
        {"close": (100.0, 101.0)},
    )
    dataset = QuantSeriesDataset(
        "virtual",
        "Virtual Provider",
        {"NVDA.US": result},
        {},
        cache_hits=1,
        fetched=0,
    )

    assert dataset.series_by_symbol["NVDA.US"].values["close"][-1] == 101.0
    with pytest.raises(TypeError):
        dataset.series_by_symbol["AAPL.US"] = result  # type: ignore[index]

    with pytest.raises(ValueError, match="aligned"):
        QuantSeries(
            "NVDA.US",
            CandleInterval.DAY,
            timestamps,
            {"close": (100.0,)},
        )


def test_quant_series_preserves_source_count_after_retention() -> None:
    timestamps = (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )

    result = QuantSeries(
        "NVDA.US",
        CandleInterval.DAY,
        timestamps,
        {"close": (100.0, 101.0)},
        source_count=650,
    )

    assert result.source_count == 650
    assert result.retained_count == 2
    with pytest.raises(ValueError, match="source count"):
        QuantSeries(
            "NVDA.US",
            CandleInterval.DAY,
            timestamps,
            {"close": (100.0, 101.0)},
            source_count=1,
        )


def test_cached_quant_service_only_fetches_cache_misses() -> None:
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 2, 1, tzinfo=UTC),
        'indicator("rs");',
        ("close",),
    )
    timestamps = (datetime(2026, 1, 2, tzinfo=UTC),)
    cached = QuantSeries("AAPL.US", CandleInterval.DAY, timestamps, {"close": (100.0,)})
    fetched = QuantSeries("NVDA.US", CandleInterval.DAY, timestamps, {"close": (200.0,)})

    class Cache:
        def __init__(self) -> None:
            self.saved: list[str] = []
            self.loaded: tuple[str, ...] = ()

        def load_many(self, provider_id, symbols, active_request):
            assert provider_id == "longbridge"
            assert active_request == request
            self.loaded = symbols
            return {"AAPL.US": cached}

        def upsert_many(self, provider_id, active_request, series):
            assert provider_id == "longbridge"
            assert active_request == request
            self.saved.extend(item.symbol for item in series)

    class Provider:
        def __init__(self) -> None:
            self.symbols = ()

        def get_quant_series(
            self,
            symbols,
            active_request,
            *,
            operation_control,
            progress=None,
        ):
            del operation_control
            del progress
            self.symbols = symbols
            assert active_request == request
            return QuantSeriesDataset(
                "longbridge",
                "Longbridge",
                {"NVDA.US": fetched},
                {},
                fetched=1,
            )

    registry = OperationRegistry(clock=lambda: datetime(2026, 7, 25, tzinfo=UTC))
    registry.reserve("op-cache", "key", "quant")
    context = registry.begin_reserved("op-cache")
    assert context is not None
    cache = Cache()
    provider = Provider()
    service = CachedQuantMarketDataService(
        provider,
        cache,
        "longbridge",
        "Longbridge",
    )

    result = service.get_quant_series(
        ("AAPL.US", "NVDA.US"),
        request,
        operation_control=context.operation_control,
    )

    assert provider.symbols == ("NVDA.US",)
    assert cache.loaded == ("AAPL.US", "NVDA.US")
    assert cache.saved == ["NVDA.US"]
    assert result.cache_hits == 1
    assert result.fetched == 1
