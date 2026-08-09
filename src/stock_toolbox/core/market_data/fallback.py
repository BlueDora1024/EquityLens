"""Small provider-independent rules for an explicit market-data fallback."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    DailyBarsDataset,
    DailyBarsProviderPort,
    DailySeriesProgressSink,
)
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.core.operations.registry import OperationControl

_ELIGIBLE_FAILURES = frozenset(
    {
        FailureCode.TIMEOUT,
        FailureCode.NETWORK_ERROR,
        FailureCode.SERVICE_UNAVAILABLE,
        FailureCode.RATE_LIMITED,
        FailureCode.QUOTA_EXHAUSTED,
    }
)


@dataclass(frozen=True, slots=True)
class FallbackOffer:
    operation_kind: str
    failed_symbols: tuple[str, ...]
    intervals: tuple[str, ...]
    failure_codes: tuple[FailureCode, ...]
    completed: int
    total: int


FallbackConsent = Callable[[FallbackOffer], bool]


class WholeRunFallbackRequested(RuntimeError):
    """Internal control flow: discard primary work and restart on Yahoo."""


def restart_whole_run_on_accept(consent: FallbackConsent) -> FallbackConsent:
    def decide(offer: FallbackOffer) -> bool:
        if consent(offer):
            raise WholeRunFallbackRequested
        return False

    return decide


class FallbackMarketDataPort(DailyBarsProviderPort, Protocol):
    def get_candle_series(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CandleDataset: ...


class FallbackSession:
    """Remember one user decision for the lifetime of an analysis run."""

    def __init__(self, consent: FallbackConsent) -> None:
        self._consent = consent
        self._decision: bool | None = None

    def allow(self, offer: FallbackOffer) -> bool:
        if self._decision is None:
            self._decision = self._consent(offer)
        return self._decision


class FallbackDailyBarsProvider:
    def __init__(
        self,
        primary: DailyBarsProviderPort,
        fallback: DailyBarsProviderPort,
        session: FallbackSession,
        *,
        operation_kind: str,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._session = session
        self._operation_kind = operation_kind

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress: DailySeriesProgressSink | None = None,
    ) -> DailyBarsDataset:
        primary = self._primary.get_daily_series(
            symbols,
            start_date,
            end_date,
            operation_control=operation_control,
            progress=progress,
        )
        eligible, codes = eligible_fallback_errors(symbols, primary.errors)
        if not eligible:
            return primary
        offer = FallbackOffer(
            self._operation_kind,
            eligible,
            (),
            codes,
            len(primary.series_by_symbol),
            len(symbols),
        )
        if not self._session.allow(offer):
            return primary
        recovered = self._fallback.get_daily_series(
            eligible,
            start_date,
            end_date,
            operation_control=operation_control,
        )
        return merge_daily_datasets(
            primary,
            recovered,
            requested=symbols,
        )


def fallback_eligible(code: FailureCode) -> bool:
    return code in _ELIGIBLE_FAILURES


def parse_failure_code(value: str) -> FailureCode | None:
    try:
        return FailureCode(value)
    except ValueError:
        return None


def eligible_fallback_errors(
    symbols: tuple[str, ...],
    errors: Mapping[str, str],
) -> tuple[tuple[str, ...], tuple[FailureCode, ...]]:
    eligible = tuple(
        symbol
        for symbol in symbols
        if (
            (code := parse_failure_code(errors.get(symbol, ""))) is not None
            and fallback_eligible(code)
        )
    )
    codes = tuple(
        dict.fromkeys(
            code
            for symbol in eligible
            if (code := parse_failure_code(errors.get(symbol, ""))) is not None
        )
    )
    return eligible, codes


def record_source(
    sources: dict[str, str],
    symbol: str,
    source: str,
) -> None:
    previous = sources.get(symbol)
    sources[symbol] = source if previous is None or previous == source else "mixed"


def provider_summary(
    sources: Mapping[str, str],
    provider_id: str,
    provider_name: str,
) -> tuple[str, str]:
    source_ids = set(sources.values())
    if "mixed" in source_ids or len(source_ids) > 1:
        return "mixed", f"{provider_name} + Yahoo 补充"
    if source_ids == {"yahoo"}:
        return "yahoo", "Yahoo 备用数据"
    return provider_id, provider_name


def merge_daily_datasets(
    primary: DailyBarsDataset,
    fallback: DailyBarsDataset,
    *,
    requested: tuple[str, ...],
) -> DailyBarsDataset:
    series = dict(primary.series_by_symbol)
    sources = dict(primary.source_by_symbol)
    for symbol in requested:
        if symbol in series:
            continue
        recovered = fallback.series_by_symbol.get(symbol)
        if recovered is not None:
            series[symbol] = recovered
            sources[symbol] = fallback.source_by_symbol.get(
                symbol,
                fallback.provider_id,
            )

    errors = {
        symbol: error
        for symbol in requested
        if symbol not in series
        and (
            error := fallback.errors.get(
                symbol,
                primary.errors.get(symbol, ""),
            )
        )
    }
    source_ids = set(sources.values())
    if len(source_ids) > 1:
        provider_id = "mixed"
        provider_name = f"{primary.provider_display_name} + Yahoo 补充"
    elif source_ids == {fallback.provider_id}:
        provider_id = fallback.provider_id
        provider_name = fallback.provider_display_name
    else:
        provider_id = primary.provider_id
        provider_name = primary.provider_display_name
    return DailyBarsDataset(
        provider_id,
        provider_name,
        series,
        errors,
        sources,
    )
