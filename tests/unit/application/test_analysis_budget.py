from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
)
from stock_toolbox.analyses.resource_budget import (
    AnalysisBudgetService,
    AnalysisBudgetSnapshot,
)
from stock_toolbox.analyses.rs_strength.application.models import RunRequest
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointRequest,
)
from stock_toolbox.core.market_data.models import (
    CandleInterval,
    MarketCandle,
    PricePoint,
    PriceSeries,
)
from stock_toolbox.core.market_data.provider_health import HistoryQuotaSnapshot
from stock_toolbox.core.market_data.quant import QuantSeries
from stock_toolbox.core.master_data.models import (
    SecurityDetailDTO,
    WatchlistDTO,
    WatchlistMembershipDTO,
)
from stock_toolbox.core.operations.storage_guard import (
    READY_FREE_BYTES,
    StorageCheck,
    StorageState,
)


class Master:
    def __init__(self, count: int) -> None:
        self.watchlist = WatchlistDTO(
            "pool",
            "Tech",
            1,
            tuple(
                WatchlistMembershipDTO(
                    f"membership-{index}",
                    f"security-{index}",
                    f"S{index}.US",
                    f"Security {index}",
                    f"binding-{index}",
                    "classification",
                    "科技",
                )
                for index in range(count)
            ),
        )

    def get_watchlist(self, watchlist_id: str) -> WatchlistDTO:
        assert watchlist_id == "pool"
        return self.watchlist

    def get_security(self, security_id: str) -> SecurityDetailDTO:
        membership = next(
            item for item in self.watchlist.memberships if item.security_id == security_id
        )
        return SecurityDetailDTO(
            membership.security_id,
            membership.canonical_symbol,
            membership.company_name,
            "NASDAQ",
            "USD",
            "US",
            None,
            {},
            "COMMON_STOCK",
            (),
        )


class Cache:
    def __init__(
        self,
        hit_symbols: set[str],
        provider_id: str = "longbridge",
    ) -> None:
        self.hit_symbols = hit_symbols
        self.provider_id = provider_id
        self.requests = []

    def load_many(self, provider_id, symbols, request):
        assert provider_id == self.provider_id
        self.requests.append(request)
        timestamp = datetime(2026, 7, 24, tzinfo=UTC)
        return {
            symbol: QuantSeries(
                symbol,
                request.interval,
                (timestamp,),
                {name: (1.0,) for name in request.series_names},
            )
            for symbol in symbols
            if symbol in self.hit_symbols
        }


class Storage:
    def __init__(self, check: StorageCheck) -> None:
        self.check = check
        self.calls = 0

    def inspect(self) -> StorageCheck:
        self.calls += 1
        return self.check


class CandleCache:
    def __init__(
        self,
        complete: set[tuple[str, CandleInterval]],
    ) -> None:
        self.complete = complete

    def covered_through(self, provider_id, symbol, interval):
        del provider_id
        return (
            datetime.combine(date(2026, 7, 24), time.max, UTC)
            if (symbol, interval) in self.complete
            else None
        )

    def load(self, provider_id, symbol, interval, end_at, limit):
        del provider_id, end_at
        if (symbol, interval) not in self.complete:
            return ()
        candle = MarketCandle(
            datetime(2026, 7, 24, tzinfo=UTC),
            Decimal(1),
            Decimal(1),
            Decimal(1),
            Decimal(1),
            0,
        )
        return (candle,) * limit


class DailyCache:
    def __init__(self, complete: set[str]) -> None:
        self.complete = complete

    def load(self, provider_id, symbol, start_date, end_date):
        del provider_id, start_date
        if symbol not in self.complete:
            return None
        return PriceSeries(symbol, (PricePoint(end_date, Decimal(1)),))


def service(
    count: int,
    hit_symbols: set[str] | None = None,
    storage: Storage | None = None,
    *,
    provider_id: str = "longbridge",
    history_quota=None,
    candle_cache=None,
    daily_cache=None,
):
    return AnalysisBudgetService(
        Master(count),
        Cache(hit_symbols or set(), provider_id),
        provider_id=provider_id,
        provider_display_name=("富途" if provider_id == "futu" else "Longbridge"),
        quant_script_versions=(
            frozenset()
            if provider_id == "futu"
            else {
                "daily-close-quant-v2",
                "turning-point-quant-v3",
                "extreme-deviation-original-v4",
            }
        ),
        storage_guard=storage,
        history_quota=history_quota,
        candle_cache=candle_cache,
        daily_cache=daily_cache,
    )


def test_rs_ranges_share_one_request_per_member() -> None:
    budget = service(600, {"S0.US", "S1.US"}).estimate_rs(
        RunRequest(
            "pool",
            "SPY.US",
            date(2026, 7, 24),
            ("1W", "2W", "1M", "3M", "6M", "1Y"),
            None,
        )
    )

    assert budget.member_count == 600
    assert budget.dimension_count == 6
    assert budget.total_tasks == 601
    assert budget.cache_hits == 2
    assert budget.cold_requests == 599
    assert budget.data_path == "Longbridge 服务端量化"


def test_turning_budget_counts_signals_and_worst_case_matched_annotations() -> None:
    budget = service(600).estimate_turning(
        TurningPointRequest(
            "pool",
            (
                CandleInterval.MIN_30,
                CandleInterval.MIN_60,
                CandleInterval.DAY,
            ),
            date(2026, 7, 24),
        )
    )

    assert budget.total_tasks == 1_806
    assert budget.cold_requests == 1_806
    assert budget.requires_confirmation is True
    assert budget.calculation_calls == 1_800
    assert budget.annotation_calls == 6


def test_turning_budget_only_counts_quant_cache_for_supported_periods() -> None:
    budget = service(2, {"S0.US"}).estimate_turning(
        TurningPointRequest(
            "pool",
            (CandleInterval.MIN_60, CandleInterval.MIN_120),
            date(2026, 7, 24),
        )
    )

    assert budget.cache_hits == 1
    assert budget.cold_requests == 6
    assert budget.calculation_calls == 5
    assert budget.annotation_calls == 1
    assert budget.data_path == "Longbridge 服务端量化 + 原生 2/4 小时 K 线"


def test_extreme_four_period_budget_requires_confirmation() -> None:
    budget = service(600).estimate_extreme(
        ExtremeDeviationRequest(
            "pool",
            (
                CandleInterval.MIN_30,
                CandleInterval.MIN_60,
                CandleInterval.DAY,
                CandleInterval.WEEK,
            ),
            date(2026, 7, 24),
        )
    )

    assert budget.total_tasks == 2_400
    assert budget.cold_requests == 9_600
    assert budget.calculation_calls == 9_600
    assert budget.requires_confirmation is True


def test_extreme_single_security_budget_resolves_global_security_without_watchlist() -> None:
    budget = service(1).estimate_extreme(
        ExtremeDeviationRequest(
            "",
            (CandleInterval.MIN_30,),
            date(2026, 7, 24),
            security_id="security-0",
        )
    )

    assert budget.member_count == 1
    assert budget.dimension_count == 1
    assert budget.total_tasks == 1


def test_budget_snapshot_carries_read_only_storage_preflight() -> None:
    storage = Storage(
        StorageCheck(
            StorageState.BLOCKED,
            123,
            error_code="storage_unavailable",
            reusable_bytes=456,
        )
    )

    budget = service(1, storage=storage).estimate_rs(
        RunRequest(
            "pool",
            "SPY.US",
            date(2026, 7, 24),
            ("3M",),
            None,
        )
    )

    assert budget.storage_state is StorageState.BLOCKED
    assert budget.free_bytes == 123
    assert budget.cache_cleaned is False
    assert budget.reusable_bytes == 456
    assert budget.effective_available_bytes == 579
    assert budget.error_code == "storage_unavailable"
    assert storage.calls == 1


def test_budget_snapshot_storage_defaults_keep_existing_construction_valid() -> None:
    budget = AnalysisBudgetSnapshot(1, 1, 2, 0, 2, 50, "virtual")

    assert budget.storage_state is StorageState.READY
    assert budget.free_bytes == READY_FREE_BYTES
    assert budget.cache_cleaned is False
    assert budget.reusable_bytes == 0
    assert budget.effective_available_bytes == READY_FREE_BYTES
    assert budget.error_code == ""


def test_futu_rs_quota_counts_distinct_new_symbols_once_across_ranges() -> None:
    budget = service(
        3,
        provider_id="futu",
        history_quota=lambda: HistoryQuotaSnapshot(
            99,
            2,
            frozenset({"S0.US", "SPY.US"}),
        ),
    ).estimate_rs(
        RunRequest(
            "pool",
            "SPY.US",
            date(2026, 7, 24),
            ("1W", "1M", "1Y"),
            None,
        )
    )

    assert budget.quota_remaining == 2
    assert budget.quota_new_symbols == 2
    assert budget.quota_shortfall == 0
    assert budget.requires_confirmation is False
    assert budget.cold_requests == 5
    assert budget.calculation_calls == 4
    assert budget.quota_checks == 1
    assert budget.minimum_seconds == 2.0
    assert budget.data_path == "富途本机 OpenD · 本地算法"
    assert budget.quota_notice == "富途历史额度：本次新增 2，剩余 2"


def test_futu_multi_period_quota_shortage_is_visible_before_kline_work() -> None:
    budget = service(
        3,
        provider_id="futu",
        history_quota=lambda: HistoryQuotaSnapshot(
            100,
            1,
            frozenset(),
        ),
    ).estimate_turning(
        TurningPointRequest(
            "pool",
            (
                CandleInterval.MIN_30,
                CandleInterval.DAY,
                CandleInterval.WEEK,
            ),
            date(2026, 7, 24),
        )
    )

    assert budget.quota_remaining == 1
    assert budget.quota_new_symbols == 3
    assert budget.quota_shortfall == 2
    assert budget.requires_confirmation is True
    assert budget.quota_notice == ("富途历史额度不足：本次新增 3，剩余 1，缺口 2")


def test_futu_quota_equal_to_new_symbols_allows_primary() -> None:
    budget = service(
        99,
        provider_id="futu",
        history_quota=lambda: HistoryQuotaSnapshot(
            100,
            98,
            frozenset({"S0.US", "SPY.US"}),
        ),
    ).estimate_rs(
        RunRequest("pool", "SPY.US", date(2026, 7, 24), ("1M",), None)
    )

    assert budget.quota_shortfall == 0
    assert budget.quota_blocked is False
    assert budget.can_confirm_primary is True


def test_futu_quota_shortfall_blocks_primary_and_allows_yahoo() -> None:
    budget = service(
        124,
        provider_id="futu",
        history_quota=lambda: HistoryQuotaSnapshot(
            100,
            98,
            frozenset({"S0.US", "SPY.US"}),
        ),
    ).estimate_rs(
        RunRequest("pool", "SPY.US", date(2026, 7, 24), ("1M",), None)
    )

    assert budget.quota_new_symbols == 123
    assert budget.quota_shortfall == 25
    assert budget.quota_blocked is True
    assert budget.can_confirm_primary is False
    assert budget.can_force_yahoo is True


def test_fresh_turning_candle_cache_does_not_consume_futu_symbol_quota() -> None:
    intervals = (CandleInterval.MIN_30, CandleInterval.DAY)
    budget = service(
        2,
        provider_id="futu",
        history_quota=lambda: HistoryQuotaSnapshot(100, 100, frozenset()),
        candle_cache=CandleCache({("S0.US", interval) for interval in intervals}),
    ).estimate_turning(
        TurningPointRequest("pool", intervals, date(2026, 7, 24))
    )

    assert budget.quota_new_symbols == 1


def test_fresh_rs_daily_cache_does_not_consume_futu_symbol_quota() -> None:
    budget = service(
        2,
        provider_id="futu",
        history_quota=lambda: HistoryQuotaSnapshot(100, 100, frozenset()),
        daily_cache=DailyCache({"SPY.US", "S0.US"}),
    ).estimate_rs(
        RunRequest("pool", "SPY.US", date(2026, 7, 24), ("1M",), None)
    )

    assert budget.quota_new_symbols == 1
