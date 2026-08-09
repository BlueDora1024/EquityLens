"""Destructive reset limited to files owned by this application."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from stock_toolbox.infrastructure.providers.longbridge_oauth import (
    LongbridgeOAuthService,
)
from stock_toolbox.runtime.paths import RuntimePaths


def reset_local_state(
    paths: RuntimePaths,
    oauth: LongbridgeOAuthService,
    client_id: str,
    *,
    clear_diagnostics: Callable[[], bool] | None = None,
) -> None:
    if client_id:
        oauth.clear(client_id)
    for database in {paths.database, paths.global_ai_database}:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{database}{suffix}").unlink(missing_ok=True)
    if clear_diagnostics is not None:
        clear_diagnostics()
    elif paths.log_root.exists():
        shutil.rmtree(paths.log_root)
