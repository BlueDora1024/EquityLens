"""OpenAI-compatible plain-text client for manual technical reports."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from time import sleep
from typing import Any
from urllib.parse import urlsplit

import httpx

from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.infrastructure.ai.openai_compatible import (
    AIAdapterError,
    AIServiceConfig,
    HTTPClientPort,
    ResponsePort,
    normalize_chat_endpoint,
)
from stock_toolbox.infrastructure.ai.request_retry import (
    AIRequestFailure,
    request_with_retry,
)
from stock_toolbox.infrastructure.secrets.store import SecretReaderPort


class OpenAICompatibleTechnicalReport:
    def __init__(
        self,
        config: AIServiceConfig,
        secret_store: SecretReaderPort,
        *,
        client: HTTPClientPort | None = None,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not config.model.strip() or not 0 <= config.max_retries <= 5:
            raise ValueError("AI configuration is invalid")
        self.model = config.model
        self._config = config
        self._endpoint = normalize_chat_endpoint(config.base_url)
        self._secret_store = secret_store
        self._client = client or httpx.Client(
            follow_redirects=False,
            timeout=float(config.timeout_seconds),
        )
        self._sleeper = sleeper or sleep
        self._use_cancellable_wait = sleeper is None
        self._clock = clock
        self._disable_thinking = (
            urlsplit(config.base_url).hostname == "api.deepseek.com"
            and config.model in {"deepseek-v4-flash", "deepseek-v4-pro"}
        )

    def generate(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        *,
        operation_control: OperationControl | None = None,
    ) -> str:
        secret = self._secret_store.read(self._config.config_revision)
        try:
            key = secret.decode("utf-8")
            payload: dict[str, Any] = {
                "model": self._config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            user_payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                ],
                "temperature": 0,
                "max_tokens": 1800,
                "stream": False,
            }
            if self._disable_thinking:
                payload["thinking"] = {"type": "disabled"}
            try:
                response = request_with_retry(
                    lambda: self._client.post(
                        self._endpoint,
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json=payload,
                    ),
                    self._parse_content,
                    max_retries=self._config.max_retries,
                    sleeper=self._sleeper,
                    cancellation_requested=(
                        operation_control.cancellation_requested
                        if operation_control is not None
                        else lambda: False
                    ),
                    cancellation_wait=(
                        operation_control.wait_for_cancellation
                        if operation_control is not None
                        and self._use_cancellable_wait
                        else None
                    ),
                    clock=self._clock,
                )
            except AIRequestFailure as error:
                raise AIAdapterError(error.code) from error
            return response
        finally:
            secret[:] = b"\x00" * len(secret)

    @classmethod
    def _parse_content(cls, response: ResponsePort) -> str:
        try:
            return cls._content(response.json())
        except AIAdapterError as error:
            raise AIRequestFailure(error.code) from error
        except Exception as error:
            raise AIRequestFailure("invalid_response") from error

    @staticmethod
    def _content(raw: Any) -> str:
        try:
            content = raw["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError) as error:
            raise AIAdapterError("invalid_response") from error
        if not isinstance(content, str) or not content.strip():
            raise AIAdapterError("invalid_response")
        return content.strip()
