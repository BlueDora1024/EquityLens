"""Deterministic security profiles and daily close series."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    CandleSeries,
    DailySeriesProgress,
    DailySeriesProgressSink,
    MarketCandle,
    PricePoint,
    PriceSeries,
    SecuritySnapshot,
    SnapshotDataset,
)
from stock_toolbox.core.market_data.models import (
    DailyBarsDataset as BarsResult,
)
from stock_toolbox.core.market_data.quant import (
    QuantProgress,
    QuantProgressSink,
    QuantSeries,
    QuantSeriesDataset,
    QuantSeriesRequest,
)
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback
from stock_toolbox.core.securities.models import (
    AssetHint,
    ProviderProfile,
    ProviderProfileError,
    ProviderProfilesResult,
)

_DESCRIPTIONS = {
    "IREN.US": "Builds AI cloud data centers and operates Bitcoin mining infrastructure.",
    "NVDA.US": "Designs accelerated computing GPUs and AI data center platforms.",
    "AMD.US": "Designs CPUs, GPUs, and adaptive computing products.",
    "AAPL.US": "Designs consumer devices, software, and digital services.",
    "MSFT.US": "Provides cloud infrastructure, enterprise software, and AI services.",
}
_NAMES = {
    "IREN.US": "艾瑞恩",
    "NVDA.US": "英伟达",
    "AMD.US": "超威半导体",
    "AAPL.US": "苹果",
    "MSFT.US": "微软",
}
_EXCLUDED = {
    "TQQQ.US": "LEVERAGED_ETF",
    "SQQQ.US": "INVERSE_ETF",
    "SPY.US": "ETF",
    "QQQ.US": "ETF",
}


@dataclass(frozen=True, slots=True)
class VirtualProviderFault:
    target: str
    events: tuple[str, ...]
    symbol: str = ""
    start_index: int | None = None


class VirtualProvider:
    provider_id = "virtual"
    provider_display_name = "Virtual Provider"
    quant_script_versions = frozenset(
        {
            "daily-close-quant-v2",
            "turning-point-quant-v3",
        }
    )

    def __init__(
        self,
        *,
        profile_errors: dict[str, str] | None = None,
        bar_errors: dict[str, str] | None = None,
        fault_plan: tuple[VirtualProviderFault, ...] = (),
    ) -> None:
        self._profile_errors = dict(profile_errors or {})
        self._bar_errors = dict(bar_errors or {})
        self._fault_plan = tuple(fault_plan)
        self._fault_positions: dict[int, int] = {}
        self._external_call_count = 0
        self._attempted_symbols: list[str] = []
        self._unexecuted_symbols: list[str] = []
        self._feedback_kinds: list[str] = []
        self._daily_operation_control: OperationControl | None = None
        self._daily_rate_limit_count = 0
        self._daily_circuit_open = False
        self._daily_circuit_code = ""

    @property
    def external_call_count(self) -> int:
        """Number of deterministic symbol-level Provider requests."""

        return self._external_call_count

    @property
    def unexecuted_symbols(self) -> tuple[str, ...]:
        return tuple(self._unexecuted_symbols)

    @property
    def attempted_symbols(self) -> tuple[str, ...]:
        return tuple(self._attempted_symbols)

    @property
    def feedback_kinds(self) -> tuple[str, ...]:
        return tuple(self._feedback_kinds)

    def _record_external_calls(self, symbols: tuple[str, ...]) -> None:
        self._external_call_count += len(symbols)
        self._attempted_symbols.extend(symbols)

    def _fault_event(
        self,
        target: str,
        symbol: str,
        index: int,
    ) -> str:
        for fault_index, fault in enumerate(self._fault_plan):
            if fault.target != target:
                continue
            if fault.symbol and fault.symbol != symbol:
                continue
            if fault.start_index is not None:
                if index < fault.start_index:
                    continue
                return fault.events[0] if fault.events else ""
            position = self._fault_positions.get(fault_index, 0)
            if position >= len(fault.events):
                return ""
            self._fault_positions[fault_index] = position + 1
            return fault.events[position]
        return ""

    def _feedback(
        self,
        kind: FeedbackKind,
        code: str,
        symbol: str,
        *,
        attempt: int,
    ) -> RunFeedback:
        self._feedback_kinds.append(kind.value)
        try:
            failure_code = FailureCode(code)
        except ValueError:
            failure_code = None
        return RunFeedback(
            kind,
            failure_code,
            symbol,
            attempt=attempt,
            max_attempts=2,
            active_concurrency=1,
        )

    def get_security_profiles(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> ProviderProfilesResult:
        profiles = []
        errors = []
        for symbol in symbols:
            if operation_control.cancellation_requested():
                break
            self._record_external_calls((symbol,))
            error = self._profile_errors.get(symbol)
            if error is None and symbol.startswith("MISSING"):
                error = "symbol_unavailable"
            if error is not None:
                errors.append(ProviderProfileError(symbol, error))
                continue
            excluded_type = _EXCLUDED.get(symbol)
            if excluded_type is not None:
                asset_type = excluded_type
                reliability = "reliable"
            elif symbol == "IREN.US":
                asset_type = "UNKNOWN"
                reliability = "ambiguous"
            else:
                asset_type = "COMMON_STOCK"
                reliability = "reliable"
            code = symbol.removesuffix(".US")
            profiles.append(
                ProviderProfile(
                    symbol=symbol,
                    name=_NAMES.get(symbol, code),
                    market="US",
                    exchange="NASDAQ",
                    currency="USD",
                    listing_country="US",
                    description=_DESCRIPTIONS.get(
                        symbol,
                        f"{code} is a publicly traded operating company.",
                    ),
                    asset_hints=(AssetHint(asset_type, reliability),),
                    business_profile={
                        "company": {
                            "market": "NASDAQ",
                            "category": "Technology",
                            "founded": "2018",
                            "employees": "1,000",
                            "website": f"https://{code.casefold()}.example",
                        }
                    },
                    source_updated_at=datetime(2026, 7, 24, tzinfo=UTC),
                )
            )
        return ProviderProfilesResult(
            tuple(profiles),
            tuple(errors),
            "virtual",
        )

    def latest_completed_trading_day(
        self,
        *,
        operation_control: OperationControl,
        on_or_before: date | None = None,
    ) -> date | None:
        if operation_control.cancellation_requested():
            return None
        candidate = min(on_or_before or date(2026, 7, 24), date(2026, 7, 24))
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress: DailySeriesProgressSink | None = None,
    ) -> BarsResult:
        if operation_control is not self._daily_operation_control:
            self._daily_operation_control = operation_control
            self._daily_rate_limit_count = 0
            self._daily_circuit_open = False
            self._daily_circuit_code = ""
        series: dict[str, PriceSeries] = {}
        errors: dict[str, str] = {}
        succeeded = 0
        failed = 0
        ordered_symbols = tuple(sorted(symbols))
        for completed, symbol in enumerate(ordered_symbols, start=1):
            if operation_control.cancellation_requested():
                break
            feedback: RunFeedback | None = None
            if self._daily_circuit_open:
                errors[symbol] = "circuit_open"
                self._unexecuted_symbols.append(symbol)
                failed += 1
                feedback = self._feedback(
                    FeedbackKind.CIRCUIT_OPEN,
                    self._daily_circuit_code,
                    symbol,
                    attempt=0,
                )
                if progress is not None:
                    progress(
                        DailySeriesProgress(
                            completed,
                            len(ordered_symbols),
                            symbol,
                            succeeded,
                            failed,
                            feedback,
                        )
                    )
                continue
            self._record_external_calls((symbol,))
            error: str | None = self._fault_event(
                "daily",
                symbol,
                completed - 1,
            )
            if not error or error == "ok":
                error = self._bar_errors.get(symbol)
            elif error in {
                FailureCode.TIMEOUT.value,
                FailureCode.NETWORK_ERROR.value,
                FailureCode.SERVICE_UNAVAILABLE.value,
                FailureCode.RATE_LIMITED.value,
            }:
                if error == FailureCode.RATE_LIMITED.value:
                    self._daily_rate_limit_count += 1
                    self._daily_circuit_open = (
                        self._daily_rate_limit_count >= 2
                    )
                    if self._daily_circuit_open:
                        self._daily_circuit_code = error
                feedback = self._feedback(
                    (
                        FeedbackKind.CIRCUIT_OPEN
                        if self._daily_circuit_open
                        else (
                            FeedbackKind.THROTTLED
                            if error == FailureCode.RATE_LIMITED.value
                            else FeedbackKind.RETRYING
                        )
                    ),
                    error,
                    symbol,
                    attempt=1,
                )
                if not self._daily_circuit_open:
                    self._record_external_calls((symbol,))
                    retry_error = self._fault_event(
                        "daily",
                        symbol,
                        completed - 1,
                    )
                    if not retry_error or retry_error == "ok":
                        error = self._bar_errors.get(symbol)
                        if error is None:
                            feedback = self._feedback(
                                FeedbackKind.RECOVERED,
                                "",
                                symbol,
                                attempt=2,
                            )
                    else:
                        error = retry_error
                        if error == FailureCode.RATE_LIMITED.value:
                            self._daily_rate_limit_count += 1
                            self._daily_circuit_open = (
                                self._daily_rate_limit_count >= 2
                            )
                            self._daily_circuit_code = error
                            feedback = self._feedback(
                                FeedbackKind.CIRCUIT_OPEN,
                                error,
                                symbol,
                                attempt=2,
                            )
            if error in {
                FailureCode.AUTHENTICATION_FAILED.value,
                FailureCode.PERMISSION_DENIED.value,
                FailureCode.QUOTA_EXHAUSTED.value,
            }:
                self._daily_circuit_open = True
                self._daily_circuit_code = error
                feedback = self._feedback(
                    FeedbackKind.FATAL,
                    error,
                    symbol,
                    attempt=1,
                )
            if error is not None:
                errors[symbol] = error
                failed += 1
            else:
                points = []
                current = start_date
                ordinal = 0
                seed = int.from_bytes(
                    hashlib.sha256(symbol.encode()).digest()[:4],
                    "big",
                )
                base = Decimal(50 + seed % 250)
                drift = Decimal((seed % 19) - 6) / Decimal(10000)
                while current <= end_date:
                    if current.weekday() < 5:
                        wave = Decimal((ordinal % 11) - 5) / Decimal(1000)
                        close = base * (
                            Decimal(1) + drift * Decimal(ordinal) + wave
                        )
                        if close <= 0:
                            close = Decimal(1)
                        points.append(
                            PricePoint(
                                current,
                                close.quantize(Decimal("0.0001")),
                            )
                        )
                        ordinal += 1
                    current += timedelta(days=1)
                if not points:
                    errors[symbol] = "symbol_unavailable"
                    failed += 1
                else:
                    series[symbol] = PriceSeries(symbol, tuple(points))
                    succeeded += 1
            if progress is not None:
                progress(
                    DailySeriesProgress(
                        completed,
                        len(ordered_symbols),
                        symbol,
                        succeeded,
                        failed,
                        feedback,
                    )
                )
        return BarsResult("virtual", "Virtual Provider", series, errors)

    def get_quant_series(
        self,
        symbols: tuple[str, ...],
        request: QuantSeriesRequest,
        *,
        operation_control: OperationControl,
        progress: QuantProgressSink | None = None,
    ) -> QuantSeriesDataset:
        if request.series_names == (
            "high",
            "close",
            "high_ema26",
            "high_ema89",
            "dif",
            "hist",
            "volume",
        ):
            candles = self.get_candle_series(
                symbols,
                request.interval,
                220,
                request.end_at,
                operation_control=operation_control,
            )
            turning_output: dict[str, QuantSeries] = {}
            for index, symbol in enumerate(symbols, start=1):
                candle_source = candles.series_by_symbol.get(symbol)
                if candle_source is not None:
                    highs = tuple(
                        float(item.high)
                        for item in candle_source.candles
                    )
                    closes = tuple(
                        float(item.close)
                        for item in candle_source.candles
                    )
                    fast = _ema_float(closes, 12)
                    slow = _ema_float(closes, 26)
                    dif = tuple(
                        left - right
                        for left, right in zip(fast, slow, strict=True)
                    )
                    dea = _ema_float(dif, 9)
                    turning_output[symbol] = QuantSeries(
                        symbol,
                        request.interval,
                        tuple(
                            item.timestamp
                            for item in candle_source.candles
                        ),
                        {
                            "high": highs,
                            "close": closes,
                            "high_ema26": _ema_float(highs, 26),
                            "high_ema89": _ema_float(highs, 89),
                            "dif": dif,
                            "hist": tuple(
                                (left - right) * 2.0
                                for left, right in zip(
                                    dif,
                                    dea,
                                    strict=True,
                                )
                            ),
                            "volume": tuple(
                                float(item.volume)
                                for item in candle_source.candles
                            ),
                        },
                    )
                if progress is not None:
                    progress(
                        QuantProgress(
                            index,
                            len(symbols),
                            symbol,
                            len(turning_output),
                            index - len(turning_output),
                        )
                    )
            return QuantSeriesDataset(
                self.provider_id,
                self.provider_display_name,
                turning_output,
                candles.errors,
                fetched=len(turning_output),
            )
        if request.series_names != ("close",):
            return QuantSeriesDataset(
                self.provider_id,
                self.provider_display_name,
                {},
                {symbol: "unsupported_quant_script" for symbol in symbols},
            )
        daily = self.get_daily_series(
            symbols,
            request.start_at.date(),
            request.end_at.date(),
            operation_control=operation_control,
        )
        daily_output: dict[str, QuantSeries] = {}
        for index, symbol in enumerate(symbols, start=1):
            daily_source = daily.series_by_symbol.get(symbol)
            if daily_source is not None:
                timestamps = tuple(
                    datetime.combine(point.date, datetime.min.time(), UTC)
                    for point in daily_source.points
                )
                daily_output[symbol] = QuantSeries(
                    symbol,
                    request.interval,
                    timestamps,
                    {
                        "close": tuple(
                            float(point.close)
                            for point in daily_source.points
                        )
                    },
                )
            if progress is not None:
                progress(
                    QuantProgress(
                        index,
                        len(symbols),
                        symbol,
                        len(daily_output),
                        index - len(daily_output),
                    )
                )
        return QuantSeriesDataset(
            self.provider_id,
            self.provider_display_name,
            daily_output,
            daily.errors,
            fetched=len(daily_output),
        )

    def get_security_snapshots(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> SnapshotDataset:
        self._record_external_calls(symbols)
        snapshots: dict[str, SecuritySnapshot] = {}
        errors: dict[str, str] = {}
        for symbol in symbols:
            if operation_control.cancellation_requested():
                break
            if symbol in self._bar_errors:
                errors[symbol] = self._bar_errors[symbol]
                continue
            seed = int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:4], "big")
            snapshots[symbol] = SecuritySnapshot(
                symbol,
                Decimal(20 + seed % 280),
                Decimal(1_000_000_000 + seed % 40_000_000_000),
            )
        return SnapshotDataset("virtual", "Virtual Provider", snapshots, errors)

    def get_candle_series(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CandleDataset:
        self._record_external_calls(symbols)
        series: dict[str, CandleSeries] = {}
        errors: dict[str, str] = {}
        minutes = {
            CandleInterval.MIN_30: 30,
            CandleInterval.MIN_60: 60,
            CandleInterval.MIN_120: 120,
            CandleInterval.MIN_240: 240,
            CandleInterval.DAY: 24 * 60,
            CandleInterval.WEEK: 7 * 24 * 60,
        }[interval]
        for symbol in symbols:
            if operation_control.cancellation_requested():
                break
            error = self._bar_errors.get(symbol)
            if error is not None:
                errors[symbol] = error
                continue
            seed = int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:4], "big")
            matched_fixture: list[float] | None = None
            if symbol == "IREN.US" and count == 220:
                rng = random.Random(131)
                matched_fixture = []
                current_value = 200.0
                for index in range(count):
                    phase = index % 40
                    delta = -0.1 + rng.uniform(-1.4, 1.4)
                    if phase < 8:
                        delta -= 1.0
                    elif phase > 30:
                        delta += 0.7
                    current_value = max(5.0, current_value + delta)
                    matched_fixture.append(current_value)
                rebound_count = rng.randrange(1, 6)
                step = rng.uniform(0.8, 3.0)
                anchor = matched_fixture[-rebound_count - 1]
                matched_fixture[-rebound_count:] = [
                    anchor + offset * step
                    for offset in range(1, rebound_count + 1)
                ]
            base = 80.0 + float(seed % 100)
            candles: list[MarketCandle] = []
            for index in range(count):
                # A deterministic falling series with MACD cycles; some symbols
                # receive a late rebound so scenarios exercise both result paths.
                if matched_fixture is not None:
                    close = matched_fixture[index]
                else:
                    wave = ((index % 36) - 18) / 20.0
                    close = base - index * 0.08 + wave
                    if seed % 3 == 0 and index >= count - 4:
                        close += float(index - (count - 4)) * 2.5
                value = max(Decimal(1), Decimal(str(close))).quantize(
                    Decimal("0.0001")
                )
                timestamp = end_at - timedelta(minutes=minutes * (count - 1 - index))
                candles.append(
                    MarketCandle(
                        timestamp,
                        value,
                        value + Decimal("0.8"),
                        max(Decimal("0.01"), value - Decimal("0.8")),
                        value,
                        100_000 + index,
                    )
                )
            series[symbol] = CandleSeries(symbol, interval, tuple(candles))
        return CandleDataset(
            "virtual",
            "Virtual Provider",
            interval,
            series,
            errors,
        )


def _ema_float(
    values: tuple[float, ...],
    span: int,
) -> tuple[float, ...]:
    if not values:
        return ()
    alpha = 2.0 / (span + 1.0)
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (1.0 - alpha) * output[-1])
    return tuple(output)
