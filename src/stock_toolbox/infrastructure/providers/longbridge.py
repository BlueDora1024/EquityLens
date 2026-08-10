"""Longbridge Python SDK adapter for profiles and unadjusted daily closes."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from math import isfinite
from threading import Event, Lock
from time import monotonic, sleep
from typing import Any, Protocol, TypeVar
from zoneinfo import ZoneInfo

from longbridge.openapi import (
    AdjustType,
    CalcIndex,
    ErrorKind,
    Market,
    OpenApiException,
    Period,
)

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
from stock_toolbox.core.operations.failure_policy import (
    CircuitBreaker,
    FailureCode,
)
from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.core.operations.run_feedback import FeedbackKind, RunFeedback
from stock_toolbox.core.securities.models import (
    AssetHint,
    ProviderProfile,
    ProviderProfileError,
    ProviderProfilesResult,
)

_NEW_YORK = ZoneInfo("America/New_York")
_LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo or UTC
_DAILY_SERIES_CONCURRENCY = 4
_QUANT_CONCURRENCY = 2
_QUANT_RATE_LIMIT_COOLDOWN_SECONDS = 10.0
_DAILY_PAGE_SIZE = 1000
_CANCELLABLE_RETRY_WAIT_SECONDS = 5.0
_ADJUSTED_OHLC_ABSOLUTE_TOLERANCE = Decimal("0.01")
_ADJUSTED_OHLC_RELATIVE_TOLERANCE = Decimal("0.0002")
_RETRYABLE_ERRORS = frozenset(
    {
        "timeout",
        "rate_limited",
        "network_error",
        "service_unavailable",
        "malformed_quant_response",
    }
)
_FATAL_QUANT_FAILURES = frozenset(
    {
        FailureCode.AUTHENTICATION_FAILED,
        FailureCode.PERMISSION_DENIED,
        FailureCode.QUOTA_EXHAUSTED,
    }
)
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class _QuantTask:
    symbol: str
    attempt: int = 0
    previous_failure: FailureCode | None = None
    wait_seconds: float = 0


class LongbridgeQuotePort(Protocol):
    def static_info(self, symbols: Sequence[str]) -> Sequence[Any]: ...

    def history_candlesticks_by_offset(
        self,
        symbol: str,
        period: object,
        adjust_type: object,
        forward: bool,
        count: int,
        timestamp: datetime | None = None,
    ) -> Sequence[Any]: ...

    def trading_days(
        self,
        market: object,
        begin: date,
        end: date,
    ) -> Any: ...

    def calc_indexes(
        self,
        symbols: Sequence[str],
        indexes: Sequence[object],
    ) -> Sequence[Any]: ...


class LongbridgeAsyncQuotePort(Protocol):
    async def history_candlesticks_by_offset(
        self,
        symbol: str,
        period: object,
        adjust_type: object,
        forward: bool,
        count: int,
        timestamp: datetime | None = None,
    ) -> Sequence[Any]: ...


class LongbridgeFundamentalPort(Protocol):
    def company(self, symbol: str) -> Any: ...


class LongbridgeHttpPort(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object],
    ) -> object: ...


class LongbridgeProvider:
    quant_script_versions = frozenset(
        {
            "daily-close-quant-v2",
            "turning-point-quant-v3",
        }
    )
    provider_id = "longbridge"
    provider_display_name = "Longbridge"

    def __init__(
        self,
        quote_context: LongbridgeQuotePort,
        *,
        fundamental_context: LongbridgeFundamentalPort | None = None,
        async_quote_factory: Callable[[], LongbridgeAsyncQuotePort] | None = None,
        quant_http_factory: Callable[[], LongbridgeHttpPort] | None = None,
        max_pages_per_symbol: int = 20,
        max_retries: int = 1,
        sleeper: Callable[[float], None] = sleep,
        async_sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        quant_request_interval_seconds: float = 0.0,
        monotonic_clock: Callable[[], float] = monotonic,
        quant_waiter: Callable[[float, OperationControl], bool] | None = None,
    ) -> None:
        self._quote = quote_context
        self._fundamental = fundamental_context
        self._async_quote_factory = async_quote_factory
        self._quant_http_factory = quant_http_factory
        self._max_pages = max_pages_per_symbol
        self._max_retries = max(0, max_retries)
        self._sleep = sleeper
        self._async_sleep = async_sleeper
        self._clock = clock
        self._quant_request_interval = max(0.0, quant_request_interval_seconds)
        self._monotonic = monotonic_clock
        self._quant_waiter = quant_waiter
        self._quant_pacing_lock = Lock()
        self._next_quant_request_at = 0.0

    def get_quant_series(
        self,
        symbols: tuple[str, ...],
        request: QuantSeriesRequest,
        *,
        operation_control: OperationControl,
        progress: QuantProgressSink | None = None,
    ) -> QuantSeriesDataset:
        """Execute one server-side script per symbol with bounded concurrency."""
        if request.interval in {
            CandleInterval.MIN_120,
            CandleInterval.MIN_240,
        }:
            return QuantSeriesDataset(
                self.provider_id,
                self.provider_display_name,
                {},
                {
                    symbol: "quant_interval_unsupported"
                    for symbol in symbols
                },
            )
        if self._quant_http_factory is None:
            return QuantSeriesDataset(
                self.provider_id,
                self.provider_display_name,
                {},
                {symbol: "quant_unavailable" for symbol in symbols},
            )
        normalized = tuple(
            dict.fromkeys(
                symbol.strip().upper()
                for symbol in symbols
                if symbol.strip()
            )
        )
        completed: dict[str, QuantSeries] = {}
        errors: dict[str, str] = {}
        finished = 0
        planned = deque(_QuantTask(symbol) for symbol in normalized)
        deferred: deque[_QuantTask] = deque()
        futures: dict[Future[QuantSeries], _QuantTask] = {}
        # One request first validates auth/permission before opening the batch.
        concurrency = 1
        throttled = False
        rate_limit_seen = False
        breaker = CircuitBreaker()
        rate_limit_observed = Event()
        stop_failure_code: FailureCode | None = None
        stop_error = ""

        def report(
            symbol: str,
            feedback: RunFeedback | None = None,
        ) -> None:
            if progress is not None:
                progress(
                    QuantProgress(
                        finished,
                        len(normalized),
                        symbol,
                        len(completed),
                        len(errors),
                        feedback=feedback,
                    )
                )

        def feedback(
            kind: FeedbackKind,
            task: _QuantTask,
            code: FailureCode | None = None,
            *,
            wait_seconds: float = 0,
            max_attempts: int = 0,
        ) -> RunFeedback:
            return RunFeedback(
                kind,
                code,
                task.symbol,
                request.interval.value,
                task.attempt + 1,
                max_attempts,
                wait_seconds,
                concurrency,
            )

        def execute(task: _QuantTask) -> QuantSeries:
            try:
                if not self._wait_for_quant_request(operation_control):
                    raise _QuantCanceled
                return self._quant_series_attempt(
                    task,
                    request,
                    operation_control,
                )
            except Exception as exception:
                if self._failure_code(exception) is FailureCode.RATE_LIMITED:
                    rate_limit_observed.set()
                raise

        executor = ThreadPoolExecutor(
            max_workers=min(_QUANT_CONCURRENCY, max(1, len(normalized))),
            thread_name_prefix="longbridge-quant",
        )
        try:
            while planned or deferred or futures:
                if operation_control.cancellation_requested():
                    stop_error = "canceled"
                    break

                if throttled and not futures and deferred:
                    while deferred:
                        planned.appendleft(deferred.pop())
                    throttled = False

                while (
                    planned
                    and len(futures) < concurrency
                    and not throttled
                    and not rate_limit_observed.is_set()
                    and not operation_control.cancellation_requested()
                ):
                    task = planned.popleft()
                    future = executor.submit(execute, task)
                    futures[future] = task

                if operation_control.cancellation_requested():
                    stop_error = "canceled"
                    break
                if not futures:
                    break

                done, _pending = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    task = futures.pop(future)
                    try:
                        series = future.result()
                    except _QuantCanceled:
                        errors[task.symbol] = "canceled"
                        finished += 1
                        report(task.symbol)
                        continue
                    except Exception as exception:  # noqa: BLE001 - provider boundary
                        code = self._failure_code(exception)
                        error_code = self._quant_error_code(code)
                        breaker_open = breaker.record(code)

                        if code is FailureCode.RATE_LIMITED:
                            rate_limit_observed.clear()
                            rate_limit_seen = True
                            concurrency = 1
                            if breaker_open:
                                errors[task.symbol] = error_code
                                finished += 1
                                report(
                                    task.symbol,
                                    feedback(
                                        FeedbackKind.CIRCUIT_OPEN,
                                        task,
                                        code,
                                    ),
                                )
                                stop_failure_code = code
                                stop_error = "circuit_open"
                                break

                            retry_limit = 0 if self._max_retries == 0 else 2
                            if task.attempt >= retry_limit:
                                errors[task.symbol] = error_code
                                finished += 1
                                report(
                                    task.symbol,
                                    feedback(
                                        FeedbackKind.ITEM_SKIPPED,
                                        task,
                                        code,
                                        max_attempts=retry_limit + 1,
                                    ),
                                )
                                continue

                            throttled = True
                            max_attempts = retry_limit + 1
                            wait_seconds = self._retry_after_seconds(
                                exception,
                                fallback_seconds=_QUANT_RATE_LIMIT_COOLDOWN_SECONDS,
                            )
                            report(
                                task.symbol,
                                feedback(
                                    FeedbackKind.THROTTLED,
                                    task,
                                    code,
                                    wait_seconds=wait_seconds,
                                    max_attempts=max_attempts,
                                ),
                            )
                            retry = _QuantTask(
                                task.symbol,
                                attempt=task.attempt + 1,
                                previous_failure=code,
                                wait_seconds=wait_seconds,
                            )
                            report(
                                task.symbol,
                                feedback(
                                    FeedbackKind.RETRYING,
                                    retry,
                                    code,
                                    wait_seconds=wait_seconds,
                                    max_attempts=max_attempts,
                                ),
                            )
                            deferred.appendleft(retry)
                            continue

                        if breaker_open:
                            errors[task.symbol] = error_code
                            finished += 1
                            concurrency = 1
                            report(
                                task.symbol,
                                feedback(
                                    FeedbackKind.CIRCUIT_OPEN,
                                    task,
                                    code,
                                ),
                            )
                            stop_failure_code = code
                            stop_error = "circuit_open"
                            break

                        if code in _FATAL_QUANT_FAILURES:
                            errors[task.symbol] = error_code
                            finished += 1
                            report(
                                task.symbol,
                                feedback(FeedbackKind.FATAL, task, code),
                            )
                            stop_failure_code = code
                            stop_error = error_code
                            break

                        retry_limit = self._quant_retry_limit(code)
                        if task.attempt < retry_limit:
                            wait_seconds = float(2**task.attempt)
                            retry = _QuantTask(
                                task.symbol,
                                attempt=task.attempt + 1,
                                previous_failure=code,
                                wait_seconds=wait_seconds,
                            )
                            report(
                                task.symbol,
                                feedback(
                                    FeedbackKind.RETRYING,
                                    retry,
                                    code,
                                    wait_seconds=wait_seconds,
                                    max_attempts=retry_limit + 1,
                                ),
                            )
                            if throttled:
                                deferred.append(retry)
                            else:
                                planned.appendleft(retry)
                            continue

                        errors[task.symbol] = error_code
                        finished += 1
                        report(
                            task.symbol,
                            feedback(
                                FeedbackKind.ITEM_SKIPPED,
                                task,
                                code,
                                max_attempts=retry_limit + 1,
                            ),
                        )
                        continue

                    completed[task.symbol] = series
                    finished += 1
                    recovered = (
                        feedback(
                            FeedbackKind.RECOVERED,
                            task,
                            task.previous_failure,
                        )
                        if task.previous_failure is not None
                        else None
                    )
                    report(task.symbol, recovered)
                    if (
                        concurrency == 1
                        and task.previous_failure is None
                        and not rate_limit_seen
                    ):
                        concurrency = min(
                            _QUANT_CONCURRENCY,
                            len(normalized),
                        )
                if stop_error:
                    break
        finally:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)

        def drain_stopped_futures() -> list[_QuantTask]:
            nonlocal finished
            unexecuted: list[_QuantTask] = []
            for future, task in futures.items():
                if future.cancelled():
                    unexecuted.append(task)
                    continue
                try:
                    series = future.result()
                except _QuantCanceled:
                    unexecuted.append(task)
                    continue
                except Exception as exception:  # noqa: BLE001 - provider boundary
                    code = self._failure_code(exception)
                    errors[task.symbol] = self._quant_error_code(code)
                    finished += 1
                    kind = (
                        FeedbackKind.FATAL
                        if code in _FATAL_QUANT_FAILURES
                        else FeedbackKind.ITEM_SKIPPED
                    )
                    report(
                        task.symbol,
                        feedback(
                            kind,
                            task,
                            code,
                            max_attempts=task.attempt + 1,
                        ),
                    )
                    continue

                completed[task.symbol] = series
                finished += 1
                recovered = (
                    feedback(
                        FeedbackKind.RECOVERED,
                        task,
                        task.previous_failure,
                    )
                    if task.previous_failure is not None
                    else None
                )
                report(task.symbol, recovered)
            return unexecuted

        if stop_error and stop_error != "canceled":
            unexecuted = (
                list(planned)
                + list(deferred)
                + drain_stopped_futures()
            )
            seen = set(errors) | set(completed)
            for task in unexecuted:
                if task.symbol in seen:
                    continue
                seen.add(task.symbol)
                errors[task.symbol] = stop_error
                finished += 1
                kind = (
                    FeedbackKind.CIRCUIT_OPEN
                    if stop_error == "circuit_open"
                    else FeedbackKind.FATAL
                )
                report(
                    task.symbol,
                    feedback(
                        kind,
                        task,
                        stop_failure_code,
                    ),
                )
        elif stop_error:
            remaining = list(planned) + list(deferred) + list(futures.values())
            seen = set(errors) | set(completed)
            for task in remaining:
                if task.symbol in seen:
                    continue
                seen.add(task.symbol)
                errors[task.symbol] = stop_error
                finished += 1
                report(task.symbol)
        return QuantSeriesDataset(
            self.provider_id,
            self.provider_display_name,
            completed,
            errors,
            fetched=len(completed),
        )

    def _wait_for_quant_request(
        self,
        operation_control: OperationControl,
    ) -> bool:
        """Pace direct quant HTTP starts below the account-wide quote limit."""
        if operation_control.cancellation_requested():
            return False
        interval = self._quant_request_interval
        if interval <= 0:
            return True
        with self._quant_pacing_lock:
            if operation_control.cancellation_requested():
                return False
            now = self._monotonic()
            wait_seconds = max(0.0, self._next_quant_request_at - now)
            if wait_seconds > 0:
                canceled = (
                    self._quant_waiter(wait_seconds, operation_control)
                    if self._quant_waiter is not None
                    else operation_control.wait_for_cancellation(wait_seconds)
                )
                if canceled:
                    return False
                now = self._monotonic()
            self._next_quant_request_at = max(
                self._next_quant_request_at,
                now,
            ) + interval
        return not operation_control.cancellation_requested()

    def _quant_series_attempt(
        self,
        task: _QuantTask,
        request: QuantSeriesRequest,
        operation_control: OperationControl,
    ) -> QuantSeries:
        factory = self._quant_http_factory
        assert factory is not None
        if operation_control.cancellation_requested():
            raise _QuantCanceled
        if task.wait_seconds and not self._wait_before_retry(
            task.wait_seconds,
            operation_control,
        ):
            raise _QuantCanceled
        if operation_control.cancellation_requested():
            raise _QuantCanceled
        body: dict[str, object] = {
            "counter_id": _counter_id(task.symbol),
            "start_time": int(request.start_at.timestamp()),
            "end_time": int(
                (request.end_at + timedelta(days=1)).timestamp()
            ),
            "script": request.script,
            "inputs_json": "[]",
            "line_type": _quant_line_type(request.interval),
            "language": 0,
            "exclude_chart": False,
        }

        response = factory().request(
            "POST",
            "/v2/quant/run_script",
            body=body,
        )
        if not isinstance(response, dict):
            raise _MalformedQuantResponse
        try:
            timestamps = _quant_timestamps(response.get("events_json"))
            values = _quant_values(
                response.get("chart_json"),
                request.series_names,
                len(timestamps),
            )
            included = tuple(
                index
                for index, timestamp in enumerate(timestamps)
                if timestamp <= request.end_at
            )
            source_count = len(included)
            retained = (
                included[-request.retain_last :]
                if request.retain_last is not None
                else included
            )
            return QuantSeries(
                task.symbol,
                request.interval,
                tuple(timestamps[index] for index in retained),
                {
                    name: tuple(series[index] for index in retained)
                    for name, series in values.items()
                },
                source_count,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise _MalformedQuantResponse from error

    def _quant_retry_limit(self, code: FailureCode) -> int:
        configured = self._max_retries
        if configured == 0:
            return 0
        if code in {FailureCode.NETWORK_ERROR, FailureCode.TIMEOUT}:
            return min(max(configured, 2), 2)
        if code in {
            FailureCode.SERVICE_UNAVAILABLE,
            FailureCode.MALFORMED_RESPONSE,
        }:
            return min(max(configured, 2), 2)
        return 0

    def _wait_before_retry(
        self,
        seconds: float,
        operation_control: OperationControl,
    ) -> bool:
        if operation_control.cancellation_requested():
            return False
        if (
            self._sleep is sleep
            or seconds >= _CANCELLABLE_RETRY_WAIT_SECONDS
        ):
            return not operation_control.wait_for_cancellation(seconds)
        self._sleep(seconds)
        return not operation_control.cancellation_requested()

    def _retry_after_seconds(
        self,
        exception: Exception,
        *,
        fallback_seconds: float,
    ) -> float:
        """Honor exposed Retry-After metadata, otherwise use controlled fallback.

        Longbridge ``OpenApiException`` exposes kind/code/trace/message only,
        while compatible HTTP transports may expose response headers.
        """
        raw: object | None = getattr(exception, "retry_after", None)
        for source in (
            getattr(exception, "headers", None),
            getattr(getattr(exception, "response", None), "headers", None),
        ):
            if source is None:
                continue
            try:
                raw = next(
                    value
                    for key, value in source.items()
                    if str(key).casefold() == "retry-after"
                )
            except (AttributeError, StopIteration):
                continue
            break
        if raw is not None:
            try:
                seconds = float(str(raw))
            except (TypeError, ValueError):
                try:
                    deadline = parsedate_to_datetime(str(raw))
                    if deadline.tzinfo is None:
                        deadline = deadline.replace(tzinfo=UTC)
                    seconds = (
                        deadline.astimezone(UTC) - self._clock().astimezone(UTC)
                    ).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    seconds = -1
            if isfinite(seconds) and seconds >= 0:
                return seconds
        return fallback_seconds

    @classmethod
    def _failure_code(cls, exception: Exception) -> FailureCode:
        legacy = cls._error_code(exception)
        return {
            "timeout": FailureCode.TIMEOUT,
            "network_error": FailureCode.NETWORK_ERROR,
            "service_unavailable": FailureCode.SERVICE_UNAVAILABLE,
            "rate_limited": FailureCode.RATE_LIMITED,
            "quota_exhausted": FailureCode.QUOTA_EXHAUSTED,
            "authentication_failed": FailureCode.AUTHENTICATION_FAILED,
            "permission_denied": FailureCode.PERMISSION_DENIED,
            "malformed_quant_response": FailureCode.MALFORMED_RESPONSE,
            "data_unavailable": FailureCode.DATA_UNAVAILABLE,
            "insufficient_data": FailureCode.INSUFFICIENT_DATA,
        }.get(legacy, FailureCode.INTERNAL)

    @staticmethod
    def _quant_error_code(code: FailureCode) -> str:
        if code is FailureCode.MALFORMED_RESPONSE:
            return "malformed_quant_response"
        if code is FailureCode.INTERNAL:
            return "provider_error"
        return code.value

    def latest_completed_trading_day(
        self,
        *,
        operation_control: OperationControl,
        on_or_before: date | None = None,
    ) -> date | None:
        if operation_control.cancellation_requested():
            return None
        local_now = self._clock().astimezone(_NEW_YORK)
        candidate = local_now.date()
        if local_now.time() < time(16):
            candidate -= timedelta(days=1)
        if on_or_before is not None:
            candidate = min(candidate, on_or_before)
        begin = candidate - timedelta(days=28)
        response, error = self._attempt(
            lambda: self._quote.trading_days(
                Market.US,
                begin,
                candidate,
            ),
            operation_control,
        )
        if error is not None or response is None:
            return None
        try:
            trading_days = tuple(response.trading_days)
        except Exception:  # noqa: BLE001 - SDK boundary
            return None
        eligible = tuple(
            item for item in trading_days if isinstance(item, date) and item <= candidate
        )
        return max(eligible) if eligible else None

    def get_security_profiles(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> ProviderProfilesResult:
        profiles: list[ProviderProfile] = []
        errors: list[ProviderProfileError] = []
        for index in range(0, len(symbols), 100):
            batch = symbols[index : index + 100]
            if operation_control.cancellation_requested():
                break

            def fetch_batch(
                current: tuple[str, ...] = batch,
            ) -> Sequence[Any]:
                return self._quote.static_info(current)

            response, error = self._attempt(
                fetch_batch,
                operation_control,
            )
            if error is not None or response is None:
                errors.extend(
                    ProviderProfileError(
                        symbol,
                        error or "provider_error",
                    )
                    for symbol in batch
                )
                continue
            by_symbol = {str(item.symbol).upper(): item for item in response}
            for symbol in batch:
                item = by_symbol.get(symbol)
                if item is None:
                    errors.append(
                        ProviderProfileError(
                            symbol,
                            "symbol_unavailable",
                        )
                    )
                    continue
                board = str(getattr(item, "board", ""))
                asset_hint = self._asset_hint(board)
                chinese_name = str(getattr(item, "name_cn", "") or "").strip()
                name = (
                    chinese_name
                    or str(getattr(item, "name_en", "") or "")
                    or str(getattr(item, "name_hk", "") or "")
                    or symbol.removesuffix(".US")
                )
                description = None
                business_profile: dict[str, Any] = {"board": board}
                if self._fundamental is not None:

                    def fetch_company(
                        current_symbol: str = symbol,
                    ) -> Any:
                        assert self._fundamental is not None
                        return self._fundamental.company(current_symbol)

                    company, _company_error = self._attempt(
                        fetch_company,
                        operation_control,
                    )
                    if company is not None:
                        company_name = self._optional_text(
                            getattr(company, "company_name", None)
                        ) or self._optional_text(getattr(company, "name", None))
                        if company_name is not None and not chinese_name:
                            name = company_name
                        description = self._optional_text(getattr(company, "profile", None))
                        company_fields = {
                            key: value
                            for key, value in (
                                (
                                    "market",
                                    self._optional_text(getattr(company, "market", None)),
                                ),
                                (
                                    "region",
                                    self._optional_text(getattr(company, "region", None)),
                                ),
                                (
                                    "sector",
                                    self._optional_text(getattr(company, "sector", None)),
                                ),
                                (
                                    "category",
                                    self._optional_text(getattr(company, "category", None)),
                                ),
                                (
                                    "founded",
                                    self._optional_text(getattr(company, "founded", None)),
                                ),
                                (
                                    "employees",
                                    self._optional_text(getattr(company, "employees", None)),
                                ),
                                (
                                    "website",
                                    self._optional_text(getattr(company, "website", None)),
                                ),
                            )
                            if value is not None
                        }
                        if company_fields:
                            business_profile["company"] = company_fields
                profiles.append(
                    ProviderProfile(
                        symbol=symbol,
                        name=name,
                        market="US",
                        exchange=self._optional_text(getattr(item, "exchange", None)),
                        currency=self._optional_text(getattr(item, "currency", None)),
                        listing_country="US",
                        description=description,
                        asset_hints=(asset_hint,),
                        business_profile=business_profile,
                        source_updated_at=None,
                    )
                )
        profile_order = {symbol: index for index, symbol in enumerate(symbols)}
        profiles.sort(key=lambda item: profile_order[item.symbol])
        errors.sort(key=lambda item: profile_order[item.symbol])
        return ProviderProfilesResult(
            tuple(profiles),
            tuple(errors),
            "longbridge",
        )

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress: DailySeriesProgressSink | None = None,
    ) -> BarsResult:
        if self._async_quote_factory is not None:
            return asyncio.run(
                self._get_daily_series_async(
                    symbols,
                    start_date,
                    end_date,
                    operation_control,
                    progress,
                )
            )
        series: dict[str, PriceSeries] = {}
        errors: dict[str, str] = {}
        succeeded = 0
        failed = 0
        for completed, symbol in enumerate(symbols, start=1):
            if operation_control.cancellation_requested():
                break
            points, error = self._series(symbol, start_date, end_date, operation_control)
            if error is not None:
                errors[symbol] = error
                failed += 1
            elif points:
                series[symbol] = PriceSeries(symbol, points)
                succeeded += 1
            else:
                errors[symbol] = "symbol_unavailable"
                failed += 1
            if progress is not None:
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
            "longbridge",
            "Longbridge",
            series,
            errors,
        )

    async def _get_daily_series_async(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        operation_control: OperationControl,
        progress: DailySeriesProgressSink | None,
    ) -> BarsResult:
        quote = self._async_quote_factory
        assert quote is not None
        async_quote = quote()
        semaphore = asyncio.Semaphore(_DAILY_SERIES_CONCURRENCY)
        completed = 0
        succeeded = 0
        failed = 0
        results: dict[str, tuple[tuple[PricePoint, ...], str | None]] = {}

        async def fetch(symbol: str) -> None:
            nonlocal completed, succeeded, failed
            async with semaphore:
                if operation_control.cancellation_requested():
                    return
                result = await self._series_async(
                    async_quote,
                    symbol,
                    start_date,
                    end_date,
                    operation_control,
                )
            results[symbol] = result
            completed += 1
            points, error = result
            if error is None and points:
                succeeded += 1
            else:
                failed += 1
            if progress is not None:
                progress(
                    DailySeriesProgress(
                        completed,
                        len(symbols),
                        symbol,
                        succeeded,
                        failed,
                    )
                )

        await asyncio.gather(*(fetch(symbol) for symbol in symbols))
        series: dict[str, PriceSeries] = {}
        errors: dict[str, str] = {}
        for symbol in symbols:
            result = results.get(symbol)
            if result is None:
                continue
            points, error = result
            if error is not None:
                errors[symbol] = error
            elif points:
                series[symbol] = PriceSeries(symbol, points)
            else:
                errors[symbol] = "symbol_unavailable"
        return BarsResult("longbridge", "Longbridge", series, errors)

    def get_security_snapshots(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> SnapshotDataset:
        snapshots: dict[str, SecuritySnapshot] = {}
        errors: dict[str, str] = {}
        for index in range(0, len(symbols), 100):
            batch = symbols[index : index + 100]

            def fetch_indexes(
                current: tuple[str, ...] = batch,
            ) -> Sequence[Any]:
                return self._quote.calc_indexes(
                    current,
                    (CalcIndex.LastDone, CalcIndex.TotalMarketValue),
                )

            response, error = self._attempt(
                fetch_indexes,
                operation_control,
            )
            if response is None:
                errors.update({symbol: error or "provider_error" for symbol in batch})
                continue
            by_symbol = {str(item.symbol).upper(): item for item in response}
            for symbol in batch:
                raw = by_symbol.get(symbol)
                if raw is None:
                    errors[symbol] = "symbol_unavailable"
                    continue
                try:
                    last = self._optional_decimal(getattr(raw, "last_done", None))
                    market_value = self._optional_decimal(getattr(raw, "total_market_value", None))
                except (InvalidOperation, TypeError, ValueError):
                    errors[symbol] = "malformed_data"
                    continue
                snapshots[symbol] = SecuritySnapshot(symbol, last, market_value)
        return SnapshotDataset("longbridge", "Longbridge", snapshots, errors)

    def get_candle_series(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CandleDataset:
        period = {
            CandleInterval.MIN_30: Period.Min_30,
            CandleInterval.MIN_60: Period.Min_60,
            CandleInterval.MIN_120: Period.Min_120,
            CandleInterval.MIN_240: Period.Min_240,
            CandleInterval.DAY: Period.Day,
            CandleInterval.WEEK: Period.Week,
        }[interval]
        series: dict[str, CandleSeries] = {}
        errors: dict[str, str] = {}
        for symbol in symbols:
            if operation_control.cancellation_requested():
                break
            try:
                raw_by_timestamp: dict[datetime, Any] = {}
                cursor = end_at
                inclusive_boundary = False
                page_count = 0
                while len(raw_by_timestamp) < count:
                    if page_count >= self._max_pages:
                        raise _CandleFetchError("partial_data")
                    remaining = count - len(raw_by_timestamp)
                    page_size = min(
                        200,
                        remaining + (1 if inclusive_boundary else 0),
                    )

                    def fetch_candles(
                        current: str = symbol,
                        current_cursor: datetime = cursor,
                        size: int = page_size,
                    ) -> Sequence[Any]:
                        return self._quote.history_candlesticks_by_offset(
                            current,
                            period,
                            AdjustType.ForwardAdjust,
                            False,
                            size,
                            current_cursor,
                        )

                    raw, error = self._attempt(
                        fetch_candles,
                        operation_control,
                    )
                    if raw is None:
                        raise _CandleFetchError(error or "provider_error")
                    if not raw:
                        break
                    timestamps = tuple(self._timestamp(item.timestamp) for item in raw)
                    before = len(raw_by_timestamp)
                    for timestamp, item in zip(
                        timestamps,
                        raw,
                        strict=True,
                    ):
                        raw_by_timestamp.setdefault(timestamp, item)
                    added = len(raw_by_timestamp) - before
                    inclusive_boundary = inclusive_boundary or added < len(raw)
                    if added == 0:
                        break
                    earliest = min(timestamps)
                    cursor = earliest - timedelta(seconds=1)
                    page_count += 1
                    if len(raw) < page_size:
                        break
                selected_timestamps = sorted(raw_by_timestamp)[-count:]
                candles = tuple(
                    self._adjusted_market_candle(
                        timestamp,
                        raw_by_timestamp[timestamp],
                    )
                    for timestamp in selected_timestamps
                )
                series[symbol] = CandleSeries(symbol, interval, candles)
            except _CandleFetchError as exception:
                errors[symbol] = exception.code
            except (AttributeError, InvalidOperation, TypeError, ValueError):
                errors[symbol] = "malformed_data"
        return CandleDataset("longbridge", "Longbridge", interval, series, errors)

    def _series(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        operation_control: OperationControl,
    ) -> tuple[tuple[PricePoint, ...], str | None]:
        cursor = datetime.combine(end_date, time.max, UTC)
        points: dict[date, PricePoint] = {}
        for _page in range(self._max_pages):
            if operation_control.cancellation_requested():
                return (), "canceled"

            def fetch_page(
                current_symbol: str = symbol,
                current_cursor: datetime = cursor,
            ) -> Sequence[Any]:
                return self._quote.history_candlesticks_by_offset(
                    current_symbol,
                    Period.Day,
                    AdjustType.NoAdjust,
                    False,
                    _DAILY_PAGE_SIZE,
                    current_cursor,
                )

            raw_page, error = self._attempt(
                fetch_page,
                operation_control,
            )
            if error is not None or raw_page is None:
                return (), error or "provider_error"
            if not raw_page:
                break
            timestamps = []
            try:
                for raw in raw_page:
                    timestamp = self._timestamp(raw.timestamp)
                    timestamps.append(timestamp)
                    market_date = timestamp.astimezone(_NEW_YORK).date()
                    if not start_date <= market_date <= end_date:
                        continue
                    close = Decimal(str(raw.close))
                    if not close.is_finite() or close <= 0:
                        return (), "malformed_data"
                    existing = points.get(market_date)
                    if existing is not None:
                        if existing.close != close:
                            return (), "malformed_data"
                        continue
                    points[market_date] = PricePoint(market_date, close)
            except (AttributeError, InvalidOperation, TypeError, ValueError):
                return (), "malformed_data"
            earliest = min(timestamps)
            if earliest >= cursor:
                return (), "malformed_data"
            if earliest.astimezone(_NEW_YORK).date() <= start_date:
                break
            if len(raw_page) < _DAILY_PAGE_SIZE:
                break
            cursor = earliest - timedelta(seconds=1)
        else:
            return (), "partial_data"
        return tuple(points[key] for key in sorted(points)), None

    async def _series_async(
        self,
        quote: LongbridgeAsyncQuotePort,
        symbol: str,
        start_date: date,
        end_date: date,
        operation_control: OperationControl,
    ) -> tuple[tuple[PricePoint, ...], str | None]:
        cursor = datetime.combine(end_date, time.max, UTC)
        points: dict[date, PricePoint] = {}
        for _page in range(self._max_pages):
            if operation_control.cancellation_requested():
                return (), "canceled"

            async def fetch_page(
                current_cursor: datetime = cursor,
            ) -> Sequence[Any]:
                return await quote.history_candlesticks_by_offset(
                    symbol,
                    Period.Day,
                    AdjustType.NoAdjust,
                    False,
                    _DAILY_PAGE_SIZE,
                    current_cursor,
                )

            raw_page, error = await self._attempt_async(
                fetch_page,
                operation_control,
            )
            if error is not None or raw_page is None:
                return (), error or "provider_error"
            if not raw_page:
                break
            timestamps: list[datetime] = []
            try:
                for raw in raw_page:
                    timestamp = self._timestamp(raw.timestamp)
                    timestamps.append(timestamp)
                    market_date = timestamp.astimezone(_NEW_YORK).date()
                    if not start_date <= market_date <= end_date:
                        continue
                    close = Decimal(str(raw.close))
                    if not close.is_finite() or close <= 0:
                        return (), "malformed_data"
                    existing = points.get(market_date)
                    if existing is not None:
                        if existing.close != close:
                            return (), "malformed_data"
                        continue
                    points[market_date] = PricePoint(market_date, close)
            except (AttributeError, InvalidOperation, TypeError, ValueError):
                return (), "malformed_data"
            earliest = min(timestamps)
            if earliest >= cursor:
                return (), "malformed_data"
            if earliest.astimezone(_NEW_YORK).date() <= start_date:
                break
            if len(raw_page) < _DAILY_PAGE_SIZE:
                break
            cursor = earliest - timedelta(seconds=1)
        else:
            return (), "partial_data"
        return tuple(points[key] for key in sorted(points)), None

    def _attempt(
        self,
        action: Callable[[], _T],
        operation_control: OperationControl,
    ) -> tuple[_T | None, str | None]:
        for attempt in range(self._max_retries + 1):
            if operation_control.cancellation_requested():
                return None, "canceled"
            try:
                return action(), None
            except Exception as exception:  # noqa: BLE001 - SDK boundary
                code = self._error_code(exception)
                if code not in _RETRYABLE_ERRORS or attempt >= self._max_retries:
                    return None, code
                if not self._wait_before_retry(
                    float(2**attempt),
                    operation_control,
                ):
                    return None, "canceled"
        return None, "provider_error"

    async def _attempt_async(
        self,
        action: Callable[[], Any],
        operation_control: OperationControl,
    ) -> tuple[Sequence[Any] | None, str | None]:
        for attempt in range(self._max_retries + 1):
            if operation_control.cancellation_requested():
                return None, "canceled"
            try:
                result = await action()
                return result, None
            except Exception as exception:  # noqa: BLE001 - SDK boundary
                code = self._error_code(exception)
                if code not in _RETRYABLE_ERRORS or attempt >= self._max_retries:
                    return None, code
                if operation_control.cancellation_requested():
                    return None, "canceled"
                await self._async_sleep(float(2**attempt))
        return None, "provider_error"

    @staticmethod
    def _error_code(exception: Exception) -> str:
        if isinstance(exception, _MalformedQuantResponse):
            return "malformed_quant_response"
        if isinstance(exception, TimeoutError):
            return "timeout"
        if isinstance(exception, ConnectionError):
            return "network_error"
        message = (
            str(exception.message)
            if isinstance(exception, OpenApiException)
            else str(exception)
        ).casefold()
        if any(
            token in message
            for token in (
                "quota exhausted",
                "quota exceeded",
                "quota exhaustion",
            )
        ):
            return "quota_exhausted"
        if isinstance(exception, OpenApiException):
            provider_code = exception.code
            if (
                isinstance(provider_code, int)
                and not isinstance(provider_code, bool)
                and provider_code in {429, 301606, 429002}
            ):
                return "rate_limited"
        if (
            isinstance(exception, OpenApiException)
            # Runtime exposes ErrorKind.Http as a singleton; the stub says type.
            and exception.kind == ErrorKind.Http  # type: ignore[comparison-overlap]
        ):
            provider_code = exception.code
            if isinstance(provider_code, int) and not isinstance(
                provider_code,
                bool,
            ):
                if provider_code == 401:
                    return "authentication_failed"
                if provider_code == 403:
                    return "permission_denied"
                if provider_code == 429:
                    return "rate_limited"
                if 500 <= provider_code < 600:
                    return "service_unavailable"
        status = getattr(exception, "status_code", None)
        if status is None:
            response = getattr(exception, "response", None)
            status = getattr(response, "status_code", None)
            if status is None:
                status = getattr(response, "status", None)
        if status == 401:
            return "authentication_failed"
        if status == 403:
            return "permission_denied"
        if status == 429:
            return "rate_limited"
        if isinstance(status, int) and 500 <= status < 600:
            return "service_unavailable"
        if any(
            token in message
            for token in (
                "authentication",
                "unauthorized",
                "invalid token",
                "invalid credential",
                "invalid api key",
            )
        ):
            return "authentication_failed"
        if (
            "forbidden" in message
            or "permission" in message
            or "access denied" in message
        ):
            return "permission_denied"
        if (
            "rate limit" in message
            or "request is limited" in message
            or "slow down request frequency" in message
            or "429" in message
        ):
            return "rate_limited"
        if "timeout" in message or "timed out" in message:
            return "timeout"
        if any(
            token in message
            for token in (
                "network error",
                "network unreachable",
                "connection reset",
                "connection refused",
            )
        ):
            return "network_error"
        if "insufficient data" in message or "insufficient history" in message:
            return "insufficient_data"
        if any(
            token in message
            for token in ("data unavailable", "no data", "symbol unavailable")
        ):
            return "data_unavailable"
        if (
            "temporary" in message
            or "unavailable" in message
            or "internal error" in message
            or "server error" in message
            or any(
                token in message
                for token in ("500", "502", "503", "504", "5xx")
            )
        ):
            return "service_unavailable"
        if "unsupported" in message:
            return "unsupported"
        return "provider_error"

    @staticmethod
    def _timestamp(value: object) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(
                    tzinfo=_LOCAL_TIMEZONE
                ).astimezone(UTC)
            return value.astimezone(UTC)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, UTC)
        raise TypeError("timestamp is invalid")

    @staticmethod
    def _adjusted_market_candle(timestamp: datetime, raw: Any) -> MarketCandle:
        open_price = Decimal(str(raw.open))
        high = Decimal(str(raw.high))
        low = Decimal(str(raw.low))
        close = Decimal(str(raw.close))
        tolerance = max(
            _ADJUSTED_OHLC_ABSOLUTE_TOLERANCE,
            max(open_price, high, low, close)
            * _ADJUSTED_OHLC_RELATIVE_TOLERANCE,
        )
        expected_high = max(open_price, close, low)
        if high < expected_high and expected_high - high <= tolerance:
            high = expected_high
        expected_low = min(open_price, close, high)
        if low > expected_low and low - expected_low <= tolerance:
            low = expected_low
        return MarketCandle(
            timestamp,
            open_price,
            high,
            low,
            close,
            int(raw.volume),
        )

    @staticmethod
    def _asset_hint(board: str) -> AssetHint:
        normalized = board.casefold()
        if "uspink" in normalized:
            return AssetHint("OTC", "reliable")
        if "usoption" in normalized:
            return AssetHint("OPTION", "reliable")
        return AssetHint("UNKNOWN", "ambiguous")

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _optional_decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        parsed = Decimal(str(value))
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("invalid decimal")
        return parsed


class _CandleFetchError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _MalformedQuantResponse(Exception):
    pass


class _QuantCanceled(Exception):
    pass


def _counter_id(symbol: str) -> str:
    code, market = symbol.split(".", 1)
    kind = "ETF" if symbol in {"SPY.US", "QQQ.US"} else "ST"
    return f"{kind}/{market}/{code}"


def _quant_line_type(interval: CandleInterval) -> int:
    return {
        CandleInterval.MIN_30: 30,
        CandleInterval.MIN_60: 60,
        CandleInterval.DAY: 1000,
        CandleInterval.WEEK: 2000,
    }[interval]


def _decoded_json(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value or "null")
    return value


def _quant_timestamps(raw: object) -> tuple[datetime, ...]:
    events = _decoded_json(raw)
    if not isinstance(events, list):
        raise TypeError("missing quant events")
    indexed: dict[int, datetime] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        bar = event.get("barStart")
        if not isinstance(bar, dict):
            continue
        candle = bar.get("candlestick")
        if not isinstance(candle, dict):
            continue
        index = bar.get("barIndex")
        timestamp = candle.get("time")
        if not isinstance(index, int) or not isinstance(timestamp, (int, float)):
            continue
        indexed[index] = datetime.fromtimestamp(float(timestamp) / 1000.0, UTC)
    if not indexed:
        raise ValueError("missing quant timestamps")
    expected = tuple(range(max(indexed) + 1))
    if tuple(sorted(indexed)) != expected:
        raise ValueError("non-contiguous quant timestamps")
    return tuple(indexed[index] for index in expected)


def _quant_values(
    raw: object,
    names: tuple[str, ...],
    expected_length: int,
) -> dict[str, tuple[float | None, ...]]:
    chart = _decoded_json(raw)
    if not isinstance(chart, dict):
        raise TypeError("missing quant chart")
    nodes = chart.get("seriesGraphs")
    if not isinstance(nodes, list):
        raise TypeError("missing quant plots")
    found: dict[str, tuple[float | None, ...]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        plot = node.get("plot", node)
        if not isinstance(plot, dict):
            continue
        title = plot.get("title")
        raw_series = plot.get("series")
        if not isinstance(title, str) or not isinstance(raw_series, list):
            continue
        values: list[float | None] = []
        for item in raw_series:
            value: object = item
            if isinstance(item, dict):
                value = item.get("Close", item.get("close", item.get("value")))
            if value is None:
                values.append(None)
            elif isinstance(value, (int, float)):
                values.append(float(value))
            else:
                raise ValueError("invalid quant value")
        found[title] = tuple(values)
    if any(name not in found for name in names):
        raise ValueError("missing expected quant plot")
    selected = {name: found[name] for name in names}
    aligned: dict[str, tuple[float | None, ...]] = {}
    for name, series_values in selected.items():
        if len(series_values) > expected_length:
            raise ValueError("unaligned quant plots")
        aligned[name] = (
            (None,) * (expected_length - len(series_values))
            + series_values
        )
    return aligned
