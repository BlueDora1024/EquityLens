"""Lazy construction of the optional Futu quote SDK context."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast


class ClosableFutuContext(Protocol):
    def close(self) -> object: ...


class FutuQuoteContextFactory:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        *,
        context_type: Callable[..., object] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._context_type = context_type

    def create(self) -> ClosableFutuContext:
        context_type = self._context_type
        if context_type is None:
            from futu import OpenQuoteContext  # type: ignore[import-untyped]

            context_type = cast(Callable[..., object], OpenQuoteContext)
        return cast(
            ClosableFutuContext,
            context_type(host=self.host, port=self.port),
        )


def close_futu_context(context: Any) -> None:
    close = getattr(context, "close", None)
    if callable(close):
        close()
