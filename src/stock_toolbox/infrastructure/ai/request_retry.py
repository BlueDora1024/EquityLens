"""One bounded retry policy shared by OpenAI-compatible requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from time import sleep
from typing import Protocol

import httpx

from stock_toolbox.core.operations.failure_policy import FailureCode

_MAX_RETRIES = 2
_MAX_RETRY_AFTER_SECONDS = 60.0


class AIHTTPResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


class AIRequestFailure(RuntimeError):
    """Internal stable request failure used at the adapter boundary."""

    def __init__(self, code: FailureCode | str) -> None:
        self.code = code.value if isinstance(code, FailureCode) else code
        super().__init__(self.code)


def request_with_retry[ResponseT: AIHTTPResponse, ResultT](
    send: Callable[[], ResponseT],
    parse: Callable[[ResponseT], ResultT],
    *,
    max_retries: int,
    sleeper: Callable[[float], None] = sleep,
    cancellation_requested: Callable[[], bool] = lambda: False,
    cancellation_wait: Callable[[float], bool] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ResultT:
    """Send once plus at most two configured retries.

    ``cancellation_wait`` returns true when cancellation interrupted the wait.
    It lets operation-backed requests remain responsive without creating a
    second retry implementation.
    """
    retry_limit = min(max(0, max_retries), _MAX_RETRIES)
    for attempt in range(retry_limit + 1):
        if cancellation_requested():
            raise AIRequestFailure("canceled")
        response: ResponseT | None = None
        code: str | None
        try:
            response = send()
        except (httpx.TimeoutException, TimeoutError) as error:
            code = FailureCode.TIMEOUT.value
            cause: Exception = error
        except Exception as error:  # noqa: BLE001 - sanitize transport boundary
            code = FailureCode.NETWORK_ERROR.value
            cause = error
        else:
            code = response_failure_code(response)
            cause = RuntimeError(code or FailureCode.INTERNAL.value)
            if code is None:
                try:
                    return parse(response)
                except AIRequestFailure as error:
                    code = error.code
                    cause = error

        if attempt >= _retry_limit(code, retry_limit):
            raise AIRequestFailure(code) from cause

        fallback = float(2**attempt)
        wait_seconds = (
            retry_after_seconds(response, fallback=fallback, clock=clock)
            if response is not None
            else fallback
        )
        canceled_during_wait = (
            cancellation_wait(wait_seconds)
            if cancellation_wait is not None
            else _sleep_and_continue(sleeper, wait_seconds)
        )
        if canceled_during_wait or cancellation_requested():
            raise AIRequestFailure("canceled")
    raise AIRequestFailure(FailureCode.INTERNAL)


def _retry_limit(code: str, configured_limit: int) -> int:
    if code in {
        FailureCode.TIMEOUT.value,
        FailureCode.NETWORK_ERROR.value,
    }:
        return configured_limit
    if code in {
        FailureCode.SERVICE_UNAVAILABLE.value,
        FailureCode.RATE_LIMITED.value,
        FailureCode.MALFORMED_RESPONSE.value,
        "invalid_response",
    }:
        return min(configured_limit, 1)
    return 0


def response_failure_code(response: AIHTTPResponse) -> str | None:
    status = response.status_code
    if status == 200:
        return None
    if _is_quota_failure(response) or status == 402:
        return FailureCode.QUOTA_EXHAUSTED.value
    if status == 401:
        return FailureCode.AUTHENTICATION_FAILED.value
    if status == 403:
        return FailureCode.PERMISSION_DENIED.value
    if status == 408:
        return FailureCode.TIMEOUT.value
    if status == 429:
        return FailureCode.RATE_LIMITED.value
    if status >= 500:
        return FailureCode.SERVICE_UNAVAILABLE.value
    return "request_rejected"


def retry_after_seconds(
    response: AIHTTPResponse,
    *,
    fallback: float,
    clock: Callable[[], datetime],
) -> float:
    headers = getattr(response, "headers", None)
    raw: object | None = None
    if isinstance(headers, Mapping):
        raw = next(
            (
                value
                for key, value in headers.items()
                if str(key).casefold() == "retry-after"
            ),
            None,
        )
    if raw is None:
        return fallback
    try:
        seconds = float(str(raw))
    except (TypeError, ValueError):
        try:
            deadline = parsedate_to_datetime(str(raw))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            seconds = (
                deadline.astimezone(UTC) - clock().astimezone(UTC)
            ).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return fallback
        if not isfinite(seconds):
            return fallback
        return min(max(seconds, 0), _MAX_RETRY_AFTER_SECONDS)
    if not isfinite(seconds) or seconds < 0:
        return fallback
    return min(seconds, _MAX_RETRY_AFTER_SECONDS)


def _is_quota_failure(response: AIHTTPResponse) -> bool:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - error body is untrusted
        return False
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if not isinstance(error, dict):
        return False
    evidence = " ".join(
        str(error.get(field, "")).casefold()
        for field in ("code", "type", "message")
    )
    return any(
        marker in evidence
        for marker in (
            "insufficient_quota",
            "quota_exhausted",
            "billing quota",
            "account balance",
        )
    )


def _sleep_and_continue(
    sleeper: Callable[[float], None],
    seconds: float,
) -> bool:
    sleeper(seconds)
    return False
