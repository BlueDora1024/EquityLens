"""Stable persistence errors that do not expose SQL or row values."""

from __future__ import annotations


class PersistenceError(Exception):
    """Base adapter error with a stable non-sensitive code."""

    code = "persistence_internal"

    def __init__(self, message: str = "Persistence operation failed") -> None:
        super().__init__(message)


class PersistenceDataError(PersistenceError):
    """Stored or boundary data does not satisfy the persistence contract."""

    code = "persistence_data_error"


class PersistenceConflictError(PersistenceError):
    code = "persistence_conflict"


class PersistenceValidationError(PersistenceError):
    code = "data_validation_failed"


class ConcurrentModificationError(PersistenceError):
    code = "concurrent_modification"


class DatabaseBusyError(PersistenceError):
    code = "database_busy"


class StorageUnavailableError(PersistenceError):
    code = "storage_unavailable"


class DatabaseCorruptError(PersistenceError):
    code = "database_corrupt"


class MigrationIncompatibleError(PersistenceError):
    code = "migration_incompatible"
