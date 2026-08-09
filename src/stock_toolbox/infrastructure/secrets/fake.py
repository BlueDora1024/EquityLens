"""In-memory Secret Store used by deterministic tests and scenarios."""

from __future__ import annotations

from stock_toolbox.infrastructure.secrets.store import (
    SecretReference,
    SecretStoreError,
)


class FakeSecretStore:
    def __init__(self) -> None:
        self._items: dict[SecretReference, bytearray] = {}
        self._delete_failures: set[SecretReference] = set()

    def create(self, reference: SecretReference, secret: bytearray) -> None:
        if reference in self._items:
            raise SecretStoreError("secret_create_conflict")
        self._items[reference] = bytearray(secret)

    def read(self, reference: SecretReference) -> bytearray:
        try:
            return bytearray(self._items[reference])
        except KeyError as error:
            raise SecretStoreError("secret_not_found") from error

    def exists(self, reference: SecretReference) -> bool:
        return reference in self._items

    def delete(self, reference: SecretReference) -> None:
        if reference in self._delete_failures:
            raise SecretStoreError("secret_delete_failed")
        secret = self._items.pop(reference, None)
        if secret is not None:
            secret[:] = b"\x00" * len(secret)

    def fail_delete_for(self, reference: SecretReference) -> None:
        self._delete_failures.add(reference)

    def allow_delete_for(self, reference: SecretReference) -> None:
        self._delete_failures.discard(reference)
