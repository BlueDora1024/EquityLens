from __future__ import annotations

from datetime import date
from decimal import Decimal

from stock_toolbox.core.market_data.fallback import (
    FallbackDailyBarsProvider,
    FallbackOffer,
    FallbackSession,
    fallback_eligible,
    merge_daily_datasets,
)
from stock_toolbox.core.market_data.models import (
    DailyBarsDataset,
    PricePoint,
    PriceSeries,
)
from stock_toolbox.core.operations.failure_policy import FailureCode


class _Control:
    def cancellation_requested(self) -> bool:
        return False


class _Provider:
    def __init__(self, dataset: DailyBarsDataset) -> None:
        self.dataset = dataset
        self.calls: list[tuple[str, ...]] = []

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: object,
        progress: object = None,
    ) -> DailyBarsDataset:
        del start_date, end_date, operation_control, progress
        self.calls.append(symbols)
        return DailyBarsDataset(
            self.dataset.provider_id,
            self.dataset.provider_display_name,
            {
                symbol: self.dataset.series_by_symbol[symbol]
                for symbol in symbols
                if symbol in self.dataset.series_by_symbol
            },
            {
                symbol: self.dataset.errors[symbol]
                for symbol in symbols
                if symbol in self.dataset.errors
            },
        )


def _series(symbol: str, close: str) -> PriceSeries:
    return PriceSeries(
        symbol,
        (PricePoint(date(2026, 7, 29), Decimal(close)),),
    )


def test_only_terminal_infrastructure_failures_are_fallback_eligible() -> None:
    for code in (
        FailureCode.NETWORK_ERROR,
        FailureCode.TIMEOUT,
        FailureCode.SERVICE_UNAVAILABLE,
        FailureCode.RATE_LIMITED,
        FailureCode.QUOTA_EXHAUSTED,
    ):
        assert fallback_eligible(code)

    for code in (
        FailureCode.AUTHENTICATION_FAILED,
        FailureCode.PERMISSION_DENIED,
        FailureCode.DATA_UNAVAILABLE,
        FailureCode.INSUFFICIENT_DATA,
        FailureCode.INTERNAL,
    ):
        assert not fallback_eligible(code)


def test_mixed_dataset_preserves_primary_success_and_per_symbol_source() -> None:
    primary = DailyBarsDataset(
        "longbridge",
        "Longbridge",
        {"A.US": _series("A.US", "10")},
        {
            "B.US": FailureCode.NETWORK_ERROR.value,
            "C.US": FailureCode.DATA_UNAVAILABLE.value,
        },
        {"A.US": "longbridge"},
    )
    fallback = DailyBarsDataset(
        "yahoo",
        "Yahoo 备用数据",
        {"B.US": _series("B.US", "20")},
        {},
        {"B.US": "yahoo"},
    )

    merged = merge_daily_datasets(
        primary,
        fallback,
        requested=("A.US", "B.US", "C.US"),
    )

    assert merged.provider_id == "mixed"
    assert merged.provider_display_name == "Longbridge + Yahoo 补充"
    assert tuple(merged.series_by_symbol) == ("A.US", "B.US")
    assert merged.errors == {"C.US": FailureCode.DATA_UNAVAILABLE.value}
    assert merged.source_by_symbol == {
        "A.US": "longbridge",
        "B.US": "yahoo",
    }


def test_merge_does_not_replace_a_primary_success() -> None:
    primary = DailyBarsDataset(
        "longbridge",
        "Longbridge",
        {"A.US": _series("A.US", "10")},
        {},
        {"A.US": "longbridge"},
    )
    fallback = DailyBarsDataset(
        "yahoo",
        "Yahoo 备用数据",
        {"A.US": _series("A.US", "99")},
        {},
        {"A.US": "yahoo"},
    )

    merged = merge_daily_datasets(primary, fallback, requested=("A.US",))

    assert merged.series_by_symbol["A.US"].points[-1].close == Decimal(10)
    assert merged.provider_id == "longbridge"
    assert merged.source_by_symbol == {"A.US": "longbridge"}


def test_mixed_provider_name_uses_the_actual_primary_provider() -> None:
    primary = DailyBarsDataset(
        "futu",
        "富途",
        {"A.US": _series("A.US", "10")},
        {"B.US": FailureCode.QUOTA_EXHAUSTED.value},
        {"A.US": "futu"},
    )
    fallback = DailyBarsDataset(
        "yahoo",
        "Yahoo 备用数据",
        {"B.US": _series("B.US", "20")},
        {},
        {"B.US": "yahoo"},
    )

    merged = merge_daily_datasets(
        primary,
        fallback,
        requested=("A.US", "B.US"),
    )

    assert merged.provider_id == "mixed"
    assert merged.provider_display_name == "富途 + Yahoo 补充"


def test_fallback_provider_requests_only_eligible_primary_failures() -> None:
    primary = _Provider(
        DailyBarsDataset(
            "longbridge",
            "Longbridge",
            {"A.US": _series("A.US", "10")},
            {
                "B.US": FailureCode.NETWORK_ERROR.value,
                "C.US": FailureCode.DATA_UNAVAILABLE.value,
            },
        )
    )
    fallback = _Provider(
        DailyBarsDataset(
            "yahoo",
            "Yahoo 备用数据",
            {"B.US": _series("B.US", "20")},
            {},
        )
    )
    offers = []
    provider = FallbackDailyBarsProvider(
        primary,
        fallback,
        FallbackSession(lambda offer: offers.append(offer) or True),
        operation_kind="rs",
    )

    result = provider.get_daily_series(
        ("A.US", "B.US", "C.US"),
        date(2026, 7, 1),
        date(2026, 7, 29),
        operation_control=_Control(),
    )

    assert fallback.calls == [("B.US",)]
    assert len(offers) == 1
    assert offers[0].failed_symbols == ("B.US",)
    assert tuple(result.series_by_symbol) == ("A.US", "B.US")
    assert result.errors == {"C.US": FailureCode.DATA_UNAVAILABLE.value}


def test_fallback_session_asks_once_and_reuses_the_decision() -> None:
    calls = []
    session = FallbackSession(lambda offer: calls.append(offer) or True)
    offer = FallbackOffer("rs", ("A.US",), (), (FailureCode.TIMEOUT,), 0, 1)

    assert session.allow(offer)
    assert session.allow(offer)
    assert len(calls) == 1
