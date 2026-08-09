"""Immutable provider-independent daily market data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.core.operations.run_feedback import RunFeedback


@dataclass(frozen=True, slots=True)
class PricePoint:
    date: date
    close: Decimal


@dataclass(frozen=True, slots=True)
class PriceSeries:
    symbol: str
    points: tuple[PricePoint, ...]

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        object.__setattr__(self, "points", tuple(self.points))


@dataclass(frozen=True, slots=True)
class DailyBarsDataset:
    provider_id: str
    provider_display_name: str
    series_by_symbol: Mapping[str, PriceSeries]
    errors: Mapping[str, str]
    source_by_symbol: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id must not be blank")
        object.__setattr__(
            self,
            "series_by_symbol",
            MappingProxyType(dict(self.series_by_symbol)),
        )
        object.__setattr__(self, "errors", MappingProxyType(dict(self.errors)))
        object.__setattr__(
            self,
            "source_by_symbol",
            MappingProxyType(
                dict(self.source_by_symbol)
                or {
                    symbol: self.provider_id
                    for symbol in self.series_by_symbol
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class DailySeriesProgress:
    completed: int
    total: int
    current_symbol: str | None = None
    succeeded: int = 0
    failed: int = 0
    feedback: RunFeedback | None = None


DailySeriesProgressSink = Callable[[DailySeriesProgress], None]


class DailyBarsProviderPort(Protocol):
    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress: DailySeriesProgressSink | None = None,
    ) -> DailyBarsDataset: ...


class CandleInterval(StrEnum):
    MIN_30 = "30m"
    MIN_60 = "60m"
    MIN_120 = "120m"
    MIN_240 = "240m"
    DAY = "1d"
    WEEK = "1w"


@dataclass(frozen=True, slots=True)
class MarketCandle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        prices = (self.open, self.high, self.low, self.close)
        if (
            self.timestamp.tzinfo is None
            or any(not value.is_finite() or value <= 0 for value in prices)
            or self.high < max(self.open, self.close, self.low)
            or self.low > min(self.open, self.close, self.high)
        ):
            raise ValueError("invalid OHLC candle")
        if self.volume < 0:
            raise ValueError("volume must not be negative")


@dataclass(frozen=True, slots=True)
class CandleSeries:
    symbol: str
    interval: CandleInterval
    candles: tuple[MarketCandle, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol must not be blank")
        candles = tuple(self.candles)
        if any(
            current.timestamp >= following.timestamp
            for current, following in pairwise(candles)
        ):
            raise ValueError("candles must be strictly ordered")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "candles", candles)


@dataclass(frozen=True, slots=True)
class CandleDataset:
    provider_id: str
    provider_display_name: str
    interval: CandleInterval
    series_by_symbol: Mapping[str, CandleSeries]
    errors: Mapping[str, str]
    source_by_symbol: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "series_by_symbol",
            MappingProxyType(dict(self.series_by_symbol)),
        )
        object.__setattr__(self, "errors", MappingProxyType(dict(self.errors)))
        object.__setattr__(
            self,
            "source_by_symbol",
            MappingProxyType(
                dict(self.source_by_symbol)
                or {
                    symbol: self.provider_id
                    for symbol in self.series_by_symbol
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class SecuritySnapshot:
    symbol: str
    last_price: Decimal | None
    total_market_value: Decimal | None


@dataclass(frozen=True, slots=True)
class SnapshotDataset:
    provider_id: str
    provider_display_name: str
    snapshots_by_symbol: Mapping[str, SecuritySnapshot]
    errors: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshots_by_symbol",
            MappingProxyType(dict(self.snapshots_by_symbol)),
        )
        object.__setattr__(self, "errors", MappingProxyType(dict(self.errors)))


@runtime_checkable
class ScreeningMarketDataPort(DailyBarsProviderPort, Protocol):
    def get_candle_series(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CandleDataset: ...

    def get_security_snapshots(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> SnapshotDataset: ...
