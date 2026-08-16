"""Futu OpenAPI adapter for provider-independent market-data contracts."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from time import monotonic, sleep
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    CandleSeries,
    DailyBarsDataset,
    DailySeriesProgress,
    DailySeriesProgressSink,
    MarketCandle,
    PricePoint,
    PriceSeries,
    SecuritySnapshot,
    SnapshotDataset,
)
from stock_toolbox.core.market_data.provider_health import (
    HistoryQuotaSnapshot,
)
from stock_toolbox.core.operations.failure_policy import CircuitBreaker, FailureCode
from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.core.securities.models import (
    AssetHint,
    ProviderProfile,
    ProviderProfileError,
    ProviderProfilesResult,
)

_NEW_YORK = ZoneInfo("America/New_York")
_PROFILE_BATCH_SIZE = 100
_SNAPSHOT_BATCH_SIZE = 400
_HISTORY_PAGE_SIZE = 1000
_SUCCESS = 0
_DAILY_FIELDS = ("1", "3")
_CANDLE_FIELDS = ("1", "2", "3", "4", "5", "8")
_ASSET_TYPES = {
    "STOCK": "COMMON_STOCK",
    "ETF": "ETF",
    "FUND": "FUND",
    "REIT": "REIT",
    "BOND": "BOND",
    "WARRANT": "WARRANT",
    "FUTURE": "FUTURE",
    "CRYPTO": "CRYPTO",
}


class FutuQuotePort(Protocol):
    def get_global_state(self) -> tuple[int, object]: ...

    def get_stock_basicinfo(
        self,
        market: object,
        stock_type: object = "STOCK",
        code_list: Sequence[str] | None = None,
    ) -> tuple[int, object]: ...

    def get_market_snapshot(
        self,
        code_list: Sequence[str],
    ) -> tuple[int, object]: ...

    def get_owner_plate(
        self,
        code_list: Sequence[str],
    ) -> tuple[int, object]: ...

    def request_trading_days(
        self,
        market: object = None,
        start: str | None = None,
        end: str | None = None,
        code: str | None = None,
    ) -> tuple[int, object]: ...

    def get_history_kl_quota(
        self,
        get_detail: bool = False,
    ) -> tuple[int, object]: ...

    def request_history_kline(
        self,
        code: str,
        start: str | None = None,
        end: str | None = None,
        ktype: object = "K_DAY",
        autype: object = "qfq",
        fields: Sequence[object] = ("",),
        max_count: int = 1000,
        page_req_key: object | None = None,
        extended_time: bool = False,
        session: object = "N/A",
    ) -> tuple[int, object, object | None]: ...


class FutuProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _RateLimiter:
    def __init__(
        self,
        minimum_interval: float,
        *,
        clock: Callable[[], float],
        sleeper: Callable[[float], None],
    ) -> None:
        self._minimum_interval = max(0.0, minimum_interval)
        self._clock = clock
        self._sleep = sleeper
        self._last_request = float("-inf")
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._minimum_interval - (self._clock() - self._last_request)
            if delay > 0:
                self._sleep(delay)
            self._last_request = self._clock()


def to_futu_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized.endswith(".US"):
        raise ValueError("only canonical US symbols are supported")
    return f"US.{normalized.removesuffix('.US')}"


def from_futu_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized.startswith("US.") or len(normalized) <= 3:
        raise ValueError("only Futu US symbols are supported")
    return f"{normalized.removeprefix('US.')}.US"


def futu_kl_type(interval: CandleInterval) -> str:
    return {
        CandleInterval.MIN_30: "K_30M",
        CandleInterval.MIN_60: "K_60M",
        CandleInterval.MIN_120: "K_120M",
        CandleInterval.MIN_240: "K_240M",
        CandleInterval.DAY: "K_DAY",
        CandleInterval.WEEK: "K_WEEK",
    }[interval]


def _records(value: object) -> tuple[Mapping[str, object], ...]:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        raw = to_dict("records")
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raw = value
    else:
        raise TypeError("Futu response is not tabular")
    if not isinstance(raw, Sequence):
        raise TypeError("Futu tabular response is malformed")
    output: list[Mapping[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("Futu row is malformed")
        output.append(cast(Mapping[str, object], item))
    return tuple(output)


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    candidate = Decimal(str(value))
    return candidate if candidate.is_finite() else None


def _error_code(value: object) -> str:
    message = str(value).casefold()
    if "not login" in message or "未登录" in message:
        return "futu_quote_not_logged_in"
    if "permission" in message or "权限" in message:
        return "permission_denied"
    if "frequency" in message or "too frequent" in message or "频率" in message:
        return "rate_limited"
    if "quota" in message or "额度" in message:
        return "quota_exhausted"
    if "timeout" in message or "超时" in message:
        return "timeout"
    return "provider_error"


class FutuProvider:
    provider_id = "futu"
    provider_display_name = "富途"
    quant_script_versions: frozenset[str] = frozenset()

    def __init__(
        self,
        quote_context: FutuQuotePort,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        minimum_request_interval: float = 0.5,
        monotonic_clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
        max_retries: int = 1,
    ) -> None:
        self._quote = quote_context
        self._clock = clock
        self._history_limiter = _RateLimiter(
            minimum_request_interval,
            clock=monotonic_clock,
            sleeper=sleeper,
        )
        self._max_retries = max(0, max_retries)
        self._history_quota_snapshot: HistoryQuotaSnapshot | None = None
        self._history_quota_authorized: set[str] = set()
        self._history_breaker = CircuitBreaker()
        self._last_error_code = ""

    @property
    def last_error_code(self) -> str:
        return self._last_error_code

    def close(self) -> None:
        close = getattr(self._quote, "close", None)
        if callable(close):
            close()

    def latest_completed_trading_day(
        self,
        *,
        operation_control: OperationControl,
        on_or_before: date | None = None,
    ) -> date | None:
        if operation_control.cancellation_requested():
            return None
        now = self._clock().astimezone(_NEW_YORK)
        candidate = now.date()
        if now.time() < time(16):
            candidate -= timedelta(days=1)
        if on_or_before is not None:
            candidate = min(candidate, on_or_before)
        begin = candidate - timedelta(days=28)
        try:
            ret, raw = self._quote.request_trading_days(
                market="US",
                start=begin.isoformat(),
                end=candidate.isoformat(),
            )
            if ret != _SUCCESS:
                self._last_error_code = _error_code(raw)
                return None
            days = tuple(
                date.fromisoformat(str(row.get("time", "")))
                for row in _records(raw)
                if str(row.get("time", ""))
            )
        except (TypeError, ValueError):
            self._last_error_code = "malformed_data"
            return None
        eligible = tuple(day for day in days if day <= candidate)
        self._last_error_code = "" if eligible else "symbol_unavailable"
        return max(eligible) if eligible else None

    def get_security_profiles(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> ProviderProfilesResult:
        normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols))
        profiles: list[ProviderProfile] = []
        errors: list[ProviderProfileError] = []
        order = {symbol: index for index, symbol in enumerate(normalized)}
        for offset in range(0, len(normalized), _PROFILE_BATCH_SIZE):
            batch = normalized[offset : offset + _PROFILE_BATCH_SIZE]
            if operation_control.cancellation_requested():
                break
            futu_symbols = [to_futu_symbol(symbol) for symbol in batch]
            try:
                ret, raw = self._quote.get_stock_basicinfo(
                    "US",
                    "STOCK",
                    futu_symbols,
                )
                if ret != _SUCCESS:
                    code = _error_code(raw)
                    errors.extend(ProviderProfileError(symbol, code) for symbol in batch)
                    continue
                rows = {
                    from_futu_symbol(str(row.get("code", ""))): row
                    for row in _records(raw)
                    if str(row.get("code", "")).startswith("US.")
                }
                plate_rows = self._plate_rows(futu_symbols)
            except (TypeError, ValueError):
                errors.extend(ProviderProfileError(symbol, "malformed_data") for symbol in batch)
                continue
            plates_by_symbol: dict[str, list[Mapping[str, object]]] = {}
            for plate_row in plate_rows:
                try:
                    symbol = from_futu_symbol(str(plate_row.get("code", "")))
                except ValueError:
                    continue
                plates_by_symbol.setdefault(symbol, []).append(plate_row)
            for symbol in batch:
                static_row = rows.get(symbol)
                if static_row is None:
                    errors.append(ProviderProfileError(symbol, "symbol_unavailable"))
                    continue
                if bool(static_row.get("delisting", False)):
                    errors.append(ProviderProfileError(symbol, "security_delisted"))
                    continue
                raw_type = str(static_row.get("stock_type", "")).strip().upper()
                asset_type = _ASSET_TYPES.get(raw_type, "UNKNOWN")
                company = self._company_from_plates(plates_by_symbol.get(symbol, []))
                business_profile: dict[str, object] = {
                    "stock_type": raw_type,
                    "exchange": str(static_row.get("exchange_type", "")).strip(),
                }
                if company:
                    business_profile["company"] = company
                name = str(static_row.get("name", "")).strip()
                if not name or name.casefold() in {
                    "unknown stock",
                    "未知股票",
                }:
                    errors.append(ProviderProfileError(symbol, "symbol_unavailable"))
                    continue
                profiles.append(
                    ProviderProfile(
                        symbol,
                        name,
                        "US",
                        str(static_row.get("exchange_type", "")).strip() or None,
                        "USD",
                        "US",
                        None,
                        (AssetHint(asset_type, "reliable"),),
                        business_profile,
                        None,
                    )
                )
        profiles.sort(key=lambda profile: order[profile.symbol])
        errors.sort(key=lambda error: order[error.symbol])
        return ProviderProfilesResult(
            tuple(profiles),
            tuple(errors),
            self.provider_id,
        )

    def get_security_snapshots(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> SnapshotDataset:
        normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols))
        snapshots: dict[str, SecuritySnapshot] = {}
        errors: dict[str, str] = {}
        for offset in range(0, len(normalized), _SNAPSHOT_BATCH_SIZE):
            batch = normalized[offset : offset + _SNAPSHOT_BATCH_SIZE]
            if operation_control.cancellation_requested():
                break
            futu_symbols = [to_futu_symbol(symbol) for symbol in batch]
            try:
                ret, raw = self._quote.get_market_snapshot(futu_symbols)
                if ret != _SUCCESS:
                    errors.update({symbol: _error_code(raw) for symbol in batch})
                    continue
                rows = {
                    from_futu_symbol(str(row.get("code", ""))): row
                    for row in _records(raw)
                    if str(row.get("code", "")).startswith("US.")
                }
                for symbol in batch:
                    row = rows.get(symbol)
                    if row is None:
                        errors[symbol] = "symbol_unavailable"
                        continue
                    snapshots[symbol] = SecuritySnapshot(
                        symbol,
                        _optional_decimal(row.get("last_price")),
                        _optional_decimal(row.get("total_market_val")),
                    )
            except (InvalidOperation, TypeError, ValueError):
                errors.update({symbol: "malformed_data" for symbol in batch})
        return SnapshotDataset(
            self.provider_id,
            self.provider_display_name,
            snapshots,
            errors,
        )

    def _plate_rows(
        self,
        futu_symbols: list[str],
    ) -> tuple[Mapping[str, object], ...]:
        ret, raw = self._quote.get_owner_plate(futu_symbols)
        return _records(raw) if ret == _SUCCESS else ()

    @staticmethod
    def _company_from_plates(
        rows: Sequence[Mapping[str, object]],
    ) -> dict[str, str]:
        company: dict[str, str] = {}
        for row in rows:
            name = str(row.get("plate_name", "")).strip()
            kind = str(row.get("plate_type", "")).strip().upper()
            if not name:
                continue
            if kind == "INDUSTRY" and "sector" not in company:
                company["sector"] = name
            elif kind == "CONCEPT" and "category" not in company:
                company["category"] = name
        return company

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress: DailySeriesProgressSink | None = None,
    ) -> DailyBarsDataset:
        normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols))
        blocked = self._quota_block(normalized, operation_control)
        if blocked is not None:
            return self._blocked_daily_result(
                normalized,
                blocked,
                progress,
            )
        series: dict[str, PriceSeries] = {}
        errors: dict[str, str] = {}
        succeeded = 0
        failed = 0
        circuit_open = False
        for completed, symbol in enumerate(normalized, start=1):
            if operation_control.cancellation_requested():
                errors[symbol] = "canceled"
                failed += 1
            else:
                rows, error = self._history_rows(
                    symbol,
                    CandleInterval.DAY,
                    start_date,
                    end_date,
                    _DAILY_FIELDS,
                    operation_control,
                )
                if error is not None:
                    errors[symbol] = error
                    failed += 1
                    circuit_open = self._record_history_failure(error)
                else:
                    try:
                        points_by_day = {
                            date.fromisoformat(str(row.get("time_key", ""))[:10]): PricePoint(
                                date.fromisoformat(str(row.get("time_key", ""))[:10]),
                                self._required_price(row.get("close")),
                            )
                            for row in rows
                            if start_date
                            <= date.fromisoformat(str(row.get("time_key", ""))[:10])
                            <= end_date
                        }
                    except (
                        InvalidOperation,
                        TypeError,
                        ValueError,
                    ):
                        errors[symbol] = "malformed_data"
                        failed += 1
                    else:
                        points = tuple(points_by_day[day] for day in sorted(points_by_day))
                        if points:
                            series[symbol] = PriceSeries(symbol, points)
                            succeeded += 1
                        else:
                            errors[symbol] = "symbol_unavailable"
                            failed += 1
            if progress is not None:
                progress(
                    DailySeriesProgress(
                        completed,
                        len(normalized),
                        symbol,
                        succeeded,
                        failed,
                    )
                )
            if circuit_open:
                remaining = normalized[completed:]
                errors.update({item: "circuit_open" for item in remaining})
                if progress is not None:
                    for offset, item in enumerate(remaining, start=completed + 1):
                        failed += 1
                        progress(
                            DailySeriesProgress(
                                offset,
                                len(normalized),
                                item,
                                succeeded,
                                failed,
                            )
                        )
                break
        return DailyBarsDataset(
            self.provider_id,
            self.provider_display_name,
            series,
            errors,
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
        normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols))
        blocked = self._quota_block(normalized, operation_control)
        if blocked is not None:
            return CandleDataset(
                self.provider_id,
                self.provider_display_name,
                interval,
                {},
                {symbol: blocked for symbol in normalized},
            )
        end_date = end_at.astimezone(_NEW_YORK).date()
        start_date = end_date - timedelta(days=self._calendar_span(interval, count))
        series: dict[str, CandleSeries] = {}
        errors: dict[str, str] = {}
        for index, symbol in enumerate(normalized):
            if operation_control.cancellation_requested():
                errors[symbol] = "canceled"
                continue
            rows, error = self._history_rows(
                symbol,
                interval,
                start_date,
                end_date,
                _CANDLE_FIELDS,
                operation_control,
            )
            if error is not None:
                errors[symbol] = error
                if self._record_history_failure(error):
                    errors.update({item: "circuit_open" for item in normalized[index + 1 :]})
                    break
                continue
            try:
                by_timestamp = {
                    self._timestamp(row.get("time_key")): MarketCandle(
                        self._timestamp(row.get("time_key")),
                        self._required_price(row.get("open")),
                        self._required_price(row.get("high")),
                        self._required_price(row.get("low")),
                        self._required_price(row.get("close")),
                        self._volume(row.get("volume")),
                    )
                    for row in rows
                }
                candles = tuple(by_timestamp[timestamp] for timestamp in sorted(by_timestamp))[
                    -count:
                ]
                if not candles:
                    errors[symbol] = "symbol_unavailable"
                    continue
                series[symbol] = CandleSeries(symbol, interval, candles)
            except (
                InvalidOperation,
                TypeError,
                ValueError,
            ):
                errors[symbol] = "malformed_data"
        return CandleDataset(
            self.provider_id,
            self.provider_display_name,
            interval,
            series,
            errors,
        )

    def get_history_quota(
        self,
        *,
        operation_control: OperationControl | None = None,
    ) -> HistoryQuotaSnapshot:
        if operation_control is not None and operation_control.cancellation_requested():
            raise FutuProviderError("canceled")
        self._history_breaker = CircuitBreaker()
        try:
            ret, raw = self._quote.get_history_kl_quota(True)
            if ret != _SUCCESS:
                raise FutuProviderError(_error_code(raw))
            if (
                not isinstance(raw, Sequence)
                or isinstance(raw, (str, bytes, bytearray))
                or len(raw) != 3
            ):
                raise FutuProviderError("malformed_data")
            used = int(raw[0])
            remaining = int(raw[1])
            reusable = frozenset(
                from_futu_symbol(str(row.get("code", "")))
                for row in _records(raw[2])
                if str(row.get("code", "")).startswith("US.")
            )
            snapshot = HistoryQuotaSnapshot(used, remaining, reusable)
            # Resource preflight and the following calculation share this
            # immutable snapshot.  The next explicit preflight still refreshes
            # it from OpenD, so the cache does not outlive a user action.
            self._history_quota_snapshot = snapshot
            return snapshot
        except FutuProviderError:
            raise
        except (TypeError, ValueError) as exception:
            raise FutuProviderError("malformed_data") from exception

    def _quota_block(
        self,
        symbols: tuple[str, ...],
        operation_control: OperationControl,
    ) -> str | None:
        if set(symbols).issubset(self._history_quota_authorized):
            return None
        quota = self._history_quota_snapshot
        if quota is None:
            try:
                quota = self.get_history_quota(operation_control=operation_control)
            except FutuProviderError as exception:
                return exception.code
            self._history_quota_snapshot = quota
        new_symbols = {
            symbol
            for symbol in symbols
            if symbol not in quota.reusable_symbols and symbol not in self._history_quota_authorized
        }
        if len(new_symbols) > quota.remaining:
            return "quota_exhausted"
        self._history_quota_authorized.update(symbols)
        if new_symbols:
            self._history_quota_snapshot = HistoryQuotaSnapshot(
                quota.used + len(new_symbols),
                quota.remaining - len(new_symbols),
                quota.reusable_symbols | frozenset(new_symbols),
            )
        return None

    def _record_history_failure(self, code: str) -> bool:
        try:
            failure = FailureCode(code)
        except ValueError:
            return False
        return self._history_breaker.record(failure)

    def _history_rows(
        self,
        symbol: str,
        interval: CandleInterval,
        start_date: date,
        end_date: date,
        fields: tuple[str, ...],
        operation_control: OperationControl,
    ) -> tuple[tuple[Mapping[str, object], ...], str | None]:
        rows: list[Mapping[str, object]] = []
        page_key: object | None = None
        for _page in range(100):
            if operation_control.cancellation_requested():
                return (), "canceled"
            response: tuple[int, object, object | None] | None = None
            error = "provider_error"
            for attempt in range(self._max_retries + 1):
                if page_key is None:
                    self._history_limiter.wait()
                try:
                    response = self._quote.request_history_kline(
                        to_futu_symbol(symbol),
                        start=start_date.isoformat(),
                        end=end_date.isoformat(),
                        ktype=futu_kl_type(interval),
                        autype="None",
                        # The real Futu SDK validates this parameter as a
                        # concrete list.  A tuple works with our protocol
                        # fakes but is rejected by OpenD as provider_error.
                        fields=list(fields),
                        max_count=_HISTORY_PAGE_SIZE,
                        page_req_key=page_key,
                        extended_time=False,
                        session="RTH",
                    )
                except TimeoutError:
                    error = "timeout"
                    if attempt < self._max_retries:
                        continue
                    return (), error
                except OSError:
                    error = "network_error"
                    if attempt < self._max_retries:
                        continue
                    return (), error
                ret, raw, next_key = response
                if ret == _SUCCESS:
                    break
                error = _error_code(raw)
                response = None
                if error in {"timeout", "rate_limited"} and attempt < self._max_retries:
                    continue
                return (), error
            if response is None:
                return (), error
            _ret, raw, next_key = response
            try:
                rows.extend(_records(raw))
            except TypeError:
                return (), "malformed_data"
            if next_key is None:
                return tuple(rows), None
            page_key = next_key
        return tuple(rows), "partial_data"

    def _blocked_daily_result(
        self,
        symbols: tuple[str, ...],
        code: str,
        progress: DailySeriesProgressSink | None,
    ) -> DailyBarsDataset:
        if progress is not None:
            for completed, symbol in enumerate(symbols, start=1):
                progress(
                    DailySeriesProgress(
                        completed,
                        len(symbols),
                        symbol,
                        0,
                        completed,
                    )
                )
        return DailyBarsDataset(
            self.provider_id,
            self.provider_display_name,
            {},
            {symbol: code for symbol in symbols},
        )

    @staticmethod
    def _required_price(value: object) -> Decimal:
        candidate = _optional_decimal(value)
        if candidate is None or candidate <= 0:
            raise ValueError("price is invalid")
        return candidate

    @staticmethod
    def _volume(value: object) -> int:
        candidate = int(Decimal(str(value)))
        if candidate < 0:
            raise ValueError("volume is invalid")
        return candidate

    @staticmethod
    def _timestamp(value: object) -> datetime:
        text = str(value).strip()
        return datetime.fromisoformat(text).replace(tzinfo=_NEW_YORK)

    @staticmethod
    def _calendar_span(
        interval: CandleInterval,
        count: int,
    ) -> int:
        bars_per_day = {
            CandleInterval.MIN_30: 13,
            CandleInterval.MIN_60: 7,
            CandleInterval.MIN_120: 4,
            CandleInterval.MIN_240: 2,
            CandleInterval.DAY: 1,
            CandleInterval.WEEK: 0.2,
        }[interval]
        trading_days = math.ceil(max(1, count) / bars_per_day)
        return math.ceil(trading_days * 7 / 5) + 14
