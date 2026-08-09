"""Secret-store protocol shared by production and deterministic adapters."""

from __future__ import annotations

from typing import Protocol

SecretReference = str | int


class SecretStoreError(Exception):
    """Sanitized secret-store failure."""


class SecretReaderPort(Protocol):
    def read(self, reference: SecretReference) -> bytearray: ...


class SecretStorePort(SecretReaderPort, Protocol):
    def create(self, reference: SecretReference, secret: bytearray) -> None: ...

    def exists(self, reference: SecretReference) -> bool: ...

    def delete(self, reference: SecretReference) -> None: ...
