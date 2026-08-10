"""Background-safe Qt facade for the official GitHub updater."""

from __future__ import annotations

import platform
import plistlib
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Property, QCoreApplication, QObject, QRunnable, QThreadPool, Signal, Slot
from shiboken6 import isValid

from stock_toolbox import __version__
from stock_toolbox.infrastructure.updates.installer import launch_replacement, stage_update
from stock_toolbox.infrastructure.updates.models import BuildIdentity, ReleaseInfo
from stock_toolbox.infrastructure.updates.service import GitHubUpdateService, is_newer_version


class _UpdateService(Protocol):
    def latest_release(self, architecture: str) -> ReleaseInfo: ...

    def download(
        self,
        release: ReleaseInfo,
        destination: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> tuple[Path, str]: ...


class _TaskSignals(QObject):
    finished = Signal(object)


class _Task(QRunnable):
    def __init__(self, action: Callable[[], object]) -> None:
        super().__init__()
        self.action = action
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.action()
        except Exception as error:  # noqa: BLE001 - sanitized at bridge boundary
            result = error
        self.signals.finished.emit(result)


def _normalized_architecture() -> str:
    machine = platform.machine().casefold()
    return "arm64" if machine in {"arm64", "aarch64"} else "x86_64"


def _current_app_bundle() -> Path | None:
    executable = Path(sys.executable).absolute()
    return next((parent for parent in executable.parents if parent.suffix == ".app"), None)


def read_build_identity(bundle: Path | None = None) -> BuildIdentity:
    architecture = _normalized_architecture()
    candidate = bundle or _current_app_bundle()
    if candidate is not None:
        info_path = candidate / "Contents/Info.plist"
        if info_path.is_file():
            with info_path.open("rb") as stream:
                info = plistlib.load(stream)
            return BuildIdentity(
                str(info.get("CFBundleShortVersionString") or __version__),
                str(info.get("EquityLensReleaseTag") or "local"),
                str(info.get("EquityLensGitSHA") or "unknown"),
                architecture,
            )
    return BuildIdentity(__version__, "local", "development", architecture)


class UpdateBridge(QObject):
    changed = Signal()
    check_finished = Signal()
    download_progress = Signal(int)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        identity: BuildIdentity | None = None,
        service: _UpdateService | None = None,
    ) -> None:
        super().__init__(parent)
        self._identity = identity or read_build_identity()
        self._service = service or GitHubUpdateService()
        self._task: _Task | None = None
        self._release: ReleaseInfo | None = None
        self._status = "idle"
        self._message = ""
        self._prompt_visible = False
        self._progress = 0
        self.download_progress.connect(self._set_progress)

    @Property(str, constant=True)
    def current_version(self) -> str:
        return self._identity.version

    @Property(str, constant=True)
    def current_tag(self) -> str:
        return self._identity.tag

    @Property(str, constant=True)
    def current_sha(self) -> str:
        return self._identity.short_sha

    @Property(str, constant=True)
    def architecture(self) -> str:
        return "Apple Silicon" if self._identity.architecture == "arm64" else "Intel"

    @Property(bool, constant=True)
    def startup_check_enabled(self) -> bool:
        return bool(getattr(sys, "frozen", False))

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Property(str, notify=changed)
    def message(self) -> str:
        return self._message

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._task is not None

    @Property(bool, notify=changed)
    def update_available(self) -> bool:
        return bool(self._release and is_newer_version(self._release.version, self._identity.version))

    @Property(bool, notify=changed)
    def prompt_visible(self) -> bool:
        return self._prompt_visible

    @Property(str, notify=changed)
    def latest_tag(self) -> str:
        return self._release.tag if self._release else ""

    @Property(list, notify=changed)
    def release_notes(self) -> list[str]:
        return list(self._release.notes) if self._release else []

    @Property(int, notify=changed)
    def progress(self) -> int:
        return self._progress

    @Slot(result=bool)
    def check_on_startup(self) -> bool:
        return self._check(silent=True)

    @Slot(result=bool)
    def check_now(self) -> bool:
        return self._check(silent=False)

    def _check(self, *, silent: bool) -> bool:
        if self._task is not None:
            return False
        self._status = "checking"
        self._message = "正在检查 GitHub 正式版本…"
        self.changed.emit()
        self._start(
            lambda: self._service.latest_release(self._identity.architecture),
            lambda raw: self._check_completed(raw, silent=silent),
        )
        return True

    def _check_completed(self, raw: object, *, silent: bool) -> None:
        if isinstance(raw, ReleaseInfo):
            self._release = raw
            if self.update_available:
                self._status = "available"
                self._message = f"发现新版本 {raw.tag}"
                self._prompt_visible = True
            else:
                self._status = "current"
                self._message = "当前已是最新正式版本。"
        elif silent:
            self._status = "idle"
            self._message = ""
        else:
            self._status = "error"
            self._message = "无法连接 GitHub，请检查网络或代理后重试。"
        self.changed.emit()
        self.check_finished.emit()

    @Slot()
    def dismiss_prompt(self) -> None:
        self._prompt_visible = False
        self.changed.emit()

    @Slot(result=bool)
    def install_update(self) -> bool:
        if self._task is not None or not self.update_available or self._release is None:
            return False
        target = _current_app_bundle()
        if target is None:
            self._status = "error"
            self._message = "开发环境不能原位更新，请使用正式应用检查。"
            self.changed.emit()
            return False
        release = self._release
        self._status = "downloading"
        self._message = f"正在下载 {release.tag}…"
        self._progress = 0
        self.changed.emit()

        def action() -> object:
            archive = Path(tempfile.mkdtemp(prefix="equitylens-download-")) / release.archive.name
            service = self._service
            def report(received: int, total: int) -> None:
                if total > 0:
                    self.download_progress.emit(min(99, int(received * 100 / total)))

            downloaded, expected = service.download(release, archive, report)
            _bundle, script = stage_update(
                downloaded,
                expected,
                version=release.version,
                target=target,
            )
            return script

        self._start(action, self._install_completed)
        return True

    @Slot(int)
    def _set_progress(self, value: int) -> None:
        self._progress = max(0, min(100, value))
        self.changed.emit()

    def _install_completed(self, raw: object) -> None:
        if isinstance(raw, Path):
            self._status = "restarting"
            self._message = "校验通过，正在重启并完成更新…"
            self._progress = 100
            self.changed.emit()
            launch_replacement(raw)
            QCoreApplication.quit()
            return
        self._status = "error"
        self._message = "更新未完成，当前版本保持不变；请检查网络或应用目录权限。"
        self.changed.emit()

    def _start(self, action: Callable[[], object], completed: Callable[[object], None]) -> None:
        task = _Task(action)
        self._task = task

        def finish(raw: object) -> None:
            if not isValid(self):
                return
            self._task = None
            completed(raw)

        task.signals.finished.connect(finish)
        QThreadPool.globalInstance().start(task)
