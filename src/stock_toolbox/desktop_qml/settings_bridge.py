"""Local service settings exposed to QML without revealing saved secrets."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    Property,
    QCoreApplication,
    QObject,
    QRunnable,
    QThreadPool,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices, QGuiApplication

from stock_toolbox import __version__
from stock_toolbox.composition import StockToolboxApplication
from stock_toolbox.core.settings.models import ServiceSettingsInput, ServiceTestResult
from stock_toolbox.core.settings.network import masked_proxy_url
from stock_toolbox.infrastructure.diagnostics.export import export_diagnostics
from stock_toolbox.infrastructure.diagnostics.jsonl import JsonlDiagnosticLogger
from stock_toolbox.infrastructure.diagnostics.query import (
    DiagnosticFileStatus,
    DiagnosticFilter,
    diagnostic_status,
    recent_events,
)
from stock_toolbox.infrastructure.providers.catalog import (
    list_provider_descriptors,
    provider_development_prompt,
)
from stock_toolbox.infrastructure.providers.futu_opend import (
    FUTU_OPEND_GUIDE_URL,
)
from stock_toolbox.runtime.environment import RuntimeEnvironment

_LONGBRIDGE_CHECKS = (
    ("oauth", "官方 OAuth 授权"),
    ("trading_day", "最近完整交易日"),
    ("company_profile", "AAPL 基础资料"),
    ("daily_bars", "AAPL 日 K 线"),
)
_FUTU_CHECKS = (
    ("opend", "本机 OpenD 连接"),
    ("trading_day", "最近完整交易日"),
    ("company_profile", "AAPL 基础资料"),
    ("snapshot", "AAPL 行情快照"),
    ("daily_bars", "AAPL 日 K 线"),
    ("history_quota", "历史 K 线额度"),
)


def _run_futu_quality_process(
    program: Path,
    arguments: list[str],
) -> ServiceTestResult:
    try:
        completed = subprocess.run(
            [str(program), *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return ServiceTestResult("provider", False, "PROVIDER_TIMEOUT")
    except OSError:
        return ServiceTestResult("provider", False, "PROVIDER_FUTU_WORKER_FAILED")

    payload: dict[str, object] | None = None
    for line in reversed(completed.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    quality = payload.get("quality") if payload is not None else None
    if not isinstance(quality, dict):
        return ServiceTestResult("provider", False, "PROVIDER_FUTU_WORKER_FAILED")
    details = quality.get("details", ())
    return ServiceTestResult(
        "provider",
        bool(quality.get("ok", False)),
        str(quality.get("code", "PROVIDER_FUTU_WORKER_FAILED")),
        tuple(str(item) for item in details) if isinstance(details, list) else (),
    )


def _byte_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def choose_default_model(models: tuple[str, ...], current: str) -> str:
    if current in models:
        return current
    for hint in ("flash", "mini", "chat"):
        matching = sorted(model for model in models if hint in model.casefold())
        if matching:
            return matching[0]
    return min(models, default="")


@dataclass(frozen=True, slots=True)
class _AISetupResult:
    models: tuple[str, ...]
    selected_model: str
    quality: ServiceTestResult


@dataclass(frozen=True, slots=True)
class _DiagnosticView:
    status: DiagnosticFileStatus
    events: tuple[dict[str, object], ...]


class _ServiceSignals(QObject):
    finished = Signal(object)


class _ServiceTask(QRunnable):
    def __init__(self, action: Callable[[], object]) -> None:
        super().__init__()
        self.action = action
        self.signals = _ServiceSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.action()
        except Exception as error:  # noqa: BLE001 - sanitized at UI callback
            result = error
        self.signals.finished.emit(result)


class SettingsBridge(QObject):
    changed = Signal()
    finished = Signal(object)
    ai_ready = Signal()
    reset_completed = Signal()
    diagnostics_finished = Signal()
    futu_guidance_requested = Signal()

    def __init__(
        self,
        application: StockToolboxApplication,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._page = "provider"
        self._status = ""
        self._reset_pending = False
        self._reset_summary = ""
        self._task: _ServiceTask | None = None
        self._diagnostic_task: _ServiceTask | None = None
        self._busy_action = ""
        self._yahoo_quality_state = "pending"
        self._yahoo_quality_detail = "尚未检查"
        self._yahoo_quality_checked_at = ""
        self._diagnostic_status = "正在准备"
        self._diagnostic_size_text = "0 B"
        self._diagnostic_last_event = ""
        self._diagnostic_summary = "卡顿 0 · 慢查询 0 · 错误 0"
        self._diagnostic_events: tuple[dict[str, object], ...] = ()
        self._diagnostic_clear_pending = False
        self._pending_client_id = ""
        self._models: tuple[str, ...] = ()
        settings = self._application.settings()
        self._selected_provider_id = (
            settings.provider_mode
            if settings.provider_mode in {"longbridge", "futu"}
            else "longbridge"
        )
        self._selected_ai_model = ""
        self._ai_quality_verified = False
        initial = (
            "passed"
            if self._provider_candidate_configured(self._selected_provider_id)
            else "pending"
        )
        self._provider_check_states = {
            check_id: initial for check_id, _label in self._selected_provider_checks()
        }

    @Property(str, notify=changed)
    def page(self) -> str:
        return self._page

    @Property(list, notify=changed)
    def providers(self) -> list[dict[str, object]]:
        active = self._active_provider_id()
        return [
            {
                "id": item.provider_id,
                "name": item.display_name,
                "summary": item.summary,
                "builtin": item.builtin,
                "configured": self._provider_candidate_configured(item.provider_id),
                "active": item.provider_id == active,
                "selected": item.provider_id == self._selected_provider_id,
            }
            for item in list_provider_descriptors()
        ]

    @Property(str, notify=changed)
    def selected_provider_id(self) -> str:
        return self._selected_provider_id

    @Property(str, notify=changed)
    def active_provider_id(self) -> str:
        return self._active_provider_id()

    def _active_provider_id(self) -> str:
        mode = self._application.settings().provider_mode
        return "longbridge" if mode == "virtual" else mode

    @Property(bool, notify=changed)
    def selected_provider_quality_passed(self) -> bool:
        return self._provider_candidate_configured(self._selected_provider_id)

    @Property(str, constant=True)
    def provider_prompt(self) -> str:
        return provider_development_prompt()

    @Property(list, notify=changed)
    def provider_checks(self) -> list[dict[str, str]]:
        return [
            {
                "id": check_id,
                "label": label,
                "state": self._provider_check_states.get(
                    check_id,
                    "pending",
                ),
            }
            for check_id, label in self._selected_provider_checks()
        ]

    @Property(bool, notify=changed)
    def provider_authorized_pending(self) -> bool:
        return bool(self._pending_client_id)

    @Property(str, constant=True)
    def provider_reference_url(self) -> str:
        return "https://open.longbridge.com/zh-CN/docs/agent-auth"

    @Property(str, constant=True)
    def futu_reference_url(self) -> str:
        return FUTU_OPEND_GUIDE_URL

    @Property(str, constant=True)
    def deepseek_api_keys_url(self) -> str:
        return "https://platform.deepseek.com/api_keys"

    @Property(bool, notify=changed)
    def provider_configured(self) -> bool:
        settings = self._application.settings()
        return settings.provider_mode == "virtual" or settings.provider_configured

    @Property(str, notify=changed)
    def ai_base_url(self) -> str:
        return self._application.settings().ai_base_url

    @Property(str, notify=changed)
    def ai_model(self) -> str:
        return self._selected_ai_model or self._application.settings().ai_model

    @Property(bool, notify=changed)
    def ai_configured(self) -> bool:
        return self._ai_quality_verified or self._application.settings().ai_configured

    @Property(str, notify=changed)
    def display_timezone(self) -> str:
        return self._application.settings().display_timezone

    @Property(str, notify=changed)
    def proxy_mode(self) -> str:
        return self._application.settings().proxy_mode

    @Property(str, notify=changed)
    def proxy_url_hint(self) -> str:
        return masked_proxy_url(self._application.settings().proxy_url)

    @Property(str, notify=changed)
    def api_key_hint(self) -> str:
        return (
            "已保存到本机 SQLite · 留空则保留"
            if self._application.settings().ai_configured
            else "尚未配置"
        )

    @Property(list, notify=changed)
    def models(self) -> list[str]:
        return list(self._models)

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._task is not None

    @Property(str, notify=changed)
    def busy_action(self) -> str:
        return self._busy_action

    @Property(str, notify=changed)
    def yahoo_quality_state(self) -> str:
        return self._yahoo_quality_state

    @Property(str, notify=changed)
    def yahoo_quality_detail(self) -> str:
        return self._yahoo_quality_detail

    @Property(str, notify=changed)
    def yahoo_quality_checked_at(self) -> str:
        return self._yahoo_quality_checked_at

    @Property(bool, notify=changed)
    def reset_pending(self) -> bool:
        return self._reset_pending

    @Property(bool, notify=changed)
    def developer_mode_enabled(self) -> bool:
        return self._application.settings().developer_mode_enabled

    @Property(bool, notify=changed)
    def diagnostic_loading(self) -> bool:
        return self._diagnostic_task is not None

    @Property(str, notify=changed)
    def diagnostic_status(self) -> str:
        return self._diagnostic_status

    @Property(str, notify=changed)
    def diagnostic_size_text(self) -> str:
        return self._diagnostic_size_text

    @Property(str, notify=changed)
    def diagnostic_last_event(self) -> str:
        return self._diagnostic_last_event

    @Property(str, notify=changed)
    def diagnostic_summary(self) -> str:
        return self._diagnostic_summary

    @Property(list, notify=changed)
    def diagnostic_events(self) -> list[dict[str, object]]:
        return list(self._diagnostic_events)

    @Property(bool, notify=changed)
    def diagnostic_clear_pending(self) -> bool:
        return self._diagnostic_clear_pending

    @Property(str, notify=changed)
    def diagnostic_export_default_url(self) -> str:
        stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
        target = Path.home() / "Documents" / f"EquityLens-诊断日志-{stamp}.zip"
        return QUrl.fromLocalFile(str(target)).toString()

    @Property(str, notify=changed)
    def reset_summary(self) -> str:
        return self._reset_summary

    @Slot(str)
    def select_page(self, page: str) -> None:
        if page == "ai" and not self.provider_configured:
            self._status = "请先完成行情供应商授权与质检。"
            self.changed.emit()
            return
        if page in {"provider", "ai", "appearance", "advanced"} and page != self._page:
            self._page = page
            self.changed.emit()
            if page == "advanced":
                self.refresh_diagnostics("", "", "")
            elif page == "ai" and self.ai_configured and not self._models:
                self.refresh_ai_models()

    @Slot(str)
    def select_provider(self, provider_id: str) -> None:
        available = {item.provider_id for item in list_provider_descriptors()}
        if provider_id != "add" and provider_id not in available:
            return
        if provider_id != self._selected_provider_id:
            self._selected_provider_id = provider_id
            if provider_id != "add":
                initial = (
                    "passed" if self._provider_candidate_configured(provider_id) else "pending"
                )
                self._provider_check_states = {
                    check_id: initial for check_id, _label in self._selected_provider_checks()
                }
            self.changed.emit()
            if provider_id == "futu":
                self.futu_guidance_requested.emit()

    @Slot()
    def refresh_providers(self) -> None:
        self.changed.emit()

    @Slot(result=bool)
    def copy_provider_prompt(self) -> bool:
        application = cast(
            QGuiApplication | None,
            QGuiApplication.instance(),
        )
        if application is None:
            return False
        application.clipboard().setText(provider_development_prompt())
        self._status = "供应商开发提示词已复制。"
        self.changed.emit()
        return True

    @Slot(str, str, str, result=bool)
    def save_ai(self, base_url: str, model: str, api_key: str) -> bool:
        current = self._application.settings()
        key = bytearray(api_key.encode()) if api_key else None
        try:
            self._application.save_settings(
                ServiceSettingsInput(
                    current.provider_mode,
                    current.timeout_seconds,
                    current.max_retries,
                    base_url.strip(),
                    model.strip(),
                    current.developer_mode_enabled,
                    current.longbridge_client_id,
                ),
                ai_api_key=key,
            )
        except (OSError, TypeError, ValueError):
            self._status = "保存失败，请检查服务地址和模型。"
            self.changed.emit()
            return False
        finally:
            if key is not None:
                key[:] = b"\x00" * len(key)
        self._selected_ai_model = model.strip()
        self._status = "AI 配置已保存到本机 SQLite。"
        self.changed.emit()
        return True

    @Slot(result=bool)
    def refresh_ai_models(self) -> bool:
        if self._task is not None or not self.ai_configured:
            return False
        self._status = "正在刷新可用模型…"
        self._start(
            self._application.discover_saved_ai_models,
            self._ai_models_finished,
            "ai_models",
        )
        return True

    @Slot(str, result=bool)
    def select_ai_model(self, model: str) -> bool:
        selected = model.strip()
        if self._task is not None or selected not in self._models:
            return False
        if not self.save_ai(self._application.settings().ai_base_url, selected, ""):
            return False
        self._ai_quality_verified = False
        self._status = f"已选择 {selected}，正在执行能力质检…"
        self._start(
            self._application.preview_ai_classification,
            self._ai_finished,
            "ai_quality",
        )
        return True

    @Slot(str, str, str, result=bool)
    def save_network(
        self,
        display_timezone: str,
        proxy_mode: str,
        proxy_url: str,
    ) -> bool:
        current = self._application.settings()
        candidate_url = proxy_url.strip()
        if proxy_mode == "custom" and not candidate_url and current.proxy_mode == "custom":
            candidate_url = current.proxy_url
        try:
            self._application.save_settings(
                ServiceSettingsInput(
                    current.provider_mode,
                    current.timeout_seconds,
                    current.max_retries,
                    current.ai_base_url,
                    current.ai_model,
                    current.developer_mode_enabled,
                    current.longbridge_client_id,
                    display_timezone,
                    proxy_mode,
                    candidate_url,
                )
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            self._status = "网络设置保存失败，请检查时区和代理地址。"
            self.changed.emit()
            return False
        self._status = "日期、时间与网络设置已保存。"
        self.changed.emit()
        return True

    @Slot(result=bool)
    def quality_provider(self) -> bool:
        if self._task is not None:
            return False
        settings = self._application.settings()
        action: Callable[[], object]
        if self._selected_provider_id == "futu":
            program = self._futu_quality_worker_program()
            action = (
                (lambda: _run_futu_quality_process(
                    program,
                    self._futu_quality_worker_arguments(),
                ))
                if program is not None
                else self._application.quality_futu
            )
        elif settings.provider_mode == "virtual":
            action = self._application.test_provider_connection
        elif self._pending_client_id or settings.longbridge_client_id:
            candidate = self._pending_client_id or settings.longbridge_client_id
            action = lambda: self._application.quality_longbridge(candidate)
        else:
            self._status = "请先完成 Longbridge 浏览器授权。"
            self.changed.emit()
            return False
        for check_id, _label in self._selected_provider_checks():
            self._provider_check_states[check_id] = "checking"
        self._status = "正在执行行情质检…"
        self._start(action, self._provider_finished, "provider_quality")
        return True

    def _futu_quality_worker_program(self) -> Path | None:
        if self._application.paths.environment not in {
            RuntimeEnvironment.PRODUCTION,
            RuntimeEnvironment.DEVELOPMENT,
        }:
            return None
        candidate = Path(QCoreApplication.applicationDirPath()) / "stock-toolbox"
        return candidate if candidate.is_file() else None

    def _futu_quality_worker_arguments(self) -> list[str]:
        environment = self._application.paths.environment
        environment_name = (
            "production"
            if environment is RuntimeEnvironment.PRODUCTION
            else "dev"
        )
        home = next(
            (
                parent.parent
                for parent in self._application.paths.data_root.parents
                if parent.name == "Library"
            ),
            Path.home(),
        )
        return [
            "--env",
            environment_name,
            "--home",
            str(home),
            "services",
            "quality",
            "--provider",
            "futu",
            "--json",
        ]

    @Slot(result=bool)
    def open_futu_opend(self) -> bool:
        opened = self._application.open_futu_opend()
        self._status = (
            "已打开 Futu OpenD，请在其中完成登录。"
            if opened
            else "未找到 Futu OpenD，请先下载安装。"
        )
        self.changed.emit()
        return opened

    @Slot(result=bool)
    def open_futu_download(self) -> bool:
        return QDesktopServices.openUrl(QUrl(FUTU_OPEND_GUIDE_URL))

    @Slot(result=bool)
    def activate_selected_provider(self) -> bool:
        if (
            self._task is not None
            or self._selected_provider_id not in {"longbridge", "futu"}
            or not self.selected_provider_quality_passed
        ):
            return False
        provider_id = self._selected_provider_id
        self._status = "正在切换当前行情供应商…"
        self._start(
            lambda: self._application.activate_provider(provider_id),
            self._provider_activation_finished,
            "provider_activate",
        )
        return True

    @Slot(result=bool)
    def quality_proxy(self) -> bool:
        if self._task is not None:
            return False
        self._status = "正在检查当前网络路径…"
        self._start(
            self._application.test_network_connection,
            self._network_finished,
            "proxy_quality",
        )
        return True

    @Slot(result=bool)
    def quality_yahoo(self) -> bool:
        if self._task is not None:
            return False
        self._yahoo_quality_state = "checking"
        self._yahoo_quality_detail = "正在读取 NVDA 日线"
        self._status = "正在检查 Yahoo 备用行情…"
        self._start(
            self._application.test_yahoo_connection,
            self._yahoo_finished,
            "yahoo_quality",
        )
        return True

    @Slot(result=bool)
    def authorize_provider(self) -> bool:
        if self._task is not None:
            return False
        self._status = "正在自动配置，等待浏览器完成长桥授权…"
        self._start(
            self._application.authorize_longbridge,
            self._authorization_finished,
            "provider_authorize",
        )
        return True

    @Slot(str, str, result=bool)
    def auto_configure_ai(self, base_url: str, api_key: str) -> bool:
        if self._task is not None:
            return False
        normalized_url = base_url.strip()
        if not normalized_url or not api_key:
            self._status = "请先填写 Base URL 和 API Key。"
            self.changed.emit()
            return False
        key = bytearray(api_key.encode())
        current_model = self._selected_ai_model or self._application.settings().ai_model

        def action() -> object:
            try:
                models = self._application.discover_ai_models(
                    normalized_url,
                    bytearray(key),
                )
                selected = choose_default_model(models, current_model)
                if not selected:
                    raise ValueError("ai_models_empty")
                quality = self._application.configure_ai(
                    normalized_url,
                    selected,
                    key,
                )
                return _AISetupResult(models, selected, quality)
            finally:
                key[:] = b"\x00" * len(key)

        self._status = "正在发现模型并执行 AI 分类质检…"
        self._start(action, self._ai_setup_finished, "ai_setup")
        return True

    @Slot(str, str, str, result=bool)
    def quality_ai(self, base_url: str, model: str, api_key: str) -> bool:
        if self._task is not None:
            return False
        if api_key:
            key = bytearray(api_key.encode())
            action: Callable[[], object] = lambda: self._application.configure_ai(
                base_url,
                model,
                key,
            )
        else:
            action = self._application.preview_ai_classification
        self._status = "AI 分类质检中…"
        self._start(action, self._ai_finished, "ai_quality")
        return True

    @Slot(bool, result=bool)
    def set_developer_mode(self, enabled: bool) -> bool:
        current = self._application.settings()
        try:
            self._application.save_settings(
                ServiceSettingsInput(
                    current.provider_mode,
                    current.timeout_seconds,
                    current.max_retries,
                    current.ai_base_url,
                    current.ai_model,
                    enabled,
                    current.longbridge_client_id,
                )
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            self._status = "开发者模式更新失败。"
            self.changed.emit()
            return False
        self._status = (
            "开发者模式已启用；场景运行仍使用独立临时数据库。" if enabled else "开发者模式已关闭。"
        )
        self.changed.emit()
        return True

    @Slot(str, str, str, result=bool)
    def refresh_diagnostics(
        self,
        module: str = "",
        level: str = "",
        query: str = "",
    ) -> bool:
        if self._diagnostic_task is not None:
            return False
        filters = DiagnosticFilter(
            module.strip(),
            level.strip(),
            query.strip(),
        )
        self._diagnostic_status = "正在读取"
        self._start_diagnostic(
            lambda: _DiagnosticView(
                diagnostic_status(self._application.paths.log_root),
                tuple(
                    recent_events(
                        self._application.paths.log_root,
                        filters=filters,
                    )
                ),
            ),
            self._diagnostic_view_finished,
        )
        return True

    @Slot(result=bool)
    def open_diagnostics_folder(self) -> bool:
        root = self._application.paths.log_root
        root.mkdir(parents=True, exist_ok=True)
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    @Slot(str, result=bool)
    def export_diagnostics(self, target_url: str) -> bool:
        if self._diagnostic_task is not None:
            return False
        url = QUrl(target_url)
        target = Path(url.toLocalFile() if url.isLocalFile() else target_url)
        if target.suffix.casefold() != ".zip":
            target = target.with_suffix(".zip")

        def action() -> object:
            self._application.diagnostics.flush()
            return export_diagnostics(
                self._application.paths.log_root,
                target,
                environment={
                    "app_version": __version__,
                    "environment": self._application.paths.environment.value,
                    "qt": "PySide6",
                },
            )

        self._diagnostic_status = "正在导出"
        self._start_diagnostic(action, self._diagnostic_export_finished)
        return True

    @Slot()
    def request_clear_diagnostics(self) -> None:
        self._diagnostic_clear_pending = True
        self.changed.emit()

    @Slot()
    def cancel_clear_diagnostics(self) -> None:
        if self._diagnostic_clear_pending:
            self._diagnostic_clear_pending = False
            self.changed.emit()

    @Slot(str, result=bool)
    def confirm_clear_diagnostics(self, confirmation: str) -> bool:
        if (
            not self._diagnostic_clear_pending
            or confirmation.strip() != "清空日志"
            or self._diagnostic_task is not None
        ):
            return False

        def action() -> object:
            diagnostics = self._application.diagnostics
            if isinstance(diagnostics, JsonlDiagnosticLogger):
                if not diagnostics.clear():
                    raise OSError("diagnostic_clear_failed")
            else:
                for path in self._application.paths.log_root.glob("diagnostics-*.jsonl"):
                    path.unlink(missing_ok=True)
            return _DiagnosticView(
                diagnostic_status(self._application.paths.log_root),
                tuple(recent_events(self._application.paths.log_root)),
            )

        self._diagnostic_clear_pending = False
        self._diagnostic_status = "正在清空"
        self._start_diagnostic(action, self._diagnostic_view_finished)
        return True

    @Slot(result=bool)
    def complete_first_run(self) -> bool:
        try:
            self._application.complete_first_run()
        except (OSError, RuntimeError, ValueError):
            self._status = "请先完成一个行情供应商的质检与启用。"
            self.changed.emit()
            return False
        self._status = "首次配置已完成。"
        self.changed.emit()
        return True

    @Slot()
    def request_reset(self) -> None:
        securities, classifications, watchlists, histories = self._application.reset_counts()
        self._reset_summary = (
            f"证券 {securities} · 分类 {classifications} · 股票池 {watchlists} · 历史 {histories}"
        )
        self._reset_pending = True
        self.changed.emit()

    @Slot()
    def cancel_reset(self) -> None:
        if self._reset_pending:
            self._reset_pending = False
            self.changed.emit()

    @Slot(str, result=bool)
    def confirm_reset(self, confirmation: str) -> bool:
        if not self._reset_pending or confirmation.strip() != "恢复默认":
            return False
        try:
            self._application.reset_local_data()
        except (OSError, RuntimeError):
            self._status = "恢复默认失败，本机数据未完整清理。"
            self.changed.emit()
            return False
        self._restore_clean_state()
        self._status = "本机数据已清空，可以从全新配置开始。"
        self.changed.emit()
        self.reset_completed.emit()
        return True

    def _start(
        self,
        action: Callable[[], object],
        callback: Callable[[object], None],
        busy_action: str = "",
    ) -> None:
        task = _ServiceTask(action)
        self._task = task
        self._busy_action = busy_action
        task.signals.finished.connect(callback)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)

    def _start_diagnostic(
        self,
        action: Callable[[], object],
        callback: Callable[[object], None],
    ) -> None:
        task = _ServiceTask(action)
        self._diagnostic_task = task
        task.signals.finished.connect(callback)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)

    @Slot(object)
    def _diagnostic_view_finished(self, raw: object) -> None:
        self._diagnostic_task = None
        if isinstance(raw, _DiagnosticView):
            self._apply_diagnostic_view(raw)
        else:
            self._diagnostic_status = "暂不可用"
        self.changed.emit()
        self.diagnostics_finished.emit()

    @Slot(object)
    def _diagnostic_export_finished(self, raw: object) -> None:
        self._diagnostic_task = None
        self._diagnostic_status = "诊断包已导出" if isinstance(raw, Path) else "诊断包导出失败"
        self.changed.emit()
        self.diagnostics_finished.emit()

    def _apply_diagnostic_view(self, view: _DiagnosticView) -> None:
        self._diagnostic_status = {
            "normal": "正常",
            "unavailable": "暂不可用",
        }.get(view.status.health, "受限")
        self._diagnostic_size_text = _byte_size(view.status.total_bytes)
        self._diagnostic_last_event = view.status.last_event
        self._diagnostic_summary = (
            f"卡顿 {view.status.stall_count} · "
            f"慢查询 {view.status.slow_query_count} · "
            f"错误 {view.status.error_count}"
        )
        priority = {"error": 2, "warning": 1}
        self._diagnostic_events = tuple(
            sorted(
                view.events,
                key=lambda event: (
                    priority.get(str(event.get("level", "")), 0),
                    str(event.get("timestamp", "")),
                ),
                reverse=True,
            )
        )

    @Slot(object)
    def _provider_finished(self, raw: object) -> None:
        self._task = None
        self._busy_action = ""
        if isinstance(raw, ServiceTestResult) and raw.ok:
            self._pending_client_id = ""
            for check_id, _label in self._selected_provider_checks():
                self._provider_check_states[check_id] = "passed"
            self._status = (
                (
                    "富途质检通过 · 当前已启用"
                    if self._active_provider_id() == "futu"
                    else "富途质检通过 · 可以设为当前供应商"
                )
                if self._selected_provider_id == "futu"
                else "质检通过 · 授权、交易日、公司资料、日线均可用"
            )
        else:
            code = raw.code if isinstance(raw, ServiceTestResult) else "unknown"
            completed = set(raw.details) if isinstance(raw, ServiceTestResult) else set()
            failed_check = {
                "PROVIDER_OAUTH_FAILED": "oauth",
                "PROVIDER_TRADING_DAY_FAILED": "trading_day",
                "PROVIDER_PROFILE_FAILED": "company_profile",
                "PROVIDER_SNAPSHOT_FAILED": "snapshot",
                "PROVIDER_DAILY_BARS_FAILED": "daily_bars",
                "PROVIDER_QUOTA_FAILED": "history_quota",
                "futu_opend_not_installed": "opend",
                "futu_opend_not_running": "opend",
            }.get(code)
            for check_id, _label in self._selected_provider_checks():
                self._provider_check_states[check_id] = (
                    "passed"
                    if check_id in completed
                    else ("failed" if check_id == failed_check else "pending")
                )
            detail = {
                "futu_opend_not_installed": "未安装 Futu OpenD。",
                "futu_opend_not_running": "Futu OpenD 尚未启动或登录。",
                "PROVIDER_TRADING_DAY_FAILED": "最近完整交易日读取失败。",
                "PROVIDER_PROFILE_FAILED": "AAPL 基础资料读取失败。",
                "PROVIDER_SNAPSHOT_FAILED": "AAPL 行情快照读取失败。",
                "PROVIDER_DAILY_BARS_FAILED": "AAPL 日 K 线读取失败。",
                "PROVIDER_QUOTA_FAILED": "历史 K 线额度读取失败。",
                "PROVIDER_TIMEOUT": "质检超时，请确认 OpenD 保持登录后重试。",
                "PROVIDER_FUTU_WORKER_FAILED": "质检进程异常，请重新打开软件后重试。",
                "PROVIDER_FUTU_FAILED": "OpenD 返回了无法识别的错误。",
            }.get(code, f"错误代码 {code}。")
            self._status = (
                f"富途质检未通过：{detail}"
                if self._selected_provider_id == "futu"
                else f"行情质检失败：{detail}"
            )
        self.changed.emit()
        self.finished.emit(raw)

    @Slot(object)
    def _ai_models_finished(self, raw: object) -> None:
        self._task = None
        self._busy_action = ""
        if (
            isinstance(raw, tuple)
            and raw
            and all(isinstance(model, str) and model.strip() for model in raw)
        ):
            self._models = tuple(dict.fromkeys(raw))
            self._status = f"已发现 {len(self._models)} 个可用模型。"
        else:
            self._models = ()
            self._status = "模型列表刷新失败；当前已保存模型仍可继续使用。"
        self.changed.emit()
        self.finished.emit(raw)

    @Slot(object)
    def _provider_activation_finished(self, raw: object) -> None:
        self._task = None
        self._busy_action = ""
        if isinstance(raw, Exception):
            self._status = "切换失败，原行情供应商保持不变。"
        else:
            self._status = "当前行情供应商已切换。"
        self.changed.emit()
        self.finished.emit(raw)

    def _selected_provider_checks(self) -> tuple[tuple[str, str], ...]:
        if self._selected_provider_id == "futu":
            return _FUTU_CHECKS
        if self._selected_provider_id == "longbridge":
            return _LONGBRIDGE_CHECKS
        return ()

    def _provider_candidate_configured(self, provider_id: str) -> bool:
        settings = self._application.settings()
        if provider_id == "futu":
            return settings.futu_configured
        if provider_id == "longbridge":
            return (
                settings.provider_mode == "virtual"
                or (settings.provider_mode == "longbridge" and settings.provider_configured)
                or bool(settings.longbridge_client_id)
            )
        return False

    @Slot(object)
    def _network_finished(self, raw: object) -> None:
        self._task = None
        self._busy_action = ""
        self._status = (
            "网络质检通过；行情仍以供应商质检为准。"
            if isinstance(raw, ServiceTestResult) and raw.ok
            else "网络质检失败，请检查代理地址或网络状态。"
        )
        self.changed.emit()
        self.finished.emit(raw)

    @Slot(object)
    def _yahoo_finished(self, raw: object) -> None:
        self._task = None
        self._busy_action = ""
        passed = isinstance(raw, ServiceTestResult) and raw.ok
        self._yahoo_quality_state = "passed" if passed else "failed"
        self._yahoo_quality_detail = "NVDA 日线可用" if passed else "无法读取 NVDA 日线"
        self._yahoo_quality_checked_at = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")
        self._status = (
            "Yahoo 备用行情质检通过 · NVDA 日线可用。"
            if passed
            else "Yahoo 备用行情不可用，请检查网络或代理设置。"
        )
        self.changed.emit()
        self.finished.emit(raw)

    @Slot(object)
    def _authorization_finished(self, raw: object) -> None:
        self._task = None
        self._busy_action = ""
        if isinstance(raw, ServiceTestResult) and raw.ok:
            self._pending_client_id = raw.details[0] if raw.details else ""
            self._provider_check_states["oauth"] = "passed"
            for check_id, _label in _LONGBRIDGE_CHECKS[1:]:
                self._provider_check_states[check_id] = "pending"
            self._status = "官方授权已完成，请点击“我已完成授权，开始自检”。"
        else:
            code = raw.code if isinstance(raw, ServiceTestResult) else "unknown"
            self._provider_check_states["oauth"] = "failed"
            self._status = f"Longbridge 授权失败 · {code}"
        self.changed.emit()
        self.finished.emit(raw)

    @Slot(object)
    def _ai_setup_finished(self, raw: object) -> None:
        self._task = None
        self._busy_action = ""
        if isinstance(raw, _AISetupResult) and raw.quality.ok:
            self._models = raw.models
            self._selected_ai_model = raw.selected_model
            self._ai_quality_verified = True
            details = "、".join(raw.quality.details)
            self._status = f"AI 质检通过 · 已自动选择 {raw.selected_model}" + (
                f" · {details}" if details else ""
            )
            self.ai_ready.emit()
        elif isinstance(raw, _AISetupResult):
            self._status = f"AI 分类质检失败 · {raw.quality.code}"
        else:
            self._status = "AI 自动检测失败，请检查 URL、Key 或服务状态。"
        self.changed.emit()
        self.finished.emit(raw)

    @Slot(object)
    def _ai_finished(self, raw: object) -> None:
        self._task = None
        self._busy_action = ""
        if isinstance(raw, ServiceTestResult) and raw.ok:
            self._ai_quality_verified = True
            self._status = "AI 质检通过 · " + "、".join(raw.details)
            self.ai_ready.emit()
        else:
            code = raw.code if isinstance(raw, ServiceTestResult) else "unknown"
            self._status = f"AI 分类质检失败 · {code}"
        self.changed.emit()
        self.finished.emit(raw)

    def _restore_clean_state(self) -> None:
        self._page = "provider"
        self._reset_pending = False
        self._reset_summary = ""
        self._pending_client_id = ""
        self._models = ()
        self._selected_provider_id = "longbridge"
        self._selected_ai_model = ""
        self._ai_quality_verified = False
        self._yahoo_quality_state = "pending"
        self._yahoo_quality_detail = "尚未检查"
        self._yahoo_quality_checked_at = ""
        initial = "passed" if self.provider_configured else "pending"
        self._provider_check_states = {check_id: initial for check_id, _label in _LONGBRIDGE_CHECKS}
