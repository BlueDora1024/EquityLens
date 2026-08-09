from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from stock_toolbox.analyses.extreme_deviation.application.models import (
    DeviationChartPoint,
    ExtremeDeviationRequest,
    ExtremeDeviationRunStatus,
    PeriodOutcome,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import request_for
from stock_toolbox.analyses.extreme_deviation.application.service import (
    StartExtremeDeviationRun,
)
from stock_toolbox.core.market_data.fallback import FallbackSession
from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    CandleSeries,
    MarketCandle,
)
from stock_toolbox.core.market_data.quant import (
    QuantProgress,
    QuantSeries,
    QuantSeriesDataset,
)
from stock_toolbox.core.market_data.service import SharedMarketDataService
from stock_toolbox.core.master_data.models import (
    SecurityBindingDTO,
    SecurityDetailDTO,
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
            3,
            (
                WatchlistMembershipDTO(
                    "membership",
                    "security",
                    "IREN.US",
                    "IREN Limited",
                    "binding",
                    "classification",
                    "AI 数据中心",
                ),
            ),
        )


class SingleSecurityMaster:
    def get_security(self, security_id: str) -> SecurityDetailDTO:
        if security_id != "security":
            raise KeyError(security_id)
        return SecurityDetailDTO(
            "security",
            "IREN.US",
            "IREN Limited",
            "NASDAQ",
            "USD",
            "US",
            None,
            {},
            "COMMON_STOCK",
            (SecurityBindingDTO("binding", "classification", "AI 数据中心", "manual"),),
        )


def test_period_outcome_can_freeze_a_normalized_ohlc_chart_point() -> None:
    point = DeviationChartPoint(
        datetime(2026, 7, 24, tzinfo=UTC),
        100.0,
        110.0,
        95.0,
        105.0,
        -82,
        "超级买入观察",
    )

    assert point.score == -82
    assert point.low < point.close < point.high
    outcome = PeriodOutcome(CandleInterval.DAY, 650, None, chart_points=(point,))
    assert outcome.chart_points == (point,)


class FailingMaster:
    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO:
        del watchlist_id
        raise KeyError("missing detail")


def test_single_security_request_freezes_only_the_selected_security() -> None:
    history = SavedHistory()
    service = StartExtremeDeviationRun(
        SingleSecurityMaster(),
        NeverMarket(),
        history,
        quant_market_data=CompactQuant(),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
        new_id=lambda: "run",
    )

    result = service.execute(
        ExtremeDeviationRequest(
            "",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
            security_id="security",
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.READY
    assert result.run is not None
    assert result.run.watchlist_name == "单证券复盘"
    assert result.run.securities[0].symbol == "IREN.US"


def test_unsupported_two_hour_interval_fails_before_market_request() -> None:
    service = StartExtremeDeviationRun(
        SingleSecurityMaster(),
        NeverMarket(),
        SavedHistory(),
        quant_market_data=CompactQuant(),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
        new_id=lambda: "run",
    )

    result = service.execute(
        ExtremeDeviationRequest(
            "",
            (CandleInterval.MIN_120,),
            date(2026, 7, 24),
            security_id="security",
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.FAILED
    assert result.error_code == "unsupported_interval"


class NeverMarket:
    def get(self, *args, **kwargs):
        raise AssertionError("market data should not be called")


class History:
    def save_extreme_deviation(self, run) -> None:
        raise AssertionError("history should not be saved")


class SavedHistory:
    def __init__(self) -> None:
        self.run = None

    def save_extreme_deviation(self, run) -> None:
        self.run = run


class FailingHistory:
    def save_extreme_deviation(self, run) -> None:
        del run
        raise RuntimeError("database detail")


class CompactQuant:
    def get_quant_series(
        self,
        symbols,
        request,
        *,
        operation_control,
        progress=None,
    ):
        del operation_control, progress
        timestamps = tuple(
            datetime(2026, 1, day, tzinfo=UTC)
            for day in range(1, 29)
        ) + tuple(
            datetime(2026, 2, day, tzinfo=UTC)
            for day in range(1, 29)
        ) + tuple(
            datetime(2026, 3, day, tzinfo=UTC)
            for day in range(1, 32)
        ) + tuple(
            datetime(2026, 4, day, tzinfo=UTC)
            for day in range(1, 14)
        )
        values = {
            name: tuple(
                (
                    100.0
                    if name in {"close", "buy_anchor", "sell_anchor"}
                    else 0.5
                    if name == "range_position"
                    else 1.0
                )
                for _item in timestamps
            )
            for name in request.series_names
        }
        series = QuantSeries(
            symbols[0],
            request.interval,
            timestamps,
            values,
            source_count=650,
        )
        return QuantSeriesDataset(
            "longbridge",
            "Longbridge",
            {symbols[0]: series},
            {},
            fetched=1,
        )


class OneReliablePeriodQuant(CompactQuant):
    """Model a recently listed security with only one usable period."""

    def get_quant_series(
        self,
        symbols,
        request,
        *,
        operation_control,
        progress=None,
    ):
        if request.interval is CandleInterval.MIN_30:
            return super().get_quant_series(
                symbols,
                request,
                operation_control=operation_control,
                progress=progress,
            )
        return QuantSeriesDataset(
            "longbridge",
            "Longbridge",
            {},
            {symbols[0]: "insufficient_quant_history"},
        )


def test_single_security_keeps_one_reliable_period_as_partial_result() -> None:
    history = SavedHistory()
    service = StartExtremeDeviationRun(
        SingleSecurityMaster(),
        NeverMarket(),
        history,
        quant_market_data=OneReliablePeriodQuant(),
        clock=lambda: datetime(2026, 7, 24, tzinfo=UTC),
        new_id=lambda: "run",
    )

    result = service.execute(
        ExtremeDeviationRequest(
            "",
            (
                CandleInterval.MIN_30,
                CandleInterval.MIN_60,
                CandleInterval.DAY,
                CandleInterval.WEEK,
            ),
            date(2026, 7, 24),
            security_id="security",
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.PARTIAL
    assert result.run is not None
    assert result.run.results[0].successful_periods == 1
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal("0.25")
    assert history.run is result.run


class FeedbackQuant(CompactQuant):
    feedback = RunFeedback(
        FeedbackKind.CIRCUIT_OPEN,
        FailureCode.RATE_LIMITED,
        "IREN.US",
        "1d",
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


class YahooRawMarket:
    def __init__(self) -> None:
        self.candle_calls: list[tuple[str, ...]] = []

    def get_daily_series(self, *args, **kwargs):
        raise AssertionError("daily bars should not run")

    def get_security_snapshots(self, *args, **kwargs):
        raise AssertionError("snapshots should not run")

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
        self.candle_calls.append(symbols)
        candles = tuple(
            MarketCandle(
                end_at - timedelta(days=count - index),
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
            "Yahoo Finance",
            interval,
            {
                symbol: CandleSeries(symbol, interval, candles)
                for symbol in symbols
            },
            {},
        )


def _context():
    registry = OperationRegistry(clock=lambda: datetime(2026, 7, 27, tzinfo=UTC))
    registry.reserve("op", "key", "test")
    context = registry.begin_reserved("op")
    assert context is not None
    return context


def test_selected_symbol_must_belong_to_the_frozen_watchlist() -> None:
    service = StartExtremeDeviationRun(
        Master(),
        NeverMarket(),
        History(),
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        new_id=lambda: "run",
    )

    result = service.execute(
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
            ("NVDA.US",),
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.FAILED
    assert result.error_code == "selected_symbol_not_in_watchlist"


def test_at_least_one_interval_is_required() -> None:
    service = StartExtremeDeviationRun(
        Master(),
        NeverMarket(),
        History(),
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        new_id=lambda: "run",
    )

    result = service.execute(
        ExtremeDeviationRequest("pool", (), date(2026, 7, 24)),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.FAILED
    assert result.error_code == "interval_required"


def test_extreme_request_retains_only_scoring_history() -> None:
    request = request_for(CandleInterval.DAY, date(2026, 7, 24))

    assert request.retain_last == 199
    assert request.series_names[:4] == ("open", "high", "low", "close")


def test_compact_quant_result_keeps_full_source_confidence() -> None:
    history = SavedHistory()
    service = StartExtremeDeviationRun(
        Master(),
        NeverMarket(),
        history,
        quant_market_data=CompactQuant(),
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        new_id=lambda: "run",
    )

    result = service.execute(
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.READY
    assert result.run is not None
    assert history.run is result.run
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal(1)
    assert result.reliability.succeeded_tasks == 1
    period = result.run.results[0].periods[0]
    assert period.candle_count == 650
    assert period.score is not None
    assert period.score.confidence == "FULL"
    assert len(period.chart_points) == 71
    assert period.chart_points[-1].buy_pressure == 1.0
    assert period.chart_points[-1].sell_pressure == 1.0
    assert period.chart_points[0].close == 100.0


def test_extreme_quant_timeout_recovers_only_failed_symbols_with_yahoo() -> None:
    raw = YahooRawMarket()
    history = SavedHistory()
    offers = []
    service = StartExtremeDeviationRun(
        Master(),
        NeverMarket(),
        history,
        quant_market_data=PlannedQuant(0, 1, 0),
        fallback_market_data=SharedMarketDataService(raw),
        fallback_session=FallbackSession(
            lambda offer: offers.append(offer) or True
        ),
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        new_id=lambda: "run",
    )

    result = service.execute(
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.READY
    assert raw.candle_calls == [("IREN.US",)]
    assert len(offers) == 1
    assert result.run is not None
    assert result.run.provider_id == "yahoo"


def test_extreme_forwards_quant_feedback_to_analysis_progress() -> None:
    progress = []
    service = StartExtremeDeviationRun(
        Master(),
        NeverMarket(),
        SavedHistory(),
        quant_market_data=FeedbackQuant(),
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        new_id=lambda: "run",
        progress=progress.append,
    )

    service.execute(
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        _context(),
    )

    assert next(item.feedback for item in progress if item.feedback is not None) == (
        FeedbackQuant.feedback
    )


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
                    "AI 数据中心",
                )
                for index in range(self.count)
            ),
        )


class PlannedQuant:
    def __init__(self, succeeded: int, failed: int, unexecuted: int) -> None:
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
        template = CompactQuant().get_quant_series(
            (symbols[0],),
            request,
            operation_control=operation_control,
            progress=progress,
        ).series_by_symbol[symbols[0]]
        failed_symbols = symbols[
            self.succeeded : self.succeeded + self.failed
        ]
        unexecuted_symbols = symbols[self.succeeded + self.failed :]
        return QuantSeriesDataset(
            "longbridge",
            "Longbridge",
            {
                symbol: QuantSeries(
                    symbol,
                    request.interval,
                    template.timestamps,
                    template.values,
                    source_count=template.source_count,
                )
                for symbol in symbols[: self.succeeded]
            },
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
    history: SavedHistory,
) -> StartExtremeDeviationRun:
    return StartExtremeDeviationRun(
        PlannedMaster(succeeded + failed + unexecuted),
        NeverMarket(),
        history,
        quant_market_data=PlannedQuant(succeeded, failed, unexecuted),
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        new_id=lambda: "run",
    )


def test_exactly_eighty_percent_extreme_tasks_save_partial() -> None:
    history = SavedHistory()

    result = planned_service(80, 0, 20, history).execute(
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.PARTIAL
    assert result.run_id is not None
    assert history.run is not None
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal("0.8")
    assert result.reliability.succeeded_tasks == 80
    assert result.reliability.failed_tasks == 0
    assert result.reliability.unexecuted_tasks == 20
    assert result.reliability.circuit_opened


def test_seventy_nine_percent_extreme_tasks_do_not_save() -> None:
    history = SavedHistory()

    result = planned_service(79, 1, 20, history).execute(
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.FAILED
    assert result.run_id is None
    assert history.run is None
    assert result.error_code == "insufficient_reliable_results"
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal("0.79")


def test_extreme_zero_valid_security_results_do_not_save() -> None:
    history = SavedHistory()

    result = planned_service(0, 1, 0, history).execute(
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.FAILED
    assert result.run_id is None
    assert history.run is None
    assert result.error_code == "insufficient_reliable_results"


def test_extreme_history_transaction_failure_returns_no_saved_run() -> None:
    service = StartExtremeDeviationRun(
        PlannedMaster(1),
        NeverMarket(),
        FailingHistory(),
        quant_market_data=PlannedQuant(1, 0, 0),
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        new_id=lambda: "run",
    )

    result = service.execute(
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.FAILED
    assert result.run_id is None
    assert result.error_code == "history_save_failed"


def test_extreme_watchlist_freeze_failure_never_saves() -> None:
    history = SavedHistory()
    service = StartExtremeDeviationRun(
        FailingMaster(),
        NeverMarket(),
        history,
        quant_market_data=CompactQuant(),
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        new_id=lambda: "run",
    )

    result = service.execute(
        ExtremeDeviationRequest(
            "missing",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        _context(),
    )

    assert result.status is ExtremeDeviationRunStatus.FAILED
    assert result.run_id is None
    assert result.error_code == "watchlist_freeze_failed"
    assert history.run is None


def test_extreme_cancellation_at_threshold_never_saves() -> None:
    registry = OperationRegistry(
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC)
    )
    registry.reserve("op", "key", "test")
    operation_context = registry.begin_reserved("op")
    assert operation_context is not None
    history = SavedHistory()

    def cancel_at_save(item) -> None:
        if item.stage == "SAVE":
            registry.cancel("op")

    service = StartExtremeDeviationRun(
        PlannedMaster(100),
        NeverMarket(),
        history,
        quant_market_data=PlannedQuant(80, 0, 20),
        clock=lambda: datetime(2026, 7, 27, tzinfo=UTC),
        new_id=lambda: "run",
        progress=cancel_at_save,
    )

    result = service.execute(
        ExtremeDeviationRequest(
            "pool",
            (CandleInterval.DAY,),
            date(2026, 7, 24),
        ),
        operation_context,
    )

    assert result.status is ExtremeDeviationRunStatus.CANCELED
    assert result.run_id is None
    assert history.run is None
