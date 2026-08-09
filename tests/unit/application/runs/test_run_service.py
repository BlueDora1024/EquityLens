from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from stock_toolbox.analyses.rs_strength.application.models import (
    BarsResult,
    RunProgress,
    RunRequest,
    RunStatus,
)
from stock_toolbox.analyses.rs_strength.application.service import StartRun
from stock_toolbox.analyses.rs_strength.domain.models import PricePoint, PriceSeries
from stock_toolbox.core.market_data.models import DailySeriesProgress
from stock_toolbox.core.master_data.models import (
    WatchlistDTO,
    WatchlistMembershipDTO,
)
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


def member(number: int, symbol: str, classification: str) -> WatchlistMembershipDTO:
    return WatchlistMembershipDTO(
        f"membership-{number}",
        f"security-{number}",
        symbol,
        symbol.removesuffix(".US"),
        f"binding-{number}",
        classification,
        classification,
    )


WATCHLIST = WatchlistDTO(
    "watchlist-1",
    "Tech",
    2,
    (
        member(1, "AAA.US", "AI"),
        member(2, "BBB.US", "AI"),
    ),
)


@dataclass
class Watchlists:
    watchlist: WatchlistDTO = WATCHLIST
    calls: int = 0

    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO:
        self.calls += 1
        assert watchlist_id == self.watchlist.id
        return self.watchlist


@dataclass
class Provider:
    result: BarsResult
    calls: list[tuple[str, ...]] = field(default_factory=list)
    date_calls: list[tuple[date, date]] = field(default_factory=list)

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: object,
        progress=None,
    ) -> BarsResult:
        del operation_control
        self.calls.append(symbols)
        self.date_calls.append((start_date, end_date))
        series_by_symbol = {
            symbol: self.result.series_by_symbol[symbol]
            for symbol in symbols
            if symbol in self.result.series_by_symbol
        }
        errors = {
            symbol: self.result.errors[symbol]
            for symbol in symbols
            if symbol in self.result.errors
        }
        if progress is not None:
            succeeded = 0
            failed = 0
            for completed, symbol in enumerate(symbols, start=1):
                succeeded += symbol in series_by_symbol
                failed += symbol in errors
                progress(
                    DailySeriesProgress(
                        completed,
                        len(symbols),
                        symbol,
                        succeeded,
                        failed,
                    )
                )
        return BarsResult(
            self.result.provider_id,
            self.result.provider_display_name,
            series_by_symbol,
            errors,
        )


class FeedbackProvider(Provider):
    feedback = RunFeedback(
        FeedbackKind.RETRYING,
        FailureCode.TIMEOUT,
        "AAA.US",
        attempt=2,
        max_attempts=2,
    )

    def get_daily_series(self, *args, progress=None, **kwargs) -> BarsResult:
        symbols = args[0]
        if progress is not None:
            progress(
                DailySeriesProgress(
                    0,
                    len(symbols),
                    symbols[0],
                    feedback=self.feedback,
                )
            )
        return super().get_daily_series(*args, progress=progress, **kwargs)


@dataclass
class History:
    snapshots: list[object] = field(default_factory=list)

    def save(self, snapshot: object, *, operation_control: object) -> bool:
        if not operation_control.try_enter_committing():  # type: ignore[attr-defined]
            return False
        self.snapshots.append(snapshot)
        return True


class RejectingHistory(History):
    def save(self, snapshot: object, *, operation_control: object) -> bool:
        del snapshot, operation_control
        return False


class CancelingHistory(History):
    def __init__(self, registry: OperationRegistry) -> None:
        super().__init__()
        self.registry = registry

    def save(self, snapshot: object, *, operation_control: object) -> bool:
        self.registry.cancel("op-1")
        return super().save(
            snapshot,
            operation_control=operation_control,
        )


def series(symbol: str, start: Decimal, end: Decimal) -> PriceSeries:
    return PriceSeries(
        symbol,
        (
            PricePoint(date(2026, 4, 24), start),
            PricePoint(date(2026, 7, 24), end),
        ),
    )


def stale_series(
    symbol: str,
    start: Decimal,
    prior_close: Decimal,
    latest_close: Decimal | None = None,
) -> PriceSeries:
    points = [
        PricePoint(date(2026, 4, 24), start),
        PricePoint(date(2026, 7, 23), prior_close),
    ]
    if latest_close is not None:
        points.append(PricePoint(date(2026, 7, 24), latest_close))
    return PriceSeries(symbol, tuple(points))


def start_context():
    registry = OperationRegistry(clock=lambda: NOW)
    registry.reserve("op-1", "key", "run")
    context = registry.begin_reserved("op-1")
    assert context is not None
    return context


def service(
    provider: Provider,
    history: History,
    progress: list[RunProgress],
    *,
    watchlist: WatchlistDTO = WATCHLIST,
) -> StartRun:
    ids = (
        f"50000000-0000-4000-8000-{number:012d}"
        for number in range(1, 10_000)
    )
    return StartRun(
        Watchlists(watchlist),
        provider,
        history,
        clock=lambda: NOW,
        new_id=lambda: next(ids),
        progress=progress.append,
    )


def test_run_fetches_benchmark_first_then_one_member_envelope() -> None:
    provider = Provider(
        BarsResult(
            provider_id="virtual",
            provider_display_name="Virtual",
            series_by_symbol={
                "SPY.US": series("SPY.US", Decimal(100), Decimal(110)),
                "AAA.US": series("AAA.US", Decimal(50), Decimal(60)),
                "BBB.US": series("BBB.US", Decimal(80), Decimal(88)),
            },
            errors={},
        )
    )
    history = History()
    progress: list[RunProgress] = []

    result = service(provider, history, progress).execute(
        RunRequest(WATCHLIST.id, "SPY.US", date(2026, 7, 24), ("3M",), None),
        start_context(),
    )

    assert result.status is RunStatus.READY
    assert provider.calls == [("SPY.US",), ("AAA.US", "BBB.US")]
    assert result.output is not None
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal(1)
    assert result.reliability.succeeded_tasks == 2
    assert len(result.output.stock_results) == 2
    assert len(history.snapshots) == 1
    assert tuple(dict.fromkeys(item.stage for item in progress)) == (
        "PREFLIGHT",
        "FETCHING",
        "VALIDATING",
        "CALCULATING",
        "AGGREGATING",
        "SAVING",
    )


def test_run_uses_recent_common_end_when_quant_members_are_one_day_stale() -> None:
    provider = Provider(
        BarsResult(
            "longbridge",
            "Longbridge",
            {
                "SPY.US": stale_series(
                    "SPY.US",
                    Decimal(100),
                    Decimal(109),
                    Decimal(110),
                ),
                "AAA.US": stale_series("AAA.US", Decimal(50), Decimal(60)),
                "BBB.US": stale_series("BBB.US", Decimal(80), Decimal(88)),
            },
            {},
        )
    )
    history = History()

    result = service(provider, history, []).execute(
        RunRequest(WATCHLIST.id, "SPY.US", date(2026, 7, 24), ("3M",), None),
        start_context(),
    )

    assert result.status is RunStatus.READY
    assert result.output is not None
    assert result.output.resolved_ranges[0].requested_end_date == date(2026, 7, 24)
    assert result.output.resolved_ranges[0].actual_end_date == date(2026, 7, 23)
    assert provider.calls == [("SPY.US",), ("AAA.US", "BBB.US")]
    assert len(history.snapshots) == 1


def test_run_does_not_align_to_a_date_below_eighty_percent_member_coverage() -> None:
    watchlist = _planned_watchlist(5)
    symbols = tuple(item.canonical_symbol for item in watchlist.memberships)
    provider = Provider(
        BarsResult(
            "longbridge",
            "Longbridge",
            {
                "SPY.US": stale_series(
                    "SPY.US",
                    Decimal(100),
                    Decimal(109),
                    Decimal(110),
                ),
                **{
                    symbol: stale_series(symbol, Decimal(50), Decimal(60))
                    for symbol in symbols[:3]
                },
                **{
                    symbol: PriceSeries(
                        symbol,
                        (PricePoint(date(2026, 4, 24), Decimal(50)),),
                    )
                    for symbol in symbols[3:]
                },
            },
            {},
        )
    )
    history = History()

    result = service(
        provider,
        history,
        [],
        watchlist=watchlist,
    ).execute(
        RunRequest(watchlist.id, "SPY.US", date(2026, 7, 24), ("3M",), None),
        start_context(),
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "insufficient_reliable_results"
    assert history.snapshots == []
    assert provider.calls == [("SPY.US",), symbols]


def test_run_forwards_provider_feedback_to_analysis_progress() -> None:
    provider = FeedbackProvider(
        BarsResult(
            "virtual",
            "Virtual",
            {
                "SPY.US": series("SPY.US", Decimal(100), Decimal(110)),
                "AAA.US": series("AAA.US", Decimal(50), Decimal(60)),
                "BBB.US": series("BBB.US", Decimal(80), Decimal(88)),
            },
            {},
        )
    )
    progress: list[RunProgress] = []

    service(provider, History(), progress).execute(
        RunRequest(WATCHLIST.id, "SPY.US", date(2026, 7, 24), ("3M",), None),
        start_context(),
    )

    assert next(item.feedback for item in progress if item.feedback is not None) == (
        FeedbackProvider.feedback
    )


def test_member_provider_error_below_eighty_percent_never_saves() -> None:
    provider = Provider(
        BarsResult(
            provider_id="virtual",
            provider_display_name="Virtual",
            series_by_symbol={
                "SPY.US": series("SPY.US", Decimal(100), Decimal(110)),
                "AAA.US": series("AAA.US", Decimal(50), Decimal(60)),
            },
            errors={"BBB.US": "timeout"},
        )
    )
    history = History()

    progress: list[RunProgress] = []
    result = service(provider, history, progress).execute(
        RunRequest(WATCHLIST.id, "SPY.US", date(2026, 7, 24), ("3M",), None),
        start_context(),
    )

    assert result.status is RunStatus.FAILED
    assert result.run_id is None
    assert result.error_code == "insufficient_reliable_results"
    assert result.output is not None
    assert result.output.failed_member_count == 1
    assert history.snapshots == []
    fetched = next(
        item
        for item in progress
        if item.stage == "FETCHING" and item.completed == item.total
    )
    assert fetched.current == "BBB.US"
    assert fetched.succeeded == 2
    assert fetched.failed == 1


def _planned_watchlist(count: int) -> WatchlistDTO:
    return WatchlistDTO(
        "planned-watchlist",
        "Planned",
        1,
        tuple(
            member(index, f"S{index:03d}.US", "AI")
            for index in range(count)
        ),
    )


def _planned_provider(succeeded: int, failed: int, unexecuted: int) -> Provider:
    total = succeeded + failed + unexecuted
    symbols = tuple(f"S{index:03d}.US" for index in range(total))
    return Provider(
        BarsResult(
            "virtual",
            "Virtual",
            {
                "SPY.US": series("SPY.US", Decimal(100), Decimal(110)),
                **{
                    symbol: series(symbol, Decimal(50), Decimal(60))
                    for symbol in symbols[:succeeded]
                },
            },
            {
                **{
                    symbol: "timeout"
                    for symbol in symbols[succeeded : succeeded + failed]
                },
                **{
                    symbol: "circuit_open"
                    for symbol in symbols[succeeded + failed :]
                },
            },
        )
    )


def test_exactly_eighty_percent_saves_one_partial_run() -> None:
    watchlist = _planned_watchlist(100)
    history = History()
    provider = _planned_provider(80, 0, 20)

    result = service(
        provider,
        history,
        [],
        watchlist=watchlist,
    ).execute(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M",),
            None,
        ),
        start_context(),
    )

    assert result.status is RunStatus.PARTIAL
    assert result.run_id is not None
    assert len(history.snapshots) == 1
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal("0.8")
    assert result.reliability.succeeded_tasks == 80
    assert result.reliability.failed_tasks == 0
    assert result.reliability.unexecuted_tasks == 20
    assert result.reliability.circuit_opened
    assert provider.calls == [
        ("SPY.US",),
        tuple(item.canonical_symbol for item in watchlist.memberships),
    ]


def test_seventy_nine_percent_fails_without_history() -> None:
    watchlist = _planned_watchlist(100)
    history = History()
    provider = _planned_provider(79, 1, 20)

    result = service(
        provider,
        history,
        [],
        watchlist=watchlist,
    ).execute(
        RunRequest(
            watchlist.id,
            "SPY.US",
            date(2026, 7, 24),
            ("3M",),
            None,
        ),
        start_context(),
    )

    assert result.status is RunStatus.FAILED
    assert result.run_id is None
    assert history.snapshots == []
    assert result.error_code == "insufficient_reliable_results"
    assert result.reliability is not None
    assert result.reliability.success_rate == Decimal("0.79")
    assert result.reliability.failed_tasks == 1
    assert result.reliability.unexecuted_tasks == 20
    assert provider.calls == [
        ("SPY.US",),
        tuple(item.canonical_symbol for item in watchlist.memberships),
    ]


def test_rs_history_transaction_failure_returns_no_saved_run() -> None:
    history = RejectingHistory()

    result = service(
        _planned_provider(1, 0, 0),
        history,
        [],
        watchlist=_planned_watchlist(1),
    ).execute(
        RunRequest(
            "planned-watchlist",
            "SPY.US",
            date(2026, 7, 24),
            ("3M",),
            None,
        ),
        start_context(),
    )

    assert result.status is RunStatus.FAILED
    assert result.run_id is None
    assert history.snapshots == []
    assert result.error_code == "HISTORY_SAVE_FAILED"


def test_rs_cancellation_at_save_never_writes_history() -> None:
    registry = OperationRegistry(clock=lambda: NOW)
    registry.reserve("op-1", "key", "run")
    context = registry.begin_reserved("op-1")
    assert context is not None
    history = CancelingHistory(registry)
    provider = _planned_provider(80, 0, 20)

    result = service(
        provider,
        history,
        [],
        watchlist=_planned_watchlist(100),
    ).execute(
        RunRequest(
            "planned-watchlist",
            "SPY.US",
            date(2026, 7, 24),
            ("3M",),
            None,
        ),
        context,
    )

    assert result.status is RunStatus.CANCELED
    assert result.run_id is None
    assert history.snapshots == []
    assert provider.calls == [
        ("SPY.US",),
        tuple(f"S{index:03d}.US" for index in range(100)),
    ]


def test_benchmark_error_is_fatal_and_never_saves_history() -> None:
    provider = Provider(
        BarsResult(
            "virtual",
            "Virtual",
            {},
            {"SPY.US": "symbol_unavailable"},
        )
    )
    history = History()

    result = service(provider, history, []).execute(
        RunRequest(WATCHLIST.id, "SPY.US", date(2026, 7, 24), ("3M",), None),
        start_context(),
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "BENCHMARK_FETCH_FAILED"
    assert provider.calls == [("SPY.US",)]
    assert history.snapshots == []


def test_preflight_rejects_bad_benchmark_and_empty_ranges_before_provider_io() -> None:
    provider = Provider(BarsResult("virtual", "Virtual", {}, {}))
    history = History()

    result = service(provider, history, []).execute(
        RunRequest(WATCHLIST.id, "DIA.US", date(2026, 7, 24), (), None),
        start_context(),
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "PREFLIGHT_FAILED"
    assert provider.calls == []


def test_preflight_rejects_today_before_provider_io() -> None:
    provider = Provider(BarsResult("virtual", "Virtual", {}, {}))

    result = service(provider, History(), []).execute(
        RunRequest(WATCHLIST.id, "SPY.US", NOW.date(), ("3M",), None),
        start_context(),
    )

    assert result.status is RunStatus.FAILED
    assert result.error_code == "HISTORICAL_DATE_REQUIRED"
    assert provider.calls == []


def test_short_presets_use_week_and_calendar_month_boundaries() -> None:
    service_under_test = service(
        Provider(BarsResult("virtual", "Virtual", {}, {})),
        History(),
        [],
    )
    ranges = service_under_test._ranges(
        RunRequest(
            WATCHLIST.id,
            "SPY.US",
            date(2026, 7, 24),
            ("1W", "2W", "1M"),
            None,
        )
    )

    assert [
        (item.key, item.label, item.requested_start_date)
        for item in ranges
    ] == [
        ("1W", "近 1 周", date(2026, 7, 17)),
        ("2W", "近 2 周", date(2026, 7, 10)),
        ("1M", "近 1 个月", date(2026, 6, 24)),
    ]


def test_rs_fetches_one_four_workday_probe_envelope() -> None:
    provider = Provider(
        BarsResult(
            "virtual",
            "Virtual",
            {
                "SPY.US": series("SPY.US", Decimal(100), Decimal(110)),
                "AAA.US": series("AAA.US", Decimal(10), Decimal(12)),
                "BBB.US": series("BBB.US", Decimal(20), Decimal(22)),
            },
            {},
        )
    )

    result = service(provider, History(), []).execute(
        RunRequest(WATCHLIST.id, "SPY.US", date(2026, 7, 24), ("3M",), None),
        start_context(),
    )

    assert result.status is RunStatus.READY
    assert provider.date_calls == [
        (date(2026, 4, 20), date(2026, 7, 24)),
        (date(2026, 4, 20), date(2026, 7, 24)),
    ]
