from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
    ExtremeDeviationRunStatus,
)
from stock_toolbox.analyses.rs_strength.application.models import (
    RunRequest,
    RunStatus,
)
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
    TurningPointRunStatus,
)
from stock_toolbox.analyses.turning_point.domain.models import TurningPointTradeSide
from stock_toolbox.composition import build_application
from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    CandleSeries,
    DailyBarsDataset,
    MarketCandle,
    PricePoint,
    PriceSeries,
)
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.runtime.environment import RuntimeEnvironment


class DailyProvider:
    provider_id = "longbridge"
    provider_display_name = "Longbridge"

    def __init__(self, *, failed_symbol: str | None = None) -> None:
        self.failed_symbol = failed_symbol
        self.calls: list[tuple[str, ...]] = []

    def get_daily_series(
        self,
        symbols,
        start_date,
        end_date,
        *,
        operation_control,
        progress=None,
    ):
        del operation_control, progress
        self.calls.append(symbols)
        errors = {
            symbol: FailureCode.TIMEOUT.value for symbol in symbols if symbol == self.failed_symbol
        }
        return DailyBarsDataset(
            self.provider_id,
            self.provider_display_name,
            {
                symbol: _series(symbol, start_date, end_date)
                for symbol in symbols
                if symbol not in errors
            },
            errors,
        )


class YahooDailyProvider(DailyProvider):
    provider_id = "yahoo"
    provider_display_name = "Yahoo 备用数据"


class CandleProvider:
    provider_id = "longbridge"
    provider_display_name = "Longbridge"

    def __init__(self, *, forbidden: bool = False) -> None:
        self.forbidden = forbidden
        self.calls: list[tuple[tuple[str, ...], CandleInterval, int]] = []

    def get_daily_series(self, *args, **kwargs):
        raise AssertionError("daily bars are outside this extreme-deviation test")

    def get_security_snapshots(self, *args, **kwargs):
        raise AssertionError("snapshots are outside this extreme-deviation test")

    def get_candle_series(
        self,
        symbols,
        interval,
        count,
        end_at,
        *,
        operation_control,
    ):
        del operation_control
        if self.forbidden:
            raise AssertionError("primary provider must not run after choosing Yahoo")
        self.calls.append((symbols, interval, count))
        step = timedelta(minutes=30)
        candles = tuple(
            MarketCandle(
                end_at - step * (count - index),
                Decimal(100),
                Decimal(101),
                Decimal(99),
                Decimal(100),
                1_000,
            )
            for index in range(count)
        )
        return CandleDataset(
            self.provider_id,
            self.provider_display_name,
            interval,
            {
                symbol: CandleSeries(symbol, interval, candles)
                for symbol in symbols
            },
            {},
        )


class YahooCandleProvider(CandleProvider):
    provider_id = "yahoo"
    provider_display_name = "Yahoo 备用数据"


def _series(symbol: str, start_date: date, end_date: date) -> PriceSeries:
    points = []
    current = start_date
    close = Decimal(100)
    while current <= end_date:
        if current.weekday() < 5:
            points.append(PricePoint(current, close))
            close += Decimal(1)
        current += timedelta(days=1)
    return PriceSeries(symbol, tuple(points))


def test_rs_yahoo_restarts_whole_run_and_freezes_one_source(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="rs-yahoo-fallback",
    )
    application.import_securities("AAPL,NVDA")
    watchlist = application.master_data.create_watchlist("Fallback")
    application.master_data.add_watchlist_members(
        watchlist.id,
        tuple(
            (security.id, security.bindings[0].id)
            for security in application.master_data.list_securities()
        ),
    )
    primary = DailyProvider(failed_symbol="NVDA.US")
    yahoo = YahooDailyProvider()
    application._provider = primary  # type: ignore[assignment]
    application._fallback_provider_override = yahoo  # type: ignore[assignment]
    offers = []

    result = application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("1W",),
            None,
        ),
        fallback_consent=lambda offer: offers.append(offer) or True,
    )

    assert result.status is RunStatus.READY
    assert result.run_id is not None
    assert yahoo.calls[0] == ("SPY.US",)
    assert set(yahoo.calls[1]) == {"AAPL.US", "NVDA.US"}
    assert len(offers) == 1
    history = application.get_history(result.run_id)
    assert history.header.provider_id == "yahoo"
    assert history.header.snapshot_extensions["source_by_symbol"] == {
        "SPY.US": "yahoo",
        "AAPL.US": "yahoo",
        "NVDA.US": "yahoo",
    }
    assert history.header.snapshot_extensions["requested_date_window"] == [
        "2026-07-17",
        "2026-07-24",
    ]
    assert history.header.snapshot_extensions["actual_date_window"] == [
        "2026-07-17",
        "2026-07-24",
    ]


def test_rs_can_choose_yahoo_before_primary_provider_work(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="rs-yahoo-preflight-choice",
    )
    application.import_securities("AAPL,NVDA")
    watchlist = application.master_data.create_watchlist("Fallback")
    application.master_data.add_watchlist_members(
        watchlist.id,
        tuple(
            (security.id, security.bindings[0].id)
            for security in application.master_data.list_securities()
        ),
    )
    primary = DailyProvider()
    yahoo = YahooDailyProvider()
    application._provider = primary  # type: ignore[assignment]
    application._fallback_provider_override = yahoo  # type: ignore[assignment]

    result = application.run(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("1W",),
            None,
        ),
        force_yahoo=True,
    )

    assert result.status is RunStatus.READY
    assert primary.calls == []
    assert yahoo.calls[0] == ("SPY.US",)
    assert set(yahoo.calls[1]) == {"AAPL.US", "NVDA.US"}


def test_extreme_can_choose_yahoo_before_primary_provider_work(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="extreme-yahoo-preflight-choice",
    )
    application.import_securities("IREN")
    security = application.master_data.list_securities()[0]
    primary = CandleProvider(forbidden=True)
    yahoo = YahooCandleProvider()
    application._provider = primary  # type: ignore[assignment]
    application._fallback_provider_override = yahoo  # type: ignore[assignment]

    result = application.run_extreme_deviation(
        ExtremeDeviationRequest(
            "",
            (CandleInterval.MIN_30,),
            date(2026, 7, 24),
            security_id=security.id,
        ),
        force_yahoo=True,
    )

    assert result.status is ExtremeDeviationRunStatus.READY
    assert primary.calls == []
    assert len(yahoo.calls) == 1
    assert result.run is not None
    assert result.run.provider_id == "yahoo"
    assert result.run.source_by_symbol == {"IREN.US": "yahoo"}


def test_turning_can_choose_yahoo_before_primary_provider_work(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="turning-yahoo-preflight-choice",
    )
    application.import_securities("IREN")
    watchlist = application.master_data.create_watchlist("Fallback")
    security = application.master_data.list_securities()[0]
    application.master_data.add_watchlist_members(
        watchlist.id,
        ((security.id, security.bindings[0].id),),
    )
    primary = CandleProvider(forbidden=True)
    yahoo = YahooCandleProvider()
    application._provider = primary  # type: ignore[assignment]
    application._fallback_provider_override = yahoo  # type: ignore[assignment]

    result = application.run_turning_point(
        TurningPointRequest(
            watchlist.id,
            (CandleInterval.MIN_30,),
            date(2026, 7, 24),
            trade_side=TurningPointTradeSide.LEFT_CD,
        ),
        force_yahoo=True,
    )

    assert result.status is TurningPointRunStatus.READY
    assert primary.calls == []
    assert len(yahoo.calls) == 1
    assert result.run is not None
    assert result.run.provider_id == "yahoo"
    assert result.run.source_by_symbol == {"IREN.US": "yahoo"}
