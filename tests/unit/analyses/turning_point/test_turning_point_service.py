import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

import stock_toolbox.analyses.turning_point.domain.engine as engine_module
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
    TurningPointRunStatus,
)
from stock_toolbox.analyses.turning_point.application.service import (
    StartTurningPointRun,
    _screen_quant,
)
from stock_toolbox.analyses.turning_point.domain.engine import TurningPointEngine
from stock_toolbox.analyses.turning_point.domain.models import (
    TurningPointTradeSide,
)
from stock_toolbox.core.market_data.fallback import FallbackSession
from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    CandleSeries,
    DailyBarsDataset,
    MarketCandle,
    SecuritySnapshot,
    SnapshotDataset,
)
from stock_toolbox.core.market_data.quant import (
    QuantProgress,
    QuantSeries,
    QuantSeriesDataset,
)
from stock_toolbox.core.market_data.service import SharedMarketDataService
from stock_toolbox.core.master_data.models import (
    WatchlistDTO,
    WatchlistMembershipDTO,
)
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback


class Master:
    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO:
        return WatchlistDTO(
            watchlist_id,
            "Tech",
            1,
            (
                WatchlistMembershipDTO(
                    "membership",
                    "security",
                    "IREN.US",
                    "IREN",
                    "binding",
                    "classification",
                    "数据中心",
                ),
            ),
        )


def test_quant_screen_applies_interval_specific_recent_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    size = 130
    signal_index = 80
    ccc = tuple(index == signal_index for index in range(size))
    kinds = tuple(
        "RECENT_BULLISH_DIVERGENCE" if index == signal_index else None
        for index in range(size)
    )
    monkeypatch.setattr(
        engine_module,
        "_divergence_state_from_macd",
        lambda *_args: (ccc, kinds),
    )
    timestamps = tuple(
        datetime(2026, 7, 1, tzinfo=UTC) + timedelta(minutes=30 * index)
        for index in range(size)
    )
    series = QuantSeries(
        "IREN.US",
        CandleInterval.MIN_30,
        timestamps,
        {
            "high": (101.0,) * size,
            "close": (100.0,) * size,
            "high_ema26": (102.0,) * size,
            "high_ema89": (103.0,) * size,
            "dif": (-1.0,) * size,
            "hist": (-0.5,) * size,
            "volume": (1_000.0,) * size,
        },
    )

    result = _screen_quant(
        TurningPointEngine(),
        "IREN.US",
        series,
        TurningPointTradeSide.LEFT_CD,
        CandleInterval.MIN_30,
    )

    assert result.decision.value == "MATCHED"
    assert result.signal_at == timestamps[signal_index]


class FailingMaster:
    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO:
        del watchlist_id
        raise KeyError("missing detail")


class Market:
    def __init__(self) -> None:
        self.snapshot_calls = 0

    def get_security_snapshots(self, symbols, *, operation_control):
        del operation_control
        self.snapshot_calls += 1
        return SnapshotDataset(
            "longbridge",
            "Longbridge",
            {
                symbol: SecuritySnapshot(
                    symbol,
                    None,
                    50_000_000_000,
                )
                for symbol in symbols
            },
            {},
        )

    def get_daily_series(self, *args, **kwargs):
        raise AssertionError("daily prefilter should not run")

    def get_candle_series(self, *args, **kwargs):
        raise AssertionError("raw candles should not run")


class NativeIntradayMarket(Market):
    def __init__(self) -> None:
        super().__init__()
        self.candle_intervals: list[CandleInterval] = []

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
        self.candle_intervals.append(interval)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        step = {
            CandleInterval.MIN_120: timedelta(hours=2),
            CandleInterval.MIN_240: timedelta(hours=4),
        }[interval]
        candles = tuple(
            MarketCandle(
                start + step * index,
                Decimal(100),
                Decimal(101),
                Decimal(99),
                Decimal(100),
                1_000,
            )
            for index in range(count)
        )
        return CandleDataset(
            "longbridge",
            "Longbridge",
            interval,
            {
                symbol: CandleSeries(symbol, interval, candles)
                for symbol in symbols
            },
            {},
        )


class Quant:
    def __init__(self) -> None:
        self.requests = []

    def get_quant_series(
        self,
        symbols,
        request,
        *,
        operation_control,
        progress=None,
    ):
        del operation_control, progress
        self.requests.append((tuple(symbols), request.script_version))
        timestamps = tuple(
            datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=index)
            for index in range(220)
        )
        values = {
            "high": tuple(101.0 for _item in timestamps),
            "close": tuple(100.0 for _item in timestamps),
            "high_ema26": tuple(101.0 for _item in timestamps),
            "high_ema89": tuple(102.0 for _item in timestamps),
            "dif": tuple(-1.0 for _item in timestamps),
            "hist": tuple(-1.0 for _item in timestamps),
            "volume": tuple(1_000_000.0 for _item in timestamps),
        }
        return QuantSeriesDataset(
            "longbridge",
            "Longbridge",
            {
                symbol: QuantSeries(
                    symbol,
                    request.interval,
                    timestamps,
                    values,
                )
                for symbol in symbols
            },
            {},
            fetched=len(symbols),
        )


class TimeoutQuant:
    def get_quant_series(
        self,
        symbols,
        request,
        *,
        operation_control,
        progress=None,
    ):
        del operation_control, progress
        return QuantSeriesDataset(
            "longbridge",
            "Longbridge",
            {},
            {symbol: FailureCode.TIMEOUT.value for symbol in symbols},
            fetched=0,
        )


class MatchingQuant(Quant):
    def get_quant_series(
        self,
        symbols,
        request,
        *,
        operation_control,
        progress=None,
    ):
        del operation_control, progress
        self.requests.append((tuple(symbols), request.script_version))
        randomizer = random.Random(3)
        closes = [100.0]
        dif = []
        histogram = []
        current_dif = -2.0
        for index in range(130):
            if index:
                closes.append(
                    max(1.0, closes[-1] + randomizer.uniform(-3.0, 2.7))
                )
            current_dif += randomizer.uniform(-0.3, 0.35)
            dif.append(current_dif)
            histogram.append(randomizer.uniform(-1.0, 1.0))
        timestamps = tuple(
            datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
            for index in range(130)
        )
        values = {
            "high": tuple(value + 1.0 for value in closes),
            "close": tuple(closes),
            "high_ema26": (200.0,) * 130,
            "high_ema89": (100.0,) * 130,
            "dif": tuple(dif),
            "hist": tuple(histogram),
            "volume": (1_000_000.0,) * 130,
        }
        return QuantSeriesDataset(
            "longbridge",
            "Longbridge",
            {
                symbol: QuantSeries(
                    symbol,
                    request.interval,
                    timestamps,
                    values,
                )
                for symbol in symbols
            },
            {},
            fetched=len(symbols),
        )


class SmallCapMarket(Market):
    def get_security_snapshots(self, symbols, *, operation_control):
        del operation_control
        self.snapshot_calls += 1
        return SnapshotDataset(
            "longbridge",
            "Longbridge",
            {
                symbol: SecuritySnapshot(symbol, None, 1_900_000_000)
                for symbol in symbols
            },
            {},
        )


class MissingMarketValueMarket(Market):
    def get_security_snapshots(self, symbols, *, operation_control):
        del operation_control
        self.snapshot_calls += 1
        return SnapshotDataset(
            "longbridge",
            "Longbridge",
            {
                symbol: SecuritySnapshot(symbol, None, None)
                for symbol in symbols
            },
            {},
        )


class YahooRawMarket:
    provider_id = "yahoo"
    provider_display_name = "Yahoo 备用数据"

    def __init__(self) -> None:
        self.candle_calls: list[tuple[str, ...]] = []

    def get_daily_series(self, *args, **kwargs):
        del args, kwargs
        return DailyBarsDataset("yahoo", "Yahoo 备用数据", {}, {})

    def get_security_snapshots(self, symbols, *, operation_control):
        del operation_control
        return SnapshotDataset("yahoo", "Yahoo 备用数据", {}, {})

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
        self.candle_calls.append(symbols)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        candles = tuple(
            MarketCandle(
                start + timedelta(days=index),
                Decimal(100),
                Decimal(101),
                Decimal(99),
                Decimal(100),
                1_000,
            )
            for index in range(count)
        )
        return CandleDataset(
            "yahoo",
            "Yahoo 备用数据",
            interval,
            {
                symbol: CandleSeries(symbol, interval, candles)
                for symbol in symbols
            },
            {},
        )


class FeedbackQuant(Quant):
    feedback = RunFeedback(
        FeedbackKind.THROTTLED,
        FailureCode.RATE_LIMITED,
        "IREN.US",
        "1d",
        wait_seconds=3,
        active_concurrency=1,
    )

    def get_quant_series(
        self,
        symbols,
        request,
        *,
        operation_control,
        progress=None,
    ):
        if progress is not None:
            progress(
                QuantProgress(
                    0,
                    len(symbols),
                    symbols[0],
                    0,
                    0,
                    feedback=self.feedback,
                )
            )
        return super().get_quant_series(
            symbols,
            request,
            operation_control=operation_control,
            progress=progress,
        )


class History:
    def __init__(self) -> None:
        self.saved = False
        self.run = None

    def save_turning_point(self, run) -> None:
        self.run = run
        self.saved = True


class FailingHistory:
    def save_turning_point(self, run) -> None:
        del run
        raise RuntimeError("database detail")


def context():
    registry = OperationRegistry(clock=lambda: datetime(2026, 7, 25, tzinfo=UTC))
    registry.reserve("op-turning", "key", "turning")
    result = registry.begin_reserved("op-turning")
    assert result is not None
    return result


def run_service(
    market: Market,
    request: TurningPointRequest,
):
    service = StartTurningPointRun(
        Master(),
        market,  # type: ignore[arg-type]
        History(),
        quant_market_data=Quant(),
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        today=lambda: date(2026, 7, 25),
    )
    return service.execute(request, context())


def test_native_two_and_four_hour_candles_bypass_unsupported_quant_periods() -> None:
    market = NativeIntradayMarket()
    quant = Quant()
    history = History()
    service = StartTurningPointRun(
        Master(),
        market,  # type: ignore[arg-type]
        history,
        quant_market_data=quant,
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        today=lambda: date(2026, 7, 25),
    )
    request = TurningPointRequest(
        "pool",
        (CandleInterval.MIN_120, CandleInterval.MIN_240),
        date(2026, 7, 24),
        trade_side=TurningPointTradeSide.LEFT_CD,
    )

    result = service.execute(request, context())

    assert result.status is TurningPointRunStatus.READY
    assert market.candle_intervals == [
        CandleInterval.MIN_120,
        CandleInterval.MIN_240,
    ]
    assert quant.requests == []


def test_request_preserves_selected_period_order() -> None:
    request = TurningPointRequest(
        "pool",
        (
            CandleInterval.DAY,
            CandleInterval.MIN_30,
            CandleInterval.WEEK,
        ),
        date(2026, 7, 24),
    )

    assert request.intervals == (
        CandleInterval.DAY,
        CandleInterval.MIN_30,
        CandleInterval.WEEK,
    )
    assert request.interval is CandleInterval.DAY


@pytest.mark.parametrize(
    "intervals",
    [
        (),
        (CandleInterval.DAY, CandleInterval.DAY),
    ],
)
def test_request_rejects_empty_or_duplicate_periods(
    intervals: tuple[CandleInterval, ...],
) -> None:
    with pytest.raises(ValueError, match="interval"):
        TurningPointRequest("pool", intervals, date(2026, 7, 24))


def test_no_prefilters_skip_security_snapshots() -> None:
    market = Market()

    result = run_service(
        market,
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
    )

    assert result.status is TurningPointRunStatus.READY
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal(1)
    assert result.reliability.succeeded_tasks == 1
    assert market.snapshot_calls == 0


def test_turning_quant_timeout_recovers_only_failed_symbols_with_yahoo() -> None:
    raw = YahooRawMarket()
    offers = []
    history = History()
    service = StartTurningPointRun(
        Master(),
        Market(),  # type: ignore[arg-type]
        history,
        quant_market_data=TimeoutQuant(),
        fallback_market_data=SharedMarketDataService(raw),
        fallback_session=FallbackSession(
            lambda offer: offers.append(offer) or True
        ),
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        today=lambda: date(2026, 7, 25),
    )

    result = service.execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        context(),
    )

    assert result.status is TurningPointRunStatus.READY
    assert raw.candle_calls == [("IREN.US",)]
    assert len(offers) == 1
    assert offers[0].failed_symbols == ("IREN.US",)
    assert result.run is history.run
    assert result.run is not None
    assert result.run.provider_id == "yahoo"


def test_turning_point_forwards_quant_feedback_to_analysis_progress() -> None:
    progress = []
    service = StartTurningPointRun(
        Master(),
        Market(),  # type: ignore[arg-type]
        History(),
        quant_market_data=FeedbackQuant(),
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        progress=progress.append,
        today=lambda: date(2026, 7, 25),
    )

    service.execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        context(),
    )

    assert next(item.feedback for item in progress if item.feedback is not None) == (
        FeedbackQuant.feedback
    )


def test_unmatched_symbols_do_not_request_snapshots() -> None:
    market = Market()

    result = run_service(
        market,
        TurningPointRequest("pool", (CandleInterval.DAY,), date(2026, 7, 24)),
    )

    assert result.status is TurningPointRunStatus.READY
    assert market.snapshot_calls == 0


def test_matched_symbols_receive_small_cap_annotation_without_250d_request() -> None:
    market = SmallCapMarket()
    quant = MatchingQuant()
    history = History()
    service = StartTurningPointRun(
        Master(),
        market,  # type: ignore[arg-type]
        history,
        quant_market_data=quant,
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        today=lambda: date(2026, 7, 25),
    )

    result = service.execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
            trade_side=TurningPointTradeSide.LEFT_CD,
        ),
        context(),
    )

    assert result.status is TurningPointRunStatus.READY
    assert result.run is history.run
    assert result.run is not None
    item = result.run.results[0]
    assert item.matched_periods == (CandleInterval.DAY,)
    assert item.market_value_usd == 1_900_000_000
    assert item.risk_flags == ("SMALL_MARKET_CAP",)
    assert not hasattr(item, "return_250d")
    assert market.snapshot_calls == 1
    assert quant.requests == [
        (("IREN.US",), "turning-point-quant-v3"),
    ]


def test_missing_market_value_keeps_matched_signal_reliable() -> None:
    market = MissingMarketValueMarket()
    quant = MatchingQuant()
    history = History()
    service = StartTurningPointRun(
        Master(),
        market,  # type: ignore[arg-type]
        history,
        quant_market_data=quant,
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        today=lambda: date(2026, 7, 25),
    )

    result = service.execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
            trade_side=TurningPointTradeSide.LEFT_CD,
        ),
        context(),
    )

    assert result.status is TurningPointRunStatus.READY
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal(1)
    assert result.run is not None
    item = result.run.results[0]
    assert item.matched_periods == (CandleInterval.DAY,)
    assert item.risk_flags == ("MARKET_VALUE_UNKNOWN",)


class PlannedMaster:
    def __init__(self, count: int) -> None:
        self.count = count

    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO:
        return WatchlistDTO(
            watchlist_id,
            "Planned",
            1,
            tuple(
                WatchlistMembershipDTO(
                    f"membership-{index}",
                    f"security-{index}",
                    f"S{index:03d}.US",
                    f"S{index:03d}",
                    f"binding-{index}",
                    "classification",
                    "数据中心",
                )
                for index in range(self.count)
            ),
        )


class PlannedQuant(Quant):
    def __init__(self, succeeded: int, failed: int, unexecuted: int) -> None:
        super().__init__()
        self.succeeded = succeeded
        self.failed = failed
        self.unexecuted = unexecuted

    def get_quant_series(
        self,
        symbols,
        request,
        *,
        operation_control,
        progress=None,
    ):
        complete = super().get_quant_series(
            symbols[: self.succeeded],
            request,
            operation_control=operation_control,
            progress=progress,
        )
        failed_symbols = symbols[
            self.succeeded : self.succeeded + self.failed
        ]
        unexecuted_symbols = symbols[self.succeeded + self.failed :]
        return QuantSeriesDataset(
            complete.provider_id,
            complete.provider_display_name,
            complete.series_by_symbol,
            {
                **{symbol: "timeout" for symbol in failed_symbols},
                **{symbol: "circuit_open" for symbol in unexecuted_symbols},
            },
            fetched=self.succeeded,
        )


def planned_service(
    succeeded: int,
    failed: int,
    unexecuted: int,
    history: History,
) -> StartTurningPointRun:
    return StartTurningPointRun(
        PlannedMaster(succeeded + failed + unexecuted),
        Market(),  # type: ignore[arg-type]
        history,
        quant_market_data=PlannedQuant(succeeded, failed, unexecuted),
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        today=lambda: date(2026, 7, 25),
    )


def test_all_turning_tasks_succeed_and_save_ready() -> None:
    history = History()

    result = planned_service(1, 0, 0, history).execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        context(),
    )

    assert result.status is TurningPointRunStatus.READY
    assert result.run_id is not None
    assert history.run is result.run
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal(1)


def test_exactly_eighty_percent_turning_tasks_save_partial() -> None:
    history = History()

    result = planned_service(80, 0, 20, history).execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        context(),
    )

    assert result.status is TurningPointRunStatus.PARTIAL
    assert result.run_id is not None
    assert history.run is not None
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal("0.8")
    assert result.reliability.succeeded_tasks == 80
    assert result.reliability.failed_tasks == 0
    assert result.reliability.unexecuted_tasks == 20
    assert result.reliability.circuit_opened


def test_seventy_nine_percent_turning_tasks_do_not_save() -> None:
    history = History()

    result = planned_service(79, 1, 20, history).execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        context(),
    )

    assert result.status is TurningPointRunStatus.FAILED
    assert result.run_id is None
    assert history.run is None
    assert result.error_code == "insufficient_reliable_results"
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal("0.79")


def test_turning_zero_valid_security_results_do_not_save() -> None:
    history = History()

    result = planned_service(0, 1, 0, history).execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        context(),
    )

    assert result.status is TurningPointRunStatus.FAILED
    assert result.run_id is None
    assert history.run is None
    assert result.error_code == "insufficient_reliable_results"


def test_turning_history_transaction_failure_returns_no_saved_run() -> None:
    service = StartTurningPointRun(
        PlannedMaster(1),
        Market(),  # type: ignore[arg-type]
        FailingHistory(),
        quant_market_data=PlannedQuant(1, 0, 0),
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        today=lambda: date(2026, 7, 25),
    )

    result = service.execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        context(),
    )

    assert result.status is TurningPointRunStatus.FAILED
    assert result.run_id is None
    assert result.error_code == "history_save_failed"


def test_turning_watchlist_freeze_failure_never_saves() -> None:
    history = History()
    service = StartTurningPointRun(
        FailingMaster(),
        Market(),  # type: ignore[arg-type]
        history,
        quant_market_data=Quant(),
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        today=lambda: date(2026, 7, 25),
    )

    result = service.execute(
        TurningPointRequest(
            "missing",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        context(),
    )

    assert result.status is TurningPointRunStatus.FAILED
    assert result.run_id is None
    assert result.error_code == "watchlist_freeze_failed"
    assert not history.saved


def test_turning_cancellation_at_threshold_never_saves() -> None:
    registry = OperationRegistry(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC)
    )
    registry.reserve("op-turning", "key", "turning")
    operation_context = registry.begin_reserved("op-turning")
    assert operation_context is not None
    history = History()

    def cancel_at_save(item) -> None:
        if item.stage == "SAVE":
            registry.cancel("op-turning")

    service = StartTurningPointRun(
        PlannedMaster(100),
        Market(),  # type: ignore[arg-type]
        history,
        quant_market_data=PlannedQuant(80, 0, 20),
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        new_id=lambda: "run",
        progress=cancel_at_save,
        today=lambda: date(2026, 7, 25),
    )

    result = service.execute(
        TurningPointRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        operation_context,
    )

    assert result.status is TurningPointRunStatus.CANCELED
    assert result.run_id is None
    assert history.run is None
