"""Daily-close adapter backed by the server-side quant endpoint."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_toolbox.core.market_data.models import (
    CandleInterval,
    DailyBarsDataset,
    DailyBarsProviderPort,
    DailySeriesProgress,
    DailySeriesProgressSink,
    PricePoint,
    PriceSeries,
)
from stock_toolbox.core.market_data.quant import (
    QuantMarketDataPort,
    QuantProgress,
    QuantSeriesRequest,
)
from stock_toolbox.core.operations.registry import OperationControl

_NEW_YORK = ZoneInfo("America/New_York")
SCRIPT_VERSION = "daily-close-quant-v2"
_SCRIPT = 'indicator("Daily close"); plot(close, "close");'


def daily_request_for(
    start_date: date,
    end_date: date,
) -> QuantSeriesRequest:
    return QuantSeriesRequest(
        SCRIPT_VERSION,
        CandleInterval.DAY,
        datetime.combine(start_date, time.min, UTC),
        datetime.combine(end_date, time.max, UTC),
        _SCRIPT,
        ("close",),
    )


class QuantDailyBarsService:
    def __init__(
        self,
        quant: QuantMarketDataPort,
        *,
        etf_fallback: DailyBarsProviderPort | None = None,
    ) -> None:
        self._quant = quant
        self._etf_fallback = etf_fallback

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress: DailySeriesProgressSink | None = None,
    ) -> DailyBarsDataset:
        request = daily_request_for(start_date, end_date)

        def report(item: QuantProgress) -> None:
            if progress is not None:
                progress(
                    DailySeriesProgress(
                        item.completed,
                        item.total,
                        item.current_symbol,
                        item.succeeded,
                        item.failed,
                        item.feedback,
                    )
                )

        result = self._quant.get_quant_series(
            symbols,
            request,
            operation_control=operation_control,
            progress=report,
        )
        series: dict[str, PriceSeries] = {}
        errors = dict(result.errors)
        sources = dict(result.source_by_symbol)
        for symbol, raw in result.series_by_symbol.items():
            closes = raw.values["close"]
            points: dict[date, PricePoint] = {}
            for timestamp, value in zip(raw.timestamps, closes, strict=True):
                market_date = timestamp.astimezone(_NEW_YORK).date()
                if value is None or not start_date <= market_date <= end_date:
                    continue
                close = Decimal(str(value))
                if not close.is_finite() or close <= 0:
                    errors[symbol] = "malformed_quant_response"
                    points.clear()
                    break
                points[market_date] = PricePoint(market_date, close)
            if points:
                series[symbol] = PriceSeries(
                    symbol,
                    tuple(points[key] for key in sorted(points)),
                )
            elif symbol not in errors:
                errors[symbol] = "symbol_unavailable"
        fallback_symbols = tuple(
            symbol
            for symbol in symbols
            if symbol not in series
            and self._etf_fallback is not None
            and (
                symbol in {"SPY.US", "QQQ.US"}
                or errors.get(symbol) == "malformed_quant_response"
            )
        )
        if fallback_symbols:
            assert self._etf_fallback is not None
            fallback = self._etf_fallback.get_daily_series(
                fallback_symbols,
                start_date,
                end_date,
                operation_control=operation_control,
            )
            series.update(fallback.series_by_symbol)
            for symbol in fallback_symbols:
                if symbol in fallback.series_by_symbol:
                    errors.pop(symbol, None)
                    sources[symbol] = fallback.source_by_symbol.get(
                        symbol,
                        fallback.provider_id,
                    )
                else:
                    errors[symbol] = fallback.errors.get(
                        symbol,
                        "benchmark_unavailable",
                    )
        source_ids = {sources[symbol] for symbol in series}
        provider_id = (
            "mixed"
            if len(source_ids) > 1
            else next(iter(source_ids), result.provider_id)
        )
        provider_name = (
            "Longbridge + Yahoo 补充"
            if provider_id == "mixed"
            else (
                fallback.provider_display_name
                if (
                    fallback_symbols
                    and provider_id != result.provider_id
                )
                else result.provider_display_name
            )
        )
        return DailyBarsDataset(
            provider_id,
            provider_name,
            series,
            errors,
            sources,
        )
