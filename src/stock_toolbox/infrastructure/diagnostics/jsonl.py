"""Bounded asynchronous JSONL diagnostics with age and LRU retention."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

from stock_toolbox.core.diagnostics.models import (
    DiagnosticEvent,
    DiagnosticLevel,
)
from stock_toolbox.infrastructure.diagnostics.redaction import (
    SensitiveDiagnosticFieldError,
    sanitize_details,
    scrub_text,
)

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
RETENTION_DAYS = 7


@dataclass(frozen=True, slots=True)
class RetentionReport:
    removed_expired: tuple[Path, ...]
    removed_lru: tuple[Path, ...]
    remaining: tuple[Path, ...]
    total_bytes: int


@dataclass(slots=True)
class _Control:
    action: str
    completed: threading.Event


type _QueueItem = DiagnosticEvent | _Control


def enforce_retention(
    root: Path,
    *,
    active_path: Path,
    now: datetime,
    retention_days: int = RETENTION_DAYS,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> RetentionReport:
    files = [
        path
        for path in root.glob("diagnostics-*.jsonl")
        if path.is_file()
    ]
    cutoff = now.timestamp() - timedelta(days=retention_days).total_seconds()
    expired: list[Path] = []
    for path in files:
        if path == active_path:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                expired.append(path)
        except OSError:
            continue

    remaining = [path for path in files if path.exists()]
    total = sum(_safe_size(path) for path in remaining)
    removed_lru: list[Path] = []
    candidates = sorted(
        (path for path in remaining if path != active_path),
        key=_retention_key,
    )
    for path in candidates:
        if total <= max_total_bytes:
            break
        size = _safe_size(path)
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        removed_lru.append(path)

    final = tuple(sorted(path for path in remaining if path.exists()))
    return RetentionReport(
        tuple(expired),
        tuple(removed_lru),
        final,
        sum(_safe_size(path) for path in final),
    )


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _retention_key(path: Path) -> tuple[int, int, str]:
    try:
        stat = path.stat()
        return stat.st_atime_ns, stat.st_mtime_ns, path.name
    except OSError:
        return 0, 0, path.name


class JsonlDiagnosticLogger:
    """One writer thread; callers never wait for disk I/O."""

    def __init__(
        self,
        root: Path,
        *,
        app_version: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_file_bytes: int = MAX_FILE_BYTES,
        max_total_bytes: int = MAX_TOTAL_BYTES,
        retention_days: int = RETENTION_DAYS,
        queue_capacity: int = 4_096,
        start_writer: bool = True,
    ) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._app_version = app_version
        self._clock = clock
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes
        self._retention_days = retention_days
        self._session_id = str(uuid.uuid4())
        self._file_index = 1
        self._active_path = self._new_path()
        self._queue: queue.Queue[_QueueItem] = queue.Queue(maxsize=queue_capacity)
        self._important: deque[DiagnosticEvent] = deque(maxlen=256)
        self._important_lock = threading.Lock()
        self._closed = False
        self._close_result: bool | None = None
        self._rejected_events = 0
        self._dropped_debug_events = 0
        self._write_failures = 0
        self._thread = threading.Thread(
            target=self._run,
            name="diagnostic-jsonl-writer",
            daemon=True,
        )
        if start_writer:
            self._thread.start()

    @property
    def active_path(self) -> Path:
        return self._active_path

    @property
    def rejected_events(self) -> int:
        return self._rejected_events

    @property
    def dropped_debug_events(self) -> int:
        return self._dropped_debug_events

    @property
    def important_backlog(self) -> int:
        with self._important_lock:
            return len(self._important)

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize() + self.important_backlog

    @property
    def write_failures(self) -> int:
        return self._write_failures

    def emit(self, event: DiagnosticEvent) -> None:
        if self._closed:
            return
        try:
            sanitized = DiagnosticEvent(
                event.level,
                event.module,
                event.action,
                event.status,
                task_id=event.task_id,
                stage=event.stage,
                ticker=event.ticker,
                duration_ms=event.duration_ms,
                memory_rss_mb=event.memory_rss_mb,
                memory_peak_mb=event.memory_peak_mb,
                error_code=event.error_code,
                details=sanitize_details(event.details),
            )
        except (SensitiveDiagnosticFieldError, TypeError, ValueError):
            self._rejected_events += 1
            return
        try:
            self._queue.put_nowait(sanitized)
        except queue.Full:
            if sanitized.level is DiagnosticLevel.DEBUG:
                self._dropped_debug_events += 1
                return
            with self._important_lock:
                self._important.append(sanitized)

    def flush(self, timeout_seconds: float = 1.0) -> bool:
        if self._closed:
            return bool(self._close_result)
        return self._request_control("flush", timeout_seconds)

    def close(self, timeout_seconds: float = 1.0) -> bool:
        if self._closed:
            return bool(self._close_result)
        self._closed = True
        self._close_result = self._request_control("close", timeout_seconds)
        return self._close_result

    def clear(self, timeout_seconds: float = 2.0) -> bool:
        if self._closed:
            return False
        return self._request_control("clear", timeout_seconds)

    def _request_control(self, action: str, timeout_seconds: float) -> bool:
        if not self._thread.is_alive():
            return False
        completed = threading.Event()
        command = _Control(action, completed)
        try:
            self._queue.put(command, timeout=max(0.0, timeout_seconds / 2))
        except queue.Full:
            return False
        return completed.wait(max(0.0, timeout_seconds / 2))

    def _run(self) -> None:
        handle: TextIO | None = None
        try:
            handle = self._open_active()
            while True:
                important = self._pop_important()
                item = important if important is not None else self._queue.get()
                if isinstance(item, DiagnosticEvent):
                    handle = self._write_event(handle, item)
                    if important is None:
                        self._queue.task_done()
                    continue
                if item.action == "flush":
                    handle.flush()
                    item.completed.set()
                    self._queue.task_done()
                    continue
                if item.action == "clear":
                    handle.flush()
                    handle.close()
                    for path in self.root.glob("diagnostics-*.jsonl"):
                        try:
                            path.unlink()
                        except OSError:
                            self._write_failures += 1
                    self._file_index += 1
                    self._active_path = self._new_path()
                    handle = self._open_active()
                    item.completed.set()
                    self._queue.task_done()
                    continue
                handle.flush()
                handle.close()
                enforce_retention(
                    self.root,
                    active_path=self._active_path,
                    now=self._clock(),
                    retention_days=self._retention_days,
                    max_total_bytes=self._max_total_bytes,
                )
                item.completed.set()
                self._queue.task_done()
                return
        except OSError:
            self._write_failures += 1
        finally:
            if handle is not None and not handle.closed:
                try:
                    handle.close()
                except OSError:
                    pass

    def _write_event(self, handle: TextIO, event: DiagnosticEvent) -> TextIO:
        try:
            handle.write(self._serialize(event))
            if handle.tell() < self._max_file_bytes:
                return handle
            handle.flush()
            handle.close()
            enforce_retention(
                self.root,
                active_path=self._active_path,
                now=self._clock(),
                retention_days=self._retention_days,
                max_total_bytes=self._max_total_bytes,
            )
            self._file_index += 1
            self._active_path = self._new_path()
            return self._open_active()
        except OSError:
            self._write_failures += 1
            return handle

    def _serialize(self, event: DiagnosticEvent) -> str:
        payload: dict[str, object] = {
            "timestamp": self._clock().isoformat(),
            "app_version": self._app_version,
            "session_id": self._session_id,
            "level": event.level.value,
            "module": event.module,
            "action": event.action,
            "status": event.status.value,
        }
        optional: tuple[tuple[str, object | None], ...] = (
            ("task_id", event.task_id or None),
            ("stage", event.stage or None),
            ("ticker", event.ticker or None),
            ("duration_ms", event.duration_ms),
            ("memory_rss_mb", event.memory_rss_mb),
            ("memory_peak_mb", event.memory_peak_mb),
            ("error_code", event.error_code or None),
            ("details", dict(event.details) or None),
        )
        payload.update((key, value) for key, value in optional if value is not None)
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=lambda value: scrub_text(str(value)),
        ) + "\n"

    def _new_path(self) -> Path:
        timestamp = self._clock().strftime("%Y-%m-%d")
        short_session = self._session_id.split("-", maxsplit=1)[0]
        return self.root / (
            f"diagnostics-{timestamp}-{short_session}-{self._file_index:03d}.jsonl"
        )

    def _open_active(self) -> TextIO:
        return self._active_path.open("a", encoding="utf-8")

    def _pop_important(self) -> DiagnosticEvent | None:
        with self._important_lock:
            return self._important.popleft() if self._important else None
