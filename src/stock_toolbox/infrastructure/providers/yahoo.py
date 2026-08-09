"""Yahoo Finance raw-market-data fallback for personal review workflows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from typing import Any, cast
from zoneinfo import ZoneInfo

from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    CandleSeries,
    DailyBarsDataset,
    MarketCandle,
    PricePoint,
    PriceSeries,
    SnapshotDataset,
)
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.core.operations.registry import OperationControl

_NEW_YORK = ZoneInfo("America/New_York")
_INTRADAY = frozenset(
    {
        CandleInterval.MIN_30,
        CandleInterval.MIN_60,
        CandleInterval.MIN_120,
        CandleInterval.MIN_240,
    }
)
_YAHOO_INTERVAL = {
    CandleInterval.MIN_30: "30m",
    CandleInterval.MIN_60: "1h",
    CandleInterval.MIN_120: "1h",
    CandleInterval.MIN_240: "1h",
    CandleInterval.DAY: "1d",
    CandleInterval.WEEK: "1wk",
}
_AGGREGATION = {
    CandleInterval.MIN_120: 2,
    CandleInterval.MIN_240: 4,
}
_INTRADAY_RETENTION = {
    CandleInterval.MIN_30: timedelta(days=60),
    CandleInterval.MIN_60: timedelta(days=730),
    CandleInterval.MIN_120: timedelta(days=730),
    CandleInterval.MIN_240: timedelta(days=730),
}
_INTRADAY_PERIOD = {
    CandleInterval.MIN_30: "60d",
    CandleInterval.MIN_60: "2y",
    CandleInterval.MIN_120: "2y",
    CandleInterval.MIN_240: "2y",
}

Download = Callable[..., Any]


class YahooFallbackProvider:
    provider_id = "yahoo"
    provider_display_name = "Yahoo 备用数据"

    def __init__(
        self,
        *,
        download: Download | None = None,
        proxy_url: str = "",
        timeout_seconds: float = 10.0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._download = download or _production_download(proxy_url)
        self._timeout = timeout_seconds
        self._now = now
        self._hourly_cache: dict[
            tuple[tuple[str, ...], datetime],
            CandleDataset,
        ] = {}

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress: object = None,
    ) -> DailyBarsDataset:
        del progress
        normalized = _normalize_symbols(symbols)
        if operation_control.cancellation_requested():
            return _daily_errors(normalized, "canceled")
        yahoo_symbols = tuple(_to_yahoo(symbol) for symbol in normalized)
        try:
            frame = self._download(
                tickers=yahoo_symbols,
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=True,
                actions=False,
                group_by="ticker",
                threads=min(4, len(yahoo_symbols)),
                progress=False,
                timeout=self._timeout,
            )
        except Exception as error:  # noqa: BLE001 - external library boundary
            return _daily_errors(normalized, _error_code(error))
        if operation_control.cancellation_requested():
            return _daily_errors(normalized, "canceled")

        ready: dict[str, PriceSeries] = {}
        errors: dict[str, str] = {}
        for symbol, yahoo_symbol in zip(normalized, yahoo_symbols, strict=True):
            points = tuple(
                PricePoint(timestamp.date(), close)
                for timestamp, _open, _high, _low, close, _volume in _rows(
                    frame,
                    yahoo_symbol,
                )
                if start_date <= timestamp.date() <= end_date
            )
            if points:
                ready[symbol] = PriceSeries(symbol, points)
            else:
                errors[symbol] = FailureCode.DATA_UNAVAILABLE.value
        return DailyBarsDataset(
            self.provider_id,
            self.provider_display_name,
            ready,
            errors,
            {symbol: self.provider_id for symbol in ready},
        )

    def get_candle_series(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CandleDataset:
        normalized = _normalize_symbols(symbols)
        retention = _INTRADAY_RETENTION.get(interval)
        if (
            retention is not None
            and self._now() - end_at.astimezone(UTC) > retention
        ):
            return _candle_errors(
                normalized,
                interval,
                "yahoo_intraday_history_limited",
            )
        if operation_control.cancellation_requested():
            return _candle_errors(normalized, interval, "canceled")

        hourly_family = interval in {
            CandleInterval.MIN_60,
            CandleInterval.MIN_120,
            CandleInterval.MIN_240,
        }
        base = (
            self._hourly(normalized, end_at, operation_control)
            if hourly_family
            else self._candles(normalized, interval, count, end_at)
        )
        if interval is CandleInterval.MIN_60:
            return _trim_candle_dataset(base, interval, count, normalized)
        if interval not in _AGGREGATION:
            return base
        factor = _AGGREGATION[interval]
        ready = {
            symbol: CandleSeries(
                symbol,
                interval,
                _aggregate(series.candles, factor)[-count:],
            )
            for symbol, series in base.series_by_symbol.items()
        }
        errors = dict(base.errors)
        for symbol in normalized:
            if symbol not in ready:
                errors.setdefault(symbol, FailureCode.DATA_UNAVAILABLE.value)
        return CandleDataset(
            self.provider_id,
            self.provider_display_name,
            interval,
            ready,
            errors,
            {symbol: self.provider_id for symbol in ready},
        )

    def get_security_snapshots(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> SnapshotDataset:
        """Satisfy the screening port while keeping Yahoo a history-only fallback."""

        normalized = _normalize_symbols(symbols)
        code = (
            "canceled"
            if operation_control.cancellation_requested()
            else FailureCode.DATA_UNAVAILABLE.value
        )
        return SnapshotDataset(
            self.provider_id,
            self.provider_display_name,
            {},
            {symbol: code for symbol in normalized},
        )

    def _hourly(
        self,
        symbols: tuple[str, ...],
        end_at: datetime,
        operation_control: OperationControl,
    ) -> CandleDataset:
        key = (symbols, end_at)
        cached = self._hourly_cache.get(key)
        if cached is None:
            cached = self._candles(
                symbols,
                CandleInterval.MIN_60,
                10_000,
                end_at,
            )
            if operation_control.cancellation_requested():
                return _candle_errors(
                    symbols,
                    CandleInterval.MIN_60,
                    "canceled",
                )
            self._hourly_cache[key] = cached
        return cached

    def _candles(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
    ) -> CandleDataset:
        yahoo_symbols = tuple(_to_yahoo(symbol) for symbol in symbols)
        end_date = end_at.astimezone(_NEW_YORK).date()
        request_range = (
            {"period": _INTRADAY_PERIOD[interval]}
            if interval in _INTRADAY
            else {
                "start": (
                    end_date
                    - timedelta(
                        days=(
                            max(28, count * 8)
                            if interval is CandleInterval.WEEK
                            else max(14, count * 3)
                        )
                    )
                ).isoformat(),
                "end": (end_date + timedelta(days=1)).isoformat(),
            }
        )
        try:
            frame = self._download(
                tickers=yahoo_symbols,
                **request_range,
                interval=_YAHOO_INTERVAL[interval],
                auto_adjust=True,
                actions=False,
                group_by="ticker",
                threads=min(4, len(yahoo_symbols)),
                progress=False,
                timeout=self._timeout,
            )
        except Exception as error:  # noqa: BLE001 - external library boundary
            return _candle_errors(symbols, interval, _error_code(error))

        ready: dict[str, CandleSeries] = {}
        errors: dict[str, str] = {}
        for symbol, yahoo_symbol in zip(symbols, yahoo_symbols, strict=True):
            candles = tuple(
                MarketCandle(timestamp, open_, high, low, close, volume)
                for timestamp, open_, high, low, close, volume in _rows(
                    frame,
                    yahoo_symbol,
                )
                if timestamp.astimezone(UTC) <= end_at.astimezone(UTC)
            )[-count:]
            if candles:
                ready[symbol] = CandleSeries(symbol, interval, candles)
            else:
                errors[symbol] = FailureCode.DATA_UNAVAILABLE.value
        return CandleDataset(
            self.provider_id,
            self.provider_display_name,
            interval,
            ready,
            errors,
            {symbol: self.provider_id for symbol in ready},
        )


def _production_download(proxy_url: str) -> Download:
    yf = import_module("yfinance")

    yf.config.network.proxy = proxy_url or None
    yf.config.network.retries = 0
    return cast(Download, yf.download)


def _normalize_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))


def _to_yahoo(symbol: str) -> str:
    return symbol.removesuffix(".US").replace(".", "-")


def _rows(
    frame: Any,
    yahoo_symbol: str,
) -> tuple[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int], ...]:
    try:
        part = (
            frame[yahoo_symbol]
            if yahoo_symbol in frame.columns.get_level_values(0)
            else frame.xs(yahoo_symbol, axis=1, level=1)
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        part = frame
    output = []
    for index, row in part.iterrows():
        try:
            values = tuple(Decimal(str(row[name])) for name in ("Open", "High", "Low", "Close"))
            if any(not value.is_finite() for value in values):
                continue
            timestamp = index.to_pydatetime()
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=_NEW_YORK)
            output.append(
                (
                    timestamp,
                    values[0],
                    values[1],
                    values[2],
                    values[3],
                    int(row["Volume"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(output)


def _aggregate(
    candles: tuple[MarketCandle, ...],
    factor: int,
) -> tuple[MarketCandle, ...]:
    by_day: dict[date, list[MarketCandle]] = defaultdict(list)
    for candle in candles:
        by_day[candle.timestamp.astimezone(_NEW_YORK).date()].append(candle)
    output = []
    for day in sorted(by_day):
        values = by_day[day]
        for offset in range(0, len(values), factor):
            chunk = values[offset : offset + factor]
            if len(chunk) != factor:
                continue
            output.append(
                MarketCandle(
                    chunk[-1].timestamp,
                    chunk[0].open,
                    max(item.high for item in chunk),
                    min(item.low for item in chunk),
                    chunk[-1].close,
                    sum(item.volume for item in chunk),
                )
            )
    return tuple(output)


def _trim_candle_dataset(
    dataset: CandleDataset,
    interval: CandleInterval,
    count: int,
    symbols: tuple[str, ...],
) -> CandleDataset:
    ready = {
        symbol: CandleSeries(
            symbol,
            interval,
            series.candles[-count:],
        )
        for symbol, series in dataset.series_by_symbol.items()
        if series.candles
    }
    errors = dict(dataset.errors)
    for symbol in symbols:
        if symbol not in ready:
            errors.setdefault(symbol, FailureCode.DATA_UNAVAILABLE.value)
    return CandleDataset(
        dataset.provider_id,
        dataset.provider_display_name,
        interval,
        ready,
        errors,
        dataset.source_by_symbol,
    )


def _error_code(error: Exception) -> str:
    text = str(error).casefold()
    if "rate" in text or "too many requests" in text or "429" in text:
        return FailureCode.RATE_LIMITED.value
    if isinstance(error, TimeoutError) or "timeout" in text or "timed out" in text:
        return FailureCode.TIMEOUT.value
    return FailureCode.NETWORK_ERROR.value


def _daily_errors(
    symbols: tuple[str, ...],
    code: str,
) -> DailyBarsDataset:
    return DailyBarsDataset(
        "yahoo",
        "Yahoo 备用数据",
        {},
        {symbol: code for symbol in symbols},
    )


def _candle_errors(
    symbols: tuple[str, ...],
    interval: CandleInterval,
    code: str,
) -> CandleDataset:
    return CandleDataset(
        "yahoo",
        "Yahoo 备用数据",
        interval,
        {},
        {symbol: code for symbol in symbols},
    )
