from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from threading import Event, Lock, Thread
from types import SimpleNamespace

import pytest
from longbridge.openapi import ErrorKind, OpenApiException

import stock_toolbox.infrastructure.providers.longbridge as longbridge_module
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.market_data.quant import QuantProgress, QuantSeriesRequest
from stock_toolbox.core.operations.failure_policy import FailureCode
from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.core.operations.run_feedback import FeedbackKind
from stock_toolbox.infrastructure.providers.longbridge import LongbridgeProvider


def test_longbridge_does_not_advertise_retired_250d_quant_support() -> None:
    assert "turning-risk-250d-v1" not in LongbridgeProvider.quant_script_versions


def test_longbridge_does_not_advertise_incompatible_extreme_quant_formula() -> None:
    assert "extreme-deviation-original-v4" not in LongbridgeProvider.quant_script_versions


class Quote:
    pass


class QuantHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append((method, path, body))
        chart = {
            "seriesGraphs": [
                {"plot": {"title": "close", "series": [100.0, 101.5]}},
                {"plot": {"title": "volume_ratio", "series": [0.8, 1.2]}},
            ]
        }
        events = [
            {
                "barStart": {
                    "barIndex": 0,
                    "candlestick": {"time": 1_735_794_000_000},
                }
            },
            "barEnd",
            {
                "barStart": {
                    "barIndex": 1,
                    "candlestick": {"time": 1_735_880_400_000},
                }
            },
            "barEnd",
            "historyEnd",
        ]
        return {
            "chart_json": json.dumps(chart),
            "events_json": json.dumps(events),
        }


def control():
    registry = OperationRegistry(clock=lambda: datetime(2026, 7, 25, tzinfo=UTC))
    registry.reserve("op-1", "key", "provider")
    context = registry.begin_reserved("op-1")
    assert context is not None
    return context.operation_control


def test_operation_control_wait_can_be_interrupted_by_cancellation() -> None:
    registry = OperationRegistry(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC)
    )
    registry.reserve("op-wait", "key-wait", "provider")
    context = registry.begin_reserved("op-wait")
    assert context is not None
    wait_for_cancellation = getattr(
        context.operation_control,
        "wait_for_cancellation",
        None,
    )

    assert callable(wait_for_cancellation)

    result: list[bool] = []
    finished = Event()

    def wait_for_cancel() -> None:
        result.append(wait_for_cancellation(60))
        finished.set()

    thread = Thread(target=wait_for_cancel)
    thread.start()
    registry.cancel("op-wait")

    assert finished.wait(timeout=0.2)
    thread.join(timeout=0.2)
    assert result == [True]


def test_quant_progress_feedback_defaults_to_none() -> None:
    progress = QuantProgress(1, 2, "AAPL.US", 1, 0)

    assert progress.feedback is None


def test_quant_endpoint_parses_named_series_for_supported_period() -> None:
    http = QuantHttp()
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
    )
    request = QuantSeriesRequest(
        "turning-v2",
        CandleInterval.MIN_60,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("turning"); plot(close, "close");',
        ("close", "volume_ratio"),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
    )

    assert not result.errors
    assert result.series_by_symbol["AAPL.US"].values["close"] == (100.0, 101.5)
    assert result.series_by_symbol["AAPL.US"].timestamps[0].tzinfo is UTC
    assert http.calls[0][0:2] == ("POST", "/v2/quant/run_script")
    assert http.calls[0][2]["line_type"] == 60
    assert http.calls[0][2]["counter_id"] == "ST/US/AAPL"
    assert http.calls[0][2]["exclude_chart"] is False


def test_quant_request_starts_leave_half_the_official_rate_budget_free() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.now = 0.0
            self.waits: list[float] = []

        def monotonic(self) -> float:
            return self.now

        def wait(self, seconds: float, _operation_control: object) -> bool:
            self.waits.append(seconds)
            self.now += seconds
            return False

    class TimedHttp(QuantHttp):
        def __init__(self, fake_clock: FakeClock) -> None:
            super().__init__()
            self.fake_clock = fake_clock
            self.started_at: list[float] = []

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.started_at.append(self.fake_clock.now)
            return super().request(method, path, body=body)

    fake_clock = FakeClock()
    http = TimedHttp(fake_clock)
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        quant_request_interval_seconds=0.2,
        monotonic_clock=fake_clock.monotonic,
        quant_waiter=fake_clock.wait,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US", "MSFT.US", "NVDA.US", "AMD.US"),
        request,
        operation_control=control(),
    )

    assert not result.errors
    starts = sorted(http.started_at)
    assert starts == pytest.approx([0.0, 0.2, 0.4, 0.6])
    assert all(
        right - left >= 0.2
        for left, right in pairwise(starts)
    )


@pytest.mark.parametrize(
    "interval",
    (CandleInterval.MIN_120, CandleInterval.MIN_240),
)
def test_quant_endpoint_rejects_periods_the_server_does_not_support(
    interval: CandleInterval,
) -> None:
    http = QuantHttp()
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
    )
    request = QuantSeriesRequest(
        "turning-v3",
        interval,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("turning"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
    )

    assert result.series_by_symbol == {}
    assert result.errors == {"AAPL.US": "quant_interval_unsupported"}
    assert http.calls == []


def test_quant_endpoint_retains_tail_but_preserves_source_count() -> None:
    http = QuantHttp()
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
    )
    request = QuantSeriesRequest(
        "extreme-v3",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("extreme"); plot(close, "close");',
        ("close", "volume_ratio"),
        retain_last=1,
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
    ).series_by_symbol["AAPL.US"]

    assert result.source_count == 2
    assert result.retained_count == 1
    assert result.values["close"] == (101.5,)


def test_quant_endpoint_uses_exclusive_next_day_boundary_but_clips_results() -> None:
    http = QuantHttp()
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
    )
    end_at = datetime(2025, 1, 2, 23, 59, tzinfo=UTC)
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        end_at,
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
    )

    assert http.calls[0][2]["end_time"] == int(
        (end_at + timedelta(days=1)).timestamp()
    )
    assert len(result.series_by_symbol["AAPL.US"].timestamps) == 1
    assert result.series_by_symbol["AAPL.US"].values["close"] == (100.0,)


def test_quant_endpoint_returns_per_symbol_failures_without_raw_kline_fallback() -> None:
    class BrokenHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            del method, path, body
            raise RuntimeError("provider unavailable")

    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=BrokenHttp,
        max_retries=0,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
    )

    assert result.series_by_symbol == {}
    assert result.errors == {"AAPL.US": "service_unavailable"}


def test_quant_endpoint_caps_parallel_requests_at_four() -> None:
    class BlockingHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.maximum = 0
            self.lock = Lock()
            self.four_started = Event()

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            with self.lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                if self.active == 4:
                    self.four_started.set()
            self.four_started.wait(timeout=1)
            try:
                return super().request(method, path, body=body)
            finally:
                with self.lock:
                    self.active -= 1

    http = BlockingHttp()
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close", "volume_ratio"),
    )

    result = provider.get_quant_series(
        tuple(f"S{index}.US" for index in range(8)),
        request,
        operation_control=control(),
    )

    assert len(result.series_by_symbol) == 8
    assert http.maximum == 4


def test_quant_submission_is_bounded_and_cancellation_prevents_later_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TrackingExecutor(ThreadPoolExecutor):
        pending = 0
        maximum_pending = 0
        guard = Lock()

        def submit(
            self,
            fn: Callable[..., object],
            /,
            *args: object,
            **kwargs: object,
        ) -> Future[object]:
            with self.guard:
                type(self).pending += 1
                type(self).maximum_pending = max(
                    type(self).maximum_pending,
                    type(self).pending,
                )
            future = super().submit(fn, *args, **kwargs)

            def finished(_future: Future[object]) -> None:
                with self.guard:
                    type(self).pending -= 1

            future.add_done_callback(finished)
            return future

    monkeypatch.setattr(
        longbridge_module,
        "ThreadPoolExecutor",
        TrackingExecutor,
    )

    class BlockingAfterProbeHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.started = 0
            self.lock = Lock()
            self.four_blocked = Event()
            self.release = Event()

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            with self.lock:
                self.started += 1
                call_number = self.started
                if self.started == 5:
                    self.four_blocked.set()
            if call_number > 1:
                self.release.wait(timeout=1)
            return super().request(method, path, body=body)

    registry = OperationRegistry(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC)
    )
    registry.reserve("op-cancel", "key-cancel", "provider")
    context = registry.begin_reserved("op-cancel")
    assert context is not None
    http = BlockingAfterProbeHttp()
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close", "volume_ratio"),
    )
    results = []

    def run() -> None:
        results.append(
            provider.get_quant_series(
                tuple(f"S{index}.US" for index in range(30)),
                request,
                operation_control=context.operation_control,
            )
        )

    thread = Thread(target=run)
    thread.start()
    assert http.four_blocked.wait(timeout=1)
    registry.cancel("op-cancel")
    http.release.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert TrackingExecutor.maximum_pending <= 4
    assert http.started == 5
    assert results


def test_quant_endpoint_retries_one_transient_malformed_chart() -> None:
    class OnceMalformedHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.attempts += 1
            if self.attempts == 1:
                return {
                    "chart_json": "{}",
                    "events_json": "[]",
                }
            return super().request(method, path, body=body)

    http = OnceMalformedHttp()
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=1,
        sleeper=lambda _seconds: None,
    )
    request = QuantSeriesRequest(
        "turning-v2",
        CandleInterval.MIN_60,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("turning"); plot(close, "close");',
        ("close", "volume_ratio"),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
    )

    assert "AAPL.US" in result.series_by_symbol
    assert http.attempts == 2


def test_compatible_transport_honors_retry_after_and_recovers_one_lane() -> None:
    class TransportRateLimited(RuntimeError):
        def __init__(self) -> None:
            super().__init__("429 rate limit")
            self.response = SimpleNamespace(headers={"Retry-After": "3"})

    class OnceRateLimitedHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False
            self.started = 0
            self.active = 0
            self.recovery_maximum = 0
            self.lock = Lock()
            self.ramp_four_started = Event()
            self.throttle_observed = Event()
            self.allow_rate_limit = Event()
            self.rate_limit_raised = Event()

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            with self.lock:
                self.started += 1
                call_number = self.started
                self.active += 1
                if self.started == 5:
                    self.ramp_four_started.set()
                if call_number > 5:
                    self.recovery_maximum = max(
                        self.recovery_maximum,
                        self.active,
                    )
            if 2 <= call_number <= 5:
                self.ramp_four_started.wait(timeout=1)
            try:
                if body["counter_id"] == "ST/US/MSFT" and not self.failed:
                    self.allow_rate_limit.wait(timeout=1)
                    self.failed = True
                    self.rate_limit_raised.set()
                    raise TransportRateLimited
                if (
                    2 <= call_number <= 5
                    and body["counter_id"] != "ST/US/NVDA"
                ):
                    self.throttle_observed.wait(timeout=1)
                return super().request(method, path, body=body)
            finally:
                with self.lock:
                    self.active -= 1

    http = OnceRateLimitedHttp()
    waits: list[float] = []
    updates: list[QuantProgress] = []

    def record_update(item: QuantProgress) -> None:
        updates.append(item)
        if item.current_symbol == "NVDA.US" and item.feedback is None:
            http.allow_rate_limit.set()
            assert http.rate_limit_raised.wait(timeout=1)
        if (
            item.feedback is not None
            and item.feedback.kind is FeedbackKind.THROTTLED
        ):
            http.throttle_observed.set()

    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        sleeper=waits.append,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close", "volume_ratio"),
    )

    result = provider.get_quant_series(
        tuple(
            ["AAPL.US", "MSFT.US", "NVDA.US", "META.US"]
            + [f"S{index}.US" for index in range(4)]
        ),
        request,
        operation_control=control(),
        progress=record_update,
    )

    feedback = [
        item.feedback
        for item in updates
        if item.feedback is not None
    ]
    assert not result.errors
    assert waits == [3.0]
    assert [item.kind for item in feedback] == [
        FeedbackKind.THROTTLED,
        FeedbackKind.RETRYING,
        FeedbackKind.RECOVERED,
    ]
    assert feedback[0].failure_code is FailureCode.RATE_LIMITED
    assert feedback[0].wait_seconds == 3.0
    assert feedback[0].active_concurrency == 1
    assert feedback[-1].active_concurrency == 1
    assert http.recovery_maximum == 1


@pytest.mark.parametrize(
    "retry_after",
    ["Infinity", "-4", "not-a-delay"],
)
def test_invalid_retry_after_uses_finite_controlled_fallback(
    retry_after: str,
) -> None:
    class InvalidRetryAfter(RuntimeError):
        def __init__(self) -> None:
            super().__init__("429 rate limit")
            self.response = SimpleNamespace(
                headers={"Retry-After": retry_after}
            )

    class OnceRateLimitedHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            if not self.failed:
                self.failed = True
                self.calls.append((method, path, body))
                raise InvalidRetryAfter
            return super().request(method, path, body=body)

    http = OnceRateLimitedHttp()
    waits: list[float] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        sleeper=waits.append,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close", "volume_ratio"),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
    )

    assert not result.errors
    assert waits == [1.0]


def test_long_retry_after_wait_is_interrupted_without_retry_request() -> None:
    class LongRateLimited(RuntimeError):
        def __init__(self) -> None:
            super().__init__("429 rate limit")
            self.response = SimpleNamespace(headers={"Retry-After": "60"})

    class LongRateLimitedHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.calls.append((method, path, body))
            raise LongRateLimited

    registry = OperationRegistry(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC)
    )
    registry.reserve("op-long-wait", "key-long-wait", "provider")
    context = registry.begin_reserved("op-long-wait")
    assert context is not None
    wait_entered = Event()
    original_wait = context.operation_control.wait_for_cancellation

    def observed_wait(timeout: float) -> bool:
        wait_entered.set()
        return original_wait(timeout)

    context.operation_control.wait_for_cancellation = observed_wait  # type: ignore[method-assign]

    def fail_if_blocking_sleep_used(_seconds: float) -> None:
        raise AssertionError("long retry wait used blocking sleeper")

    http = LongRateLimitedHttp()
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        sleeper=fail_if_blocking_sleep_used,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )
    results = []

    def run() -> None:
        results.append(
            provider.get_quant_series(
                ("AAPL.US",),
                request,
                operation_control=context.operation_control,
            )
        )

    thread = Thread(target=run)
    thread.start()
    entered = wait_entered.wait(timeout=0.2)
    registry.cancel("op-long-wait")
    thread.join(timeout=0.2)

    assert entered
    assert not thread.is_alive()
    assert len(http.calls) == 1
    assert results[0].errors == {"AAPL.US": "canceled"}


def test_scattered_rate_limits_recover_without_aborting_the_batch() -> None:
    class TwiceRateLimitedHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.attempts_by_counter: dict[str, int] = {}

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            counter = str(body["counter_id"])
            self.attempts_by_counter[counter] = (
                self.attempts_by_counter.get(counter, 0) + 1
            )
            if (
                counter in {"ST/US/S0", "ST/US/S1"}
                and self.attempts_by_counter[counter] == 1
            ):
                raise RuntimeError("429 rate limit")
            return super().request(method, path, body=body)

    http = TwiceRateLimitedHttp()
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        sleeper=lambda _seconds: None,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close", "volume_ratio"),
    )
    symbols = tuple(f"S{index}.US" for index in range(30))

    result = provider.get_quant_series(
        symbols,
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert not result.errors
    assert len(result.series_by_symbol) == len(symbols)
    assert http.attempts_by_counter["ST/US/S0"] == 2
    assert http.attempts_by_counter["ST/US/S1"] == 2
    assert not any(
        item.feedback is not None
        and item.feedback.kind is FeedbackKind.CIRCUIT_OPEN
        for item in updates
    )


def test_shared_circuit_breaker_stops_persistent_infrastructure_failures() -> None:
    class UnavailableHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.calls.append((method, path, body))
            raise RuntimeError("503 service unavailable")

    http = UnavailableHttp()
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=0,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )
    symbols = tuple(f"S{index}.US" for index in range(30))

    result = provider.get_quant_series(
        symbols,
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert len(http.calls) < len(symbols)
    assert "circuit_open" in result.errors.values()
    circuit = [
        item.feedback
        for item in updates
        if item.feedback is not None
        and item.feedback.kind is FeedbackKind.CIRCUIT_OPEN
    ]
    unexecuted = {
        symbol
        for symbol, error in result.errors.items()
        if error == "circuit_open"
    }
    assert len(circuit) == len(unexecuted) + 1
    assert len({item.symbol for item in circuit}) == len(circuit)
    assert circuit[0].failure_code is FailureCode.SERVICE_UNAVAILABLE


def test_breaker_drains_running_work_and_only_marks_unexecuted_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ImmediateBreaker:
        def record(self, code: FailureCode) -> bool:
            return code is FailureCode.SERVICE_UNAVAILABLE

    class ControlledExecutor:
        def __init__(
            self,
            *,
            max_workers: int,
            thread_name_prefix: str,
        ) -> None:
            del max_workers, thread_name_prefix
            self.submissions = 0
            self.release_running = Event()
            self.threads: list[Thread] = []

        @staticmethod
        def resolve(
            future: Future[object],
            fn: Callable[..., object],
            args: tuple[object, ...],
        ) -> None:
            try:
                future.set_result(fn(*args))
            except Exception as error:  # noqa: BLE001 - controlled fake boundary
                future.set_exception(error)

        def submit(
            self,
            fn: Callable[..., object],
            /,
            *args: object,
            **kwargs: object,
        ) -> Future[object]:
            assert not kwargs
            self.submissions += 1
            future: Future[object] = Future()
            if self.submissions in {1, 2}:
                assert future.set_running_or_notify_cancel()
                self.resolve(future, fn, args)
            elif self.submissions in {3, 4}:
                assert future.set_running_or_notify_cancel()

                def run_later() -> None:
                    self.release_running.wait(timeout=1)
                    self.resolve(future, fn, args)

                thread = Thread(target=run_later)
                self.threads.append(thread)
                thread.start()
            return future

        def shutdown(
            self,
            wait: bool = True,
            *,
            cancel_futures: bool = False,
        ) -> None:
            del cancel_futures
            self.release_running.set()
            if wait:
                for thread in self.threads:
                    thread.join(timeout=1)

    monkeypatch.setattr(
        longbridge_module,
        "CircuitBreaker",
        ImmediateBreaker,
    )
    monkeypatch.setattr(
        longbridge_module,
        "ThreadPoolExecutor",
        ControlledExecutor,
    )

    class BreakerHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            if body["counter_id"] == "ST/US/S1":
                self.calls.append((method, path, body))
                raise RuntimeError("503 service unavailable")
            if body["counter_id"] == "ST/US/S3":
                self.calls.append((method, path, body))
                raise RuntimeError("insufficient history")
            return super().request(method, path, body=body)

    http = BreakerHttp()
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=0,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close", "volume_ratio"),
    )
    symbols = tuple(f"S{index}.US" for index in range(8))

    result = provider.get_quant_series(
        symbols,
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert set(result.series_by_symbol) == {"S0.US", "S2.US"}
    assert result.errors["S1.US"] == "service_unavailable"
    assert result.errors["S3.US"] == "insufficient_data"
    assert all(
        result.errors[symbol] == "circuit_open"
        for symbol in symbols[4:]
    )
    assert len(http.calls) == 4
    assert Counter(item.current_symbol for item in updates) == Counter(symbols)
    assert updates[-1].completed == len(symbols)
    assert all(
        item.feedback is not None
        and item.feedback.kind is FeedbackKind.CIRCUIT_OPEN
        for item in updates
        if item.current_symbol in set(symbols[4:])
    )
    failed_running = next(
        item
        for item in updates
        if item.current_symbol == "S3.US"
    )
    assert failed_running.feedback is not None
    assert failed_running.feedback.kind is FeedbackKind.ITEM_SKIPPED
    assert (
        failed_running.feedback.failure_code
        is FailureCode.INSUFFICIENT_DATA
    )


def test_fatal_stop_drains_running_work_and_only_marks_unexecuted_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledExecutor:
        def __init__(
            self,
            *,
            max_workers: int,
            thread_name_prefix: str,
        ) -> None:
            del max_workers, thread_name_prefix
            self.submissions = 0
            self.release_running = Event()
            self.threads: list[Thread] = []

        @staticmethod
        def resolve(
            future: Future[object],
            fn: Callable[..., object],
            args: tuple[object, ...],
        ) -> None:
            try:
                future.set_result(fn(*args))
            except Exception as error:  # noqa: BLE001 - controlled fake boundary
                future.set_exception(error)

        def submit(
            self,
            fn: Callable[..., object],
            /,
            *args: object,
            **kwargs: object,
        ) -> Future[object]:
            assert not kwargs
            self.submissions += 1
            future: Future[object] = Future()
            if self.submissions in {1, 2}:
                assert future.set_running_or_notify_cancel()
                self.resolve(future, fn, args)
            elif self.submissions in {3, 4}:
                assert future.set_running_or_notify_cancel()

                def run_later() -> None:
                    self.release_running.wait(timeout=1)
                    self.resolve(future, fn, args)

                thread = Thread(target=run_later)
                self.threads.append(thread)
                thread.start()
            return future

        def shutdown(
            self,
            wait: bool = True,
            *,
            cancel_futures: bool = False,
        ) -> None:
            del cancel_futures
            self.release_running.set()
            if wait:
                for thread in self.threads:
                    thread.join(timeout=1)

    monkeypatch.setattr(
        longbridge_module,
        "ThreadPoolExecutor",
        ControlledExecutor,
    )

    class FatalHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            if body["counter_id"] == "ST/US/S1":
                self.calls.append((method, path, body))
                raise OpenApiException(
                    ErrorKind.Http,
                    401,
                    "production-trace",
                    "request rejected",
                )
            if body["counter_id"] == "ST/US/S3":
                self.calls.append((method, path, body))
                raise RuntimeError("insufficient history")
            return super().request(method, path, body=body)

    http = FatalHttp()
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=0,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close", "volume_ratio"),
    )
    symbols = tuple(f"S{index}.US" for index in range(8))

    result = provider.get_quant_series(
        symbols,
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert set(result.series_by_symbol) == {"S0.US", "S2.US"}
    assert result.errors["S1.US"] == "authentication_failed"
    assert result.errors["S3.US"] == "insufficient_data"
    assert all(
        result.errors[symbol] == "authentication_failed"
        for symbol in symbols[4:]
    )
    assert len(http.calls) == 4
    assert Counter(item.current_symbol for item in updates) == Counter(symbols)
    failed_running = next(
        item
        for item in updates
        if item.current_symbol == "S3.US"
    )
    assert failed_running.feedback is not None
    assert failed_running.feedback.kind is FeedbackKind.ITEM_SKIPPED
    assert all(
        item.feedback is not None
        and item.feedback.kind is FeedbackKind.FATAL
        for item in updates
        if item.current_symbol in {"S1.US", *symbols[4:]}
    )


def test_authentication_failure_stops_batch_after_one_provider_call() -> None:
    class InvalidApiKeyHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.calls.append((method, path, body))
            raise RuntimeError("invalid API key")

    http = InvalidApiKeyHttp()
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=2,
        sleeper=lambda _seconds: None,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US", "MSFT.US", "NVDA.US"),
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert len(http.calls) == 1
    assert result.errors == {
        "AAPL.US": "authentication_failed",
        "MSFT.US": "authentication_failed",
        "NVDA.US": "authentication_failed",
    }
    fatal = [
        item.feedback
        for item in updates
        if item.feedback is not None
        and item.feedback.kind is FeedbackKind.FATAL
    ]
    assert {item.symbol for item in fatal} == {
        "AAPL.US",
        "MSFT.US",
        "NVDA.US",
    }
    assert all(
        item.failure_code is FailureCode.AUTHENTICATION_FAILED
        for item in fatal
    )


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (401, FailureCode.AUTHENTICATION_FAILED),
        (403, FailureCode.PERMISSION_DENIED),
    ],
)
def test_openapi_http_auth_failure_is_fatal_and_stops_batch(
    code: int,
    expected: FailureCode,
) -> None:
    class FailedHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.calls.append((method, path, body))
            raise OpenApiException(
                ErrorKind.Http,
                code,
                "production-trace",
                "request rejected",
            )

    http = FailedHttp()
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=2,
        sleeper=lambda _seconds: None,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US", "MSFT.US"),
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert len(http.calls) == 1
    assert result.errors["AAPL.US"] == expected.value
    assert updates[0].feedback is not None
    assert updates[0].feedback.kind is FeedbackKind.FATAL
    assert updates[0].feedback.failure_code is expected


@pytest.mark.parametrize(
    ("code", "message", "expected"),
    [
        (401, "insufficient data", FailureCode.AUTHENTICATION_FAILED),
        (429, "insufficient history", FailureCode.RATE_LIMITED),
        (503, "market data unavailable", FailureCode.SERVICE_UNAVAILABLE),
    ],
)
def test_openapi_http_code_outranks_conflicting_data_text(
    code: int,
    message: str,
    expected: FailureCode,
) -> None:
    class ConflictingHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            if not self.failed:
                self.failed = True
                self.calls.append((method, path, body))
                raise OpenApiException(
                    ErrorKind.Http,
                    code,
                    "production-trace",
                    message,
                )
            return super().request(method, path, body=body)

    http = ConflictingHttp()
    waits: list[float] = []
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=1,
        sleeper=waits.append,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )
    symbols = (
        ("AAPL.US", "MSFT.US")
        if expected is FailureCode.AUTHENTICATION_FAILED
        else ("AAPL.US",)
    )

    result = provider.get_quant_series(
        symbols,
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert updates[0].feedback is not None
    assert updates[0].feedback.failure_code is expected
    if expected is FailureCode.AUTHENTICATION_FAILED:
        assert len(http.calls) == 1
        assert updates[0].feedback.kind is FeedbackKind.FATAL
        assert result.errors["AAPL.US"] == expected.value
    else:
        assert len(http.calls) == 2
        assert not result.errors
        assert waits == [1.0]


def test_explicit_quota_exhaustion_takes_precedence_over_http_429() -> None:
    class ExhaustedQuotaHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.calls.append((method, path, body))
            raise OpenApiException(
                ErrorKind.Http,
                429,
                "production-trace",
                "quota exhausted",
            )

    http = ExhaustedQuotaHttp()
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=2,
        sleeper=lambda _seconds: None,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US", "MSFT.US"),
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert len(http.calls) == 1
    assert result.errors["AAPL.US"] == "quota_exhausted"
    assert updates[0].feedback is not None
    assert updates[0].feedback.kind is FeedbackKind.FATAL
    assert updates[0].feedback.failure_code is FailureCode.QUOTA_EXHAUSTED


def test_openapi_rate_limit_uses_controlled_fallback_without_headers() -> None:
    class ProductionRateLimitedHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.attempts += 1
            if self.attempts == 1:
                self.calls.append((method, path, body))
                raise RuntimeError("network error")
            if self.attempts == 2:
                self.calls.append((method, path, body))
                raise OpenApiException(
                    ErrorKind.Http,
                    429,
                    "production-trace",
                    "too many requests",
                )
            return super().request(method, path, body=body)

    http = ProductionRateLimitedHttp()
    waits: list[float] = []
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=2,
        sleeper=waits.append,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
        progress=updates.append,
    )

    feedback = [
        item.feedback
        for item in updates
        if item.feedback is not None
    ]
    assert not result.errors
    assert len(http.calls) == 3
    assert waits == [1.0, 2.0]
    assert [item.kind for item in feedback] == [
        FeedbackKind.RETRYING,
        FeedbackKind.THROTTLED,
        FeedbackKind.RETRYING,
        FeedbackKind.RECOVERED,
    ]
    assert feedback[1].failure_code is FailureCode.RATE_LIMITED
    assert feedback[1].wait_seconds == 2.0


def test_statusless_openapi_network_error_retries_twice_then_recovers() -> None:
    class StatuslessNetworkHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.attempts += 1
            if self.attempts <= 2:
                self.calls.append((method, path, body))
                raise OpenApiException(
                    ErrorKind.Http,
                    None,
                    "production-trace",
                    "network error",
                )
            return super().request(method, path, body=body)

    http = StatuslessNetworkHttp()
    waits: list[float] = []
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=20,
        sleeper=waits.append,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert not result.errors
    assert len(http.calls) == 3
    assert waits == [1.0, 2.0]
    feedback = [
        item.feedback
        for item in updates
        if item.feedback is not None
    ]
    assert [item.kind for item in feedback] == [
        FeedbackKind.RETRYING,
        FeedbackKind.RETRYING,
        FeedbackKind.RECOVERED,
    ]
    assert all(
        item.failure_code is FailureCode.NETWORK_ERROR
        for item in feedback
    )


def test_statusless_openapi_timeout_stops_after_two_retries() -> None:
    class StatuslessTimeoutHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.calls.append((method, path, body))
            raise OpenApiException(
                ErrorKind.Http,
                None,
                "production-trace",
                "request timed out",
            )

    http = StatuslessTimeoutHttp()
    waits: list[float] = []
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=20,
        sleeper=waits.append,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert result.errors == {"AAPL.US": "timeout"}
    assert len(http.calls) == 3
    assert waits == [1.0, 2.0]
    feedback = [
        item.feedback
        for item in updates
        if item.feedback is not None
    ]
    assert [item.kind for item in feedback] == [
        FeedbackKind.RETRYING,
        FeedbackKind.RETRYING,
        FeedbackKind.ITEM_SKIPPED,
    ]
    assert all(
        item.failure_code is FailureCode.TIMEOUT
        for item in feedback
    )


def test_non_integer_openapi_code_uses_transport_message_without_crashing() -> None:
    class NonIntegerCodeHttp(QuantHttp):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.attempts += 1
            if self.attempts == 1:
                self.calls.append((method, path, body))
                raise OpenApiException(
                    ErrorKind.Http,
                    "transport",
                    "production-trace",
                    "network error",
                )
            return super().request(method, path, body=body)

    http = NonIntegerCodeHttp()
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        sleeper=lambda _seconds: None,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert not result.errors
    assert len(http.calls) == 2
    assert updates[0].feedback is not None
    assert updates[0].feedback.kind is FeedbackKind.RETRYING
    assert (
        updates[0].feedback.failure_code
        is FailureCode.NETWORK_ERROR
    )


def test_generic_network_failure_is_limited_to_two_automatic_retries() -> None:
    class NetworkFailureHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.calls.append((method, path, body))
            raise RuntimeError("network error")

    http = NetworkFailureHttp()
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=20,
        sleeper=lambda _seconds: None,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert len(http.calls) == 3
    assert result.errors == {"AAPL.US": "network_error"}
    assert [
        item.feedback.kind
        for item in updates
        if item.feedback is not None
    ] == [
        FeedbackKind.RETRYING,
        FeedbackKind.RETRYING,
        FeedbackKind.ITEM_SKIPPED,
    ]


def test_insufficient_data_skips_item_without_retrying() -> None:
    class InsufficientHistoryHttp(QuantHttp):
        def request(
            self,
            method: str,
            path: str,
            *,
            body: dict[str, object],
        ) -> dict[str, object]:
            self.calls.append((method, path, body))
            raise RuntimeError("insufficient history")

    http = InsufficientHistoryHttp()
    waits: list[float] = []
    updates: list[QuantProgress] = []
    provider = LongbridgeProvider(
        Quote(),
        quant_http_factory=lambda: http,
        max_retries=20,
        sleeper=waits.append,
    )
    request = QuantSeriesRequest(
        "rs-v2",
        CandleInterval.DAY,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 2, 1, tzinfo=UTC),
        'indicator("rs"); plot(close, "close");',
        ("close",),
    )

    result = provider.get_quant_series(
        ("AAPL.US",),
        request,
        operation_control=control(),
        progress=updates.append,
    )

    assert len(http.calls) == 1
    assert waits == []
    assert result.errors == {"AAPL.US": "insufficient_data"}
    assert updates[-1].feedback is not None
    assert updates[-1].feedback.kind is FeedbackKind.ITEM_SKIPPED
    assert (
        updates[-1].feedback.failure_code
        is FailureCode.INSUFFICIENT_DATA
    )
