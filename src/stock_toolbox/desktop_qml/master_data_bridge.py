"""Shared securities, classifications, and watchlists for QML pages."""

from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import (
    Property,
    QCoreApplication,
    QObject,
    QProcess,
    QRunnable,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)

from stock_toolbox.composition import (
    SecurityRefreshProgress,
    SecurityRefreshResult,
    StockToolboxApplication,
)
from stock_toolbox.core.operations.registry import OperationStatus
from stock_toolbox.core.securities.import_input import (
    ImportInputError,
    ImportInputPreview,
    parse_import_file,
    select_import_column,
)
from stock_toolbox.core.securities.import_service import (
    ImportItemResult,
    ImportProgress,
    ImportResult,
    ImportStatus,
)
from stock_toolbox.desktop_qml.progress_diagnostics import emit_progress
from stock_toolbox.infrastructure.persistence.errors import PersistenceError
from stock_toolbox.runtime.environment import RuntimeEnvironment


class _ImportSignals(QObject):
    progress = Signal(object)
    finished = Signal(object)


class _ImportTask(QRunnable):
    def __init__(
        self,
        application: StockToolboxApplication,
        raw_input: str,
    ) -> None:
        super().__init__()
        self.application = application
        self.raw_input = raw_input
        self.operation_id = str(uuid.uuid4())
        self.signals = _ImportSignals()

    @Slot()
    def run(self) -> None:
        try:
            result: object = self.application.import_securities(
                self.raw_input,
                operation_id=self.operation_id,
                progress=self.signals.progress.emit,
            )
        except RuntimeError as exception:
            result = exception
        self.signals.finished.emit(result)


class _SnapshotSignals(QObject):
    finished = Signal(object)


class _RefreshSignals(QObject):
    progress = Signal(object)
    finished = Signal(object)


class _RefreshTask(QRunnable):
    def __init__(
        self,
        application: StockToolboxApplication,
    ) -> None:
        super().__init__()
        self.application = application
        self.operation_id = str(uuid.uuid4())
        self.signals = _RefreshSignals()

    @Slot()
    def run(self) -> None:
        try:
            result: object = self.application.refresh_all_security_profiles(
                operation_id=self.operation_id,
                progress=self.signals.progress.emit,
            )
        except RuntimeError as error:
            result = error
        self.signals.finished.emit(result)


class _SnapshotTask(QRunnable):
    def __init__(
        self,
        application: StockToolboxApplication,
        security_id: str,
    ) -> None:
        super().__init__()
        self.application = application
        self.security_id = security_id
        self.signals = _SnapshotSignals()

    @Slot()
    def run(self) -> None:
        try:
            result: object = self.application.get_security_snapshot(
                self.security_id
            )
        except (PersistenceError, RuntimeError, ValueError) as exception:
            result = exception
        self.signals.finished.emit((self.security_id, result))


class MasterDataBridge(QObject):
    changed = Signal()
    import_changed = Signal()
    import_finished = Signal(object)
    snapshot_finished = Signal(object)
    refresh_changed = Signal()
    refresh_finished = Signal(object)

    def __init__(
        self,
        application: StockToolboxApplication,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._search = ""
        self._selected_classification_id = ""
        self._classification_batch_result: dict[str, object] = {}
        self._selected_watchlist_id = ""
        self._status = ""
        self._import_task: _ImportTask | None = None
        self._import_process: QProcess | None = None
        self._import_process_buffer = b""
        self._import_process_result: object | None = None
        self._import_operation_id = ""
        self._import_summary: dict[str, int] = {}
        self._import_details: list[dict[str, str]] = []
        self._import_completed = 0
        self._import_total = 0
        self._import_progress = 0.0
        self._import_file_preview: ImportInputPreview | None = None
        self._snapshot_task: _SnapshotTask | None = None
        self._security_snapshot: dict[str, str] = {}
        self._refresh_task: _RefreshTask | None = None
        self._refresh_progress = 0.0
        self._refresh_status = ""
        self._refresh_summary: dict[str, int] = {}
        self._refresh_details: list[dict[str, str]] = []
        self._securities_cache: tuple[Any, ...] = ()
        self._classifications_cache: tuple[Any, ...] = ()
        self._watchlists_cache: tuple[Any, ...] = ()
        self._reload_master_data()

    def _reload_master_data(self) -> None:
        self._securities_cache = tuple(
            self._application.master_data.list_securities()
        )
        self._classifications_cache = tuple(
            self._application.master_data.list_classifications()
        )
        self._watchlists_cache = tuple(
            self._application.master_data.list_watchlists()
        )

    @Property(list, notify=changed)
    def securities(self) -> list[dict[str, object]]:
        return self._security_rows(self._search)

    def _security_rows(self, search: str = "") -> list[dict[str, object]]:
        query = search.casefold().strip()
        rows: list[dict[str, object]] = []
        for security in self._securities_cache:
            display_symbol = security.canonical_symbol.removesuffix(".US")
            searchable = f"{display_symbol} {security.display_name}".casefold()
            if query and query not in searchable:
                continue
            company = security.business_profile.get("company", {})
            if not isinstance(company, dict):
                company = {}
            refresh = security.business_profile.get("refresh", {})
            if not isinstance(refresh, dict):
                refresh = {}
            classification_rows = [
                {
                    "bindingId": binding.id,
                    "id": binding.classification_id,
                    "name": _localized_classification_name(
                        binding.classification_name
                    ),
                }
                for binding in security.bindings
            ]
            rows.append(
                {
                    "id": security.id,
                    "symbol": security.canonical_symbol,
                    "displaySymbol": display_symbol,
                    "name": security.display_name,
                    "assetType": security.asset_type,
                    "assetTypeText": {
                        "COMMON_STOCK": "普通股",
                        "ADR": "美国存托凭证",
                    }.get(security.asset_type, security.asset_type),
                    "exchange": security.exchange or "",
                    "currency": security.currency or "",
                    "listingCountry": security.listing_country or "",
                    "founded": str(company.get("founded") or ""),
                    "employees": str(company.get("employees") or ""),
                    "website": str(company.get("website") or ""),
                    "sector": str(company.get("sector") or ""),
                    "category": str(company.get("category") or ""),
                    "description": security.description or "",
                    "availabilityStatus": str(
                        refresh.get("status") or "UNKNOWN"
                    ),
                    "refreshError": str(refresh.get("error") or ""),
                    "refreshedAt": str(refresh.get("checked_at") or ""),
                    "cachedLastPrice": _format_stored_price(
                        refresh.get("last_price")
                    ),
                    "cachedMarketValue": _format_stored_market_value(
                        refresh.get("market_value")
                    ),
                    "classifications": classification_rows,
                    "classificationText": " · ".join(
                        str(item["name"]) for item in classification_rows
                    )
                    or "待分类",
                }
            )
        for ordinal, row in enumerate(rows, start=1):
            row["rowNumber"] = ordinal
        return rows

    @Property(list, notify=changed)
    def classifications(self) -> list[dict[str, object]]:
        member_counts: dict[str, int] = {}
        for security in self._securities_cache:
            for binding in security.bindings:
                member_counts[binding.classification_id] = (
                    member_counts.get(binding.classification_id, 0) + 1
                )
        return [
            {
                "id": item.id,
                "name": item.display_name,
                "displayName": _localized_classification_name(
                    item.display_name
                ),
                "origin": item.origin,
                "aliases": list(item.aliases),
                "memberCount": member_counts.get(item.id, 0),
            }
            for item in self._classifications_cache
        ]

    @Property(list, notify=changed)
    def classification_members(self) -> list[dict[str, object]]:
        if not self._selected_classification_id:
            return []
        return [
            row
            for row in self._security_rows()
            if self._row_has_classification(
                row,
                self._selected_classification_id,
            )
        ]

    @Property(list, notify=changed)
    def classification_candidates(self) -> list[dict[str, object]]:
        if not self._selected_classification_id:
            return []
        return [
            {
                **row,
                "classificationCount": len(
                    cast(list[dict[str, object]], row["classifications"])
                ),
            }
            for row in self._security_rows()
            if not self._row_has_classification(
                row,
                self._selected_classification_id,
            )
        ]

    @staticmethod
    def _row_has_classification(
        row: dict[str, object],
        classification_id: str,
    ) -> bool:
        classifications = cast(
            list[dict[str, object]],
            row["classifications"],
        )
        return any(item["id"] == classification_id for item in classifications)

    @Property(dict, notify=changed)
    def classification_batch_result(self) -> dict[str, object]:
        return dict(self._classification_batch_result)

    @Property(list, notify=changed)
    def watchlists(self) -> list[dict[str, object]]:
        return [
            {
                "id": item.id,
                "name": item.display_name,
                "memberCount": len(item.memberships),
            }
            for item in self._watchlists_cache
        ]

    @Property(str, notify=changed)
    def selected_watchlist_id(self) -> str:
        return self._selected_watchlist_id

    @Property(list, notify=changed)
    def selected_watchlist_members(self) -> list[dict[str, object]]:
        if not self._selected_watchlist_id:
            return []
        watchlist = next(
            (
                item
                for item in self._watchlists_cache
                if item.id == self._selected_watchlist_id
            ),
            None,
        )
        if watchlist is None:
            return []
        securities = {
            item.id: item
            for item in self._securities_cache
        }
        return [
            {
                "id": item.id,
                "securityId": item.security_id,
                "symbol": item.canonical_symbol,
                "displaySymbol": item.canonical_symbol.removesuffix(".US"),
                "name": item.company_name,
                "classification": _localized_classification_name(
                    item.participating_classification_name
                ),
                "bindingId": item.participating_binding_id,
                "bindings": [
                    {
                        "bindingId": binding.id,
                        "name": _localized_classification_name(
                            binding.classification_name
                        ),
                    }
                    for binding in securities[item.security_id].bindings
                ],
            }
            for item in watchlist.memberships
        ]

    @Property(list, notify=changed)
    def watchlist_candidates(self) -> list[dict[str, object]]:
        if not self._selected_watchlist_id:
            return []
        watchlist = next(
            (
                item
                for item in self._watchlists_cache
                if item.id == self._selected_watchlist_id
            ),
            None,
        )
        if watchlist is None:
            return []
        existing = {item.security_id for item in watchlist.memberships}
        return [
            row for row in self._security_rows() if row["id"] not in existing
        ]

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=import_changed)
    def import_running(self) -> bool:
        return self._import_task is not None or self._import_process is not None

    @Property(str, notify=import_changed)
    def import_status(self) -> str:
        return self._status

    @Property(dict, notify=import_changed)
    def import_summary(self) -> dict[str, int]:
        return dict(self._import_summary)

    @Property(list, notify=import_changed)
    def import_details(self) -> list[dict[str, str]]:
        return list(self._import_details)

    @Property(int, notify=import_changed)
    def import_completed(self) -> int:
        return self._import_completed

    @Property(int, notify=import_changed)
    def import_total(self) -> int:
        return self._import_total

    @Property(float, notify=import_changed)
    def import_progress(self) -> float:
        return self._import_progress

    @Property(list, notify=import_changed)
    def import_file_candidates(self) -> list[dict[str, object]]:
        preview = self._import_file_preview
        if preview is None:
            return []
        return [
            {
                "index": item.index,
                "name": item.name,
                "samples": list(item.samples),
                "validCount": item.valid_count,
                "score": item.score,
                "selected": preview.selected_index == item.index,
            }
            for item in preview.candidates
        ]

    @Property(bool, notify=import_changed)
    def import_file_requires_choice(self) -> bool:
        return bool(
            self._import_file_preview
            and self._import_file_preview.requires_column_choice
        )

    @Property(dict, notify=import_changed)
    def import_preview(self) -> dict[str, object]:
        preview = self._import_file_preview
        if preview is None:
            return {}
        return {
            "column": preview.selected_column or "",
            "rows": preview.row_count,
            "recognized": len(preview.symbols),
            "duplicates": preview.duplicate_count,
            "invalid": preview.invalid_count,
        }

    @Property(str, notify=import_changed)
    def import_file_text(self) -> str:
        preview = self._import_file_preview
        return "\n".join(preview.symbols) if preview is not None else ""

    @Property(bool, notify=changed)
    def snapshot_running(self) -> bool:
        return self._snapshot_task is not None

    @Property(dict, notify=changed)
    def security_snapshot(self) -> dict[str, str]:
        return dict(self._security_snapshot)

    @Property(bool, notify=refresh_changed)
    def refresh_running(self) -> bool:
        return self._refresh_task is not None

    @Property(float, notify=refresh_changed)
    def refresh_progress(self) -> float:
        return self._refresh_progress

    @Property(str, notify=refresh_changed)
    def refresh_status(self) -> str:
        return self._refresh_status

    @Property(dict, notify=refresh_changed)
    def refresh_summary(self) -> dict[str, int]:
        return dict(self._refresh_summary)

    @Property(list, notify=refresh_changed)
    def refresh_details(self) -> list[dict[str, str]]:
        return list(self._refresh_details)

    @Slot(str)
    def set_search(self, query: str) -> None:
        if query != self._search:
            self._search = query
            self.changed.emit()

    @Slot(str, result=str)
    def read_import_file(self, target: str) -> str:
        local_target = QUrl(target).toLocalFile() if target.startswith("file:") else target
        try:
            preview = parse_import_file(
                Path(local_target).read_bytes(),
            )
        except OSError:
            self._import_file_preview = None
            self._status = "文件读取失败，请检查权限。"
            self.import_changed.emit()
            self.changed.emit()
            return ""
        except ImportInputError as error:
            self._import_file_preview = None
            self._status = _import_file_error(str(error))
            self.import_changed.emit()
            self.changed.emit()
            return ""
        self._import_file_preview = preview
        self._status = (
            f"已读取 {Path(local_target).name}，请选择证券代码列。"
            if preview.requires_column_choice
            else (
                f"已识别 {preview.selected_column} · "
                f"{len(preview.symbols)} 个代码，等待导入。"
            )
        )
        self.import_changed.emit()
        self.changed.emit()
        return "\n".join(preview.symbols)

    @Slot(int, result=bool)
    def select_import_column(self, index: int) -> bool:
        preview = self._import_file_preview
        if preview is None:
            return False
        try:
            self._import_file_preview = select_import_column(preview, index)
        except ImportInputError:
            return False
        selected = self._import_file_preview
        self._status = (
            f"已选择 {selected.selected_column} · "
            f"{len(selected.symbols)} 个代码，等待导入。"
        )
        self.import_changed.emit()
        self.changed.emit()
        return True

    @Slot(result=bool)
    def reset_import_session(self) -> bool:
        """Clear the transient import draft after the user finishes reviewing it."""
        if self.import_running:
            return False
        self._import_summary = {}
        self._import_details = []
        self._import_completed = 0
        self._import_total = 0
        self._import_progress = 0.0
        self._import_file_preview = None
        self._status = ""
        self.import_changed.emit()
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def import_securities(self, raw_input: str) -> bool:
        if self.import_running or not raw_input.strip():
            return False
        self._import_operation_id = str(uuid.uuid4())
        self._import_summary = {}
        self._import_details = []
        self._import_total = len(
            [
                token
                for token in re.split(r"[\s,;]+", raw_input.strip())
                if token
                and token.casefold()
                not in {"ticker", "tickers", "symbol", "symbols"}
            ]
        )
        self._import_completed = 0
        self._import_progress = 0.0
        self._status = "正在解析并验证证券…"
        program = self._import_worker_program()
        if program is None:
            task = _ImportTask(self._application, raw_input)
            self._import_task = task
            self._import_operation_id = task.operation_id
            task.signals.progress.connect(self._on_import_progress)
            task.signals.finished.connect(self._on_import_finished)
        else:
            process = QProcess(self)
            process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
            process.readyReadStandardOutput.connect(
                self._on_import_process_output
            )
            process.finished.connect(self._on_import_process_finished)
            process.errorOccurred.connect(self._on_import_process_error)
            process.started.connect(
                lambda: self._write_import_process_input(raw_input)
            )
            self._import_process = process
            self._import_process_buffer = b""
            self._import_process_result = None
            self._application.registry.reserve(
                self._import_operation_id,
                str(uuid.uuid4()),
                "security_import_process",
            )
            self._application.registry.begin_reserved(
                self._import_operation_id
            )
        self.import_changed.emit()
        if self._import_task is not None:
            QThreadPool.globalInstance().start(self._import_task)
        else:
            assert self._import_process is not None
            self._import_process.start(
                str(program),
                self._import_worker_arguments(),
            )
        return True

    def _import_worker_program(self) -> Path | None:
        if self._application.paths.environment not in {
            RuntimeEnvironment.PRODUCTION,
            RuntimeEnvironment.DEVELOPMENT,
        }:
            return None
        candidate = Path(QCoreApplication.applicationDirPath()) / "stock-toolbox"
        return candidate if candidate.is_file() else None

    def _import_worker_arguments(self) -> list[str]:
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
            "securities",
            "import-worker",
        ]

    def _write_import_process_input(self, raw_input: str) -> None:
        process = self._import_process
        if process is None:
            return
        process.write(raw_input.encode("utf-8"))
        process.closeWriteChannel()

    @Slot(result=bool)
    def refresh_securities(self) -> bool:
        if self._refresh_task is not None:
            return False
        task = _RefreshTask(self._application)
        self._refresh_task = task
        self._refresh_progress = 0.02
        self._refresh_status = "准备更新全局证券资料…"
        self._refresh_summary = {}
        self._refresh_details = []
        task.signals.progress.connect(self._on_refresh_progress)
        task.signals.finished.connect(self._on_refresh_finished)
        self.refresh_changed.emit()
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(result=bool)
    def cancel_import(self) -> bool:
        if self._import_process is not None:
            process = self._import_process
            self._application.registry.cancel(self._import_operation_id)
            process.terminate()
            QTimer.singleShot(1_500, self._kill_import_process)
            self._status = "正在取消 · 本批不会留下半成品"
            self.import_changed.emit()
            return True
        if self._import_task is None:
            return False
        accepted = self._application.cancel_operation(
            self._import_task.operation_id
        ).value == "ACCEPTED"
        if accepted:
            self._status = "正在取消 · 本批不会留下半成品"
            self.import_changed.emit()
        return accepted

    def _kill_import_process(self) -> None:
        process = self._import_process
        if process is not None and process.state() is not QProcess.ProcessState.NotRunning:
            process.kill()

    @Slot(str, result=bool)
    def create_classification(self, name: str) -> bool:
        try:
            self._application.master_data.create_classification(name)
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "分类创建失败，请检查名称是否重复。"
            self.changed.emit()
            return False
        self._status = "分类已创建。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot(str)
    def select_classification(self, classification_id: str) -> None:
        self._selected_classification_id = classification_id
        self._classification_batch_result = {}
        self._status = ""
        self.changed.emit()

    @Slot(str, list, result="QVariantMap")
    def add_classification_members(
        self,
        classification_id: str,
        security_ids: list[object],
    ) -> dict[str, object]:
        summary = {"added": 0, "existing": 0, "failed": 0}
        details: list[dict[str, str]] = []
        for security_id in dict.fromkeys(str(item) for item in security_ids):
            try:
                security = self._application.master_data.get_security(security_id)
            except (KeyError, PersistenceError, RuntimeError, ValueError):
                summary["failed"] += 1
                details.append(
                    {
                        "securityId": security_id,
                        "symbol": "",
                        "name": "",
                        "category": "failed",
                        "reason": "证券不存在或数据已经变化",
                    }
                )
                continue
            row = {
                "securityId": security.id,
                "symbol": security.canonical_symbol.removesuffix(".US"),
                "name": security.display_name,
            }
            classification_ids = [
                binding.classification_id for binding in security.bindings
            ]
            if classification_id in classification_ids:
                summary["existing"] += 1
                details.append(
                    {
                        **row,
                        "category": "existing",
                        "reason": "已经绑定该标签",
                    }
                )
                continue
            if len(classification_ids) >= 3:
                summary["failed"] += 1
                details.append(
                    {
                        **row,
                        "category": "failed",
                        "reason": "已有 3 个标签，达到上限",
                    }
                )
                continue
            try:
                self._application.master_data.set_security_classifications(
                    security.id,
                    (*classification_ids, classification_id),
                )
            except (PersistenceError, RuntimeError, ValueError):
                summary["failed"] += 1
                details.append(
                    {
                        **row,
                        "category": "failed",
                        "reason": "添加失败，证券数据可能已变化",
                    }
                )
                continue
            summary["added"] += 1
            details.append(
                {
                    **row,
                    "category": "added",
                    "reason": "添加成功",
                }
            )
        self._selected_classification_id = classification_id
        self._classification_batch_result = {
            "summary": summary,
            "details": details,
        }
        self._status = (
            f"批量添加完成 · 成功 {summary['added']} · "
            f"已存在 {summary['existing']} · 失败 {summary['failed']}"
        )
        self._reload_master_data()
        self.changed.emit()
        return dict(self._classification_batch_result)

    @Slot(str, str, result=bool)
    def rename_classification(
        self,
        classification_id: str,
        name: str,
    ) -> bool:
        try:
            self._application.master_data.rename_classification(
                classification_id,
                name,
            )
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "分类重命名失败，请检查名称是否重复。"
            self.changed.emit()
            return False
        self._status = "分类已重命名。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def delete_classification(self, classification_id: str) -> bool:
        try:
            self._application.master_data.delete_classification(
                classification_id
            )
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "分类仍被证券引用，暂时不能删除。"
            self.changed.emit()
            return False
        self._status = "分类已删除。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot(str, list, result=bool)
    def set_security_classifications(
        self,
        security_id: str,
        classification_ids: list[object],
    ) -> bool:
        normalized = tuple(str(item) for item in classification_ids)
        try:
            self._application.master_data.set_security_classifications(
                security_id,
                normalized,
            )
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "分类绑定失败；最多三个，且参评中的绑定不能直接删除。"
            self.changed.emit()
            return False
        self._status = "证券分类已更新。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot(str, str, result="QVariantMap")
    def security_classification_removal_impact(
        self,
        security_id: str,
        classification_id: str,
    ) -> dict[str, object]:
        try:
            security = self._application.master_data.get_security(security_id)
        except (KeyError, PersistenceError, RuntimeError, ValueError):
            return {}
        binding = next(
            (
                item
                for item in security.bindings
                if item.classification_id == classification_id
            ),
            None,
        )
        if binding is None:
            return {}
        remaining = tuple(
            item for item in security.bindings if item.id != binding.id
        )
        watchlist_names = self._application.master_data.binding_watchlist_names(
            binding.id
        )
        return {
            "securityId": security.id,
            "symbol": security.canonical_symbol.removesuffix(".US"),
            "name": security.display_name,
            "classificationId": binding.classification_id,
            "classificationName": _localized_classification_name(
                binding.classification_name
            ),
            "watchlistCount": len(watchlist_names),
            "watchlistNames": list(watchlist_names),
            "replacementName": (
                _localized_classification_name(
                    remaining[0].classification_name
                )
                if remaining
                else ""
            ),
        }

    @Slot(str, str, result=bool)
    def remove_security_classification(
        self,
        security_id: str,
        classification_id: str,
    ) -> bool:
        try:
            security = self._application.master_data.get_security(security_id)
            classification_ids = tuple(
                binding.classification_id
                for binding in security.bindings
                if binding.classification_id != classification_id
            )
            if len(classification_ids) == len(security.bindings):
                raise ValueError("classification_binding_missing")
            self._application.master_data.set_security_classifications(
                security_id,
                classification_ids,
            )
        except (KeyError, PersistenceError, RuntimeError, ValueError):
            self._status = "标签移除失败，证券或股票池数据可能已变化。"
            self.changed.emit()
            return False
        self._status = "标签已移除；相关股票池已按剩余标签同步。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def delete_security(self, security_id: str) -> bool:
        try:
            self._application.master_data.delete_security(security_id)
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "证券删除失败，数据可能已经变化。"
            self.changed.emit()
            return False
        self._status = "证券及其股票池成员关系已删除。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot(str, result="QVariantMap")
    def security_delete_impact(self, security_id: str) -> dict[str, object]:
        try:
            security = self._application.master_data.get_security(security_id)
        except (PersistenceError, RuntimeError, ValueError):
            return {"watchlistCount": 0, "symbol": "", "name": ""}
        return {
            "watchlistCount": self._application.master_data.security_watchlist_count(
                security_id
            ),
            "symbol": security.canonical_symbol.removesuffix(".US"),
            "name": security.display_name,
        }

    @Slot(str, result=bool)
    def load_security_snapshot(self, security_id: str) -> bool:
        if self._snapshot_task is not None or not security_id:
            return False
        self._security_snapshot = {"securityId": security_id}
        task = _SnapshotTask(self._application, security_id)
        self._snapshot_task = task
        task.signals.finished.connect(self._on_snapshot_finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(task)
        return True

    @Slot(str, result=str)
    def create_watchlist(self, name: str) -> str:
        try:
            watchlist = self._application.master_data.create_watchlist(name)
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "股票池创建失败，请检查名称。"
            self.changed.emit()
            return ""
        self._selected_watchlist_id = watchlist.id
        self._status = "股票池已创建。"
        self._reload_master_data()
        self.changed.emit()
        return watchlist.id

    @Slot(str)
    def select_watchlist(self, watchlist_id: str) -> None:
        self._selected_watchlist_id = watchlist_id
        self._status = ""
        self.changed.emit()

    @Slot(str, str, result=bool)
    def rename_watchlist(self, watchlist_id: str, name: str) -> bool:
        try:
            self._application.master_data.rename_watchlist(
                watchlist_id,
                name,
            )
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "股票池重命名失败，请检查名称。"
            self.changed.emit()
            return False
        self._status = "股票池已重命名。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def delete_watchlist(self, watchlist_id: str) -> bool:
        try:
            self._application.master_data.delete_watchlist(watchlist_id)
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "股票池删除失败，数据可能已经变化。"
            self.changed.emit()
            return False
        if self._selected_watchlist_id == watchlist_id:
            self._selected_watchlist_id = ""
        self._status = "股票池已删除。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot(str, list, result="QVariantMap")
    def add_watchlist_members_batch(
        self,
        watchlist_id: str,
        raw_selections: list[object],
    ) -> dict[str, int]:
        try:
            watchlist = self._application.master_data.get_watchlist(watchlist_id)
        except (KeyError, PersistenceError, RuntimeError, ValueError):
            self._status = "股票池不存在或数据已经变化。"
            self.changed.emit()
            return {"added": 0}
        existing = {item.security_id for item in watchlist.memberships}
        selections: dict[str, str] = {}
        for raw in raw_selections:
            if not isinstance(raw, dict):
                continue
            security_id = str(raw.get("securityId", ""))
            binding_id = str(raw.get("bindingId", ""))
            if security_id and binding_id and security_id not in existing:
                selections[security_id] = binding_id
        if not selections:
            self._status = "没有可添加的证券。"
            self.changed.emit()
            return {"added": 0}
        try:
            self._application.master_data.add_watchlist_members(
                watchlist_id,
                tuple(selections.items()),
            )
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "批量添加失败，请检查证券与参评标签。"
            self.changed.emit()
            return {"added": 0}
        self._selected_watchlist_id = watchlist_id
        self._status = f"已添加 {len(selections)} 只证券。"
        self._reload_master_data()
        self.changed.emit()
        return {"added": len(selections)}

    @Slot(str, str, str, result=bool)
    def update_watchlist_member_binding(
        self,
        watchlist_id: str,
        security_id: str,
        binding_id: str,
    ) -> bool:
        try:
            self._application.master_data.set_watchlist_member_binding(
                watchlist_id,
                security_id,
                binding_id,
            )
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "参评标签更新失败，数据可能已经变化。"
            self.changed.emit()
            return False
        self._status = "参评标签已更新。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot(str, str, result=bool)
    def remove_watchlist_member(
        self,
        watchlist_id: str,
        security_id: str,
    ) -> bool:
        try:
            self._application.master_data.remove_watchlist_members(
                watchlist_id,
                (security_id,),
            )
        except (PersistenceError, RuntimeError, ValueError):
            self._status = "移除失败，股票池可能已经变化。"
            self.changed.emit()
            return False
        self._status = "成员已从股票池移除。"
        self._reload_master_data()
        self.changed.emit()
        return True

    @Slot()
    def _on_import_process_output(self) -> None:
        process = self._import_process
        if process is None:
            return
        self._import_process_buffer += process.readAllStandardOutput().data()
        while b"\n" in self._import_process_buffer:
            raw_line, self._import_process_buffer = (
                self._import_process_buffer.split(b"\n", 1)
            )
            self._consume_import_process_line(raw_line)

    def _consume_import_process_line(self, raw_line: bytes) -> None:
        try:
            payload = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("type", ""))
        if event_type == "progress":
            self._on_import_progress(
                ImportProgress(
                    str(payload.get("stage", "")),
                    int(payload.get("completed", 0)),
                    int(payload.get("total", 0)),
                    str(payload.get("symbol", "")),
                    str(payload.get("status", "")),
                    str(payload.get("reason", "")),
                )
            )
            return
        if event_type == "result":
            try:
                items = tuple(
                    ImportItemResult(
                        str(item["symbol"]),
                        ImportStatus(str(item["status"])),
                        str(item.get("reason", "")) or None,
                    )
                    for item in payload.get("items", [])
                    if isinstance(item, dict)
                )
                duplicates = tuple(
                    str(item) for item in payload.get("duplicates", [])
                )
                self._import_process_result = ImportResult(
                    items,
                    duplicates,
                    bool(payload.get("committed", False)),
                )
            except (KeyError, TypeError, ValueError):
                self._import_process_result = RuntimeError(
                    "invalid_import_worker_result"
                )
            return
        if event_type == "error":
            self._import_process_result = RuntimeError(
                str(payload.get("code", "security_import_worker_failed"))
            )

    @Slot(int, object)
    def _on_import_process_finished(
        self,
        exit_code: int,
        _exit_status: object,
    ) -> None:
        process = self._import_process
        if process is None:
            return
        self._on_import_process_output()
        if self._import_process_buffer.strip():
            self._consume_import_process_line(
                self._import_process_buffer.strip()
            )
        result = self._import_process_result
        self._import_process = None
        self._import_process_buffer = b""
        self._import_process_result = None
        if isinstance(result, ImportResult) and exit_code == 0:
            self._application.registry.try_complete(
                self._import_operation_id,
                OperationStatus.SUCCEEDED,
                {"success_count": result.success_count},
            )
        else:
            self._application.registry.try_complete(
                self._import_operation_id,
                OperationStatus.FAILED,
                {"code": "security_import_worker_failed"},
            )
        process.deleteLater()
        self._on_import_finished(
            result
            if isinstance(result, ImportResult)
            else RuntimeError("security_import_worker_failed")
        )

    @Slot(object)
    def _on_import_process_error(self, _error: object) -> None:
        process = self._import_process
        if process is None or process.state() is not QProcess.ProcessState.NotRunning:
            return
        self._import_process = None
        self._application.registry.try_complete(
            self._import_operation_id,
            OperationStatus.FAILED,
            {"code": "security_import_worker_start_failed"},
        )
        process.deleteLater()
        self._on_import_finished(RuntimeError("security_import_worker_start_failed"))

    @Slot(object)
    def _on_import_progress(self, raw: object) -> None:
        if not isinstance(raw, ImportProgress):
            return
        if self._import_operation_id:
            emit_progress(
                self._application.diagnostics,
                module="securities",
                task_id=self._import_operation_id,
                stage=raw.stage,
                completed=raw.completed,
                total=raw.total,
                ticker=raw.symbol,
            )
        labels = {
            "PARSING": "正在解析输入",
            "FETCHING_PROFILES": "正在获取公司资料",
            "CLASSIFYING": "正在校验并分类",
            "ITEM": "正在逐项处理",
            "SAVING": "正在保存",
            "DONE": "导入完成",
        }
        self._import_total = raw.total
        self._import_completed = raw.completed
        weighted = _weighted_import_progress(
            raw.stage,
            raw.completed,
            raw.total,
        )
        self._import_progress = max(self._import_progress, weighted)
        if raw.symbol:
            category = _import_category(raw.status)
            self._import_details.append(
                {
                    "symbol": raw.symbol.removesuffix(".US"),
                    "status": raw.status,
                    "reason": _reason_label(raw.reason),
                    "category": category,
                }
            )
            if category:
                self._import_summary[category] = (
                    self._import_summary.get(category, 0) + 1
                )
        label = labels.get(raw.stage, raw.stage)
        self._status = f"{label} · {self._import_completed}/{self._import_total}"
        self.import_changed.emit()

    @Slot(object)
    def _on_import_finished(self, raw: object) -> None:
        self._import_task = None
        self._import_operation_id = ""
        if not isinstance(raw, ImportResult):
            self._status = "导入已取消或失败 · 未保存半成品"
            self.import_changed.emit()
            self.import_finished.emit(raw)
            return
        self._import_summary = {
            "success": raw.success_count,
            "existing": len(raw.existing_symbols),
            "duplicate": len(raw.duplicate_input_symbols),
            "unavailable": len(raw.unavailable),
            "excluded": len(raw.excluded),
            "invalid": len(raw.invalid_inputs),
        }
        self._import_details = [
            {
                "symbol": item.symbol.removesuffix(".US"),
                "status": item.status.value,
                "reason": _reason_label(item.reason or ""),
                "category": _import_category(item.status.value),
            }
            for item in raw.items
        ]
        self._import_details.extend(
            {
                "symbol": symbol.removesuffix(".US"),
                "status": "DUPLICATE",
                "reason": "本批只处理首次出现项",
                "category": "duplicate",
            }
            for symbol in raw.duplicate_input_symbols
        )
        self._status = (
            f"导入完成 · 成功 {raw.success_count} · "
            f"已存在 {len(raw.existing_symbols)} · "
            f"失败 {len(raw.unavailable) + len(raw.excluded) + len(raw.invalid_inputs)}"
        )
        self._import_total = sum(self._import_summary.values())
        self._import_completed = self._import_total
        self._import_progress = 1.0
        self._reload_master_data()
        self.import_changed.emit()
        self.changed.emit()
        self.import_finished.emit(raw)

    @Slot(object)
    def _on_snapshot_finished(self, raw: object) -> None:
        from stock_toolbox.core.market_data.models import SecuritySnapshot

        self._snapshot_task = None
        security_id = ""
        snapshot: object = None
        if isinstance(raw, tuple) and len(raw) == 2:
            security_id = str(raw[0])
            snapshot = raw[1]
        if isinstance(snapshot, SecuritySnapshot):
            self._security_snapshot = {
                "securityId": security_id,
                "lastPrice": _format_price(snapshot.last_price),
                "marketValue": _format_market_value(
                    snapshot.total_market_value
                ),
                "status": "ready",
            }
        else:
            self._security_snapshot = {
                "securityId": security_id,
                "lastPrice": "暂不可用",
                "marketValue": "暂不可用",
                "status": "unavailable",
            }
        self.changed.emit()
        self.snapshot_finished.emit(raw)

    @Slot(object)
    def _on_refresh_progress(self, raw: object) -> None:
        if not isinstance(raw, SecurityRefreshProgress):
            return
        if self._refresh_task is not None:
            emit_progress(
                self._application.diagnostics,
                module="securities",
                task_id=self._refresh_task.operation_id,
                stage=raw.stage,
                completed=raw.completed,
                total=raw.total,
                ticker=raw.symbol,
            )
        fraction = raw.completed / raw.total if raw.total else 0.0
        self._refresh_progress = max(
            self._refresh_progress,
            min(0.98, fraction),
        )
        self._refresh_status = (
            "正在从供应商拉取基础资料与行情…"
            if raw.stage == "FETCHING"
            else (
                f"正在更新 {raw.symbol.removesuffix('.US')}…"
                if raw.symbol
                else "正在写入本地资料…"
            )
        )
        if raw.symbol:
            self._refresh_details.append(
                {
                    "symbol": raw.symbol.removesuffix(".US"),
                    "status": raw.status,
                }
            )
        self.refresh_changed.emit()

    @Slot(object)
    def _on_refresh_finished(self, raw: object) -> None:
        self._refresh_task = None
        self._refresh_progress = 1.0
        if isinstance(raw, SecurityRefreshResult):
            self._refresh_summary = {
                "updated": raw.updated_count,
                "unavailable": raw.unavailable_count,
                "failed": raw.failed_count,
            }
            self._refresh_status = (
                f"更新完成 · 有效 {raw.updated_count} · "
                f"不可用 {raw.unavailable_count} · "
                f"检查失败 {raw.failed_count}"
            )
        else:
            self._refresh_summary = {
                "updated": 0,
                "unavailable": 0,
                "failed": 1,
            }
            self._refresh_status = "更新失败，请检查供应商连接后重试。"
        self._reload_master_data()
        self.refresh_changed.emit()
        self.changed.emit()
        self.refresh_finished.emit(raw)


def _weighted_import_progress(
    stage: str,
    completed: int,
    total: int,
) -> float:
    fraction = min(1.0, max(0.0, completed / total)) if total else 0.0
    if stage == "PARSING":
        return 0.04
    if stage == "FETCHING_PROFILES":
        return 0.18
    if stage == "CLASSIFYING":
        return 0.28
    if stage == "ITEM":
        return 0.28 + fraction * 0.64
    if stage == "SAVING":
        return 0.96
    if stage == "DONE":
        return 1.0
    return fraction


def _import_category(status: str) -> str:
    return {
        "IMPORTED": "success",
        "IMPORTED_PENDING_CLASSIFICATION": "success",
        "EXISTING": "existing",
        "INVALID_INPUT": "invalid",
        "UNAVAILABLE": "unavailable",
        "FAILED": "unavailable",
        "EXCLUDED": "excluded",
        "DUPLICATE": "duplicate",
    }.get(status, "")


def _import_file_error(code: str) -> str:
    return {
        "file_too_large": "文件超过 10 MiB，请拆分后重试。",
        "too_many_rows": "文件超过 10 万行，请拆分后重试。",
        "too_many_columns": "文件列数过多，无法安全预览。",
        "unsupported_encoding": "无法识别文件编码，请另存为 UTF-8 或 GB18030。",
        "file_empty": "文件中没有可导入的数据。",
        "symbol_column_not_found": "没有找到可识别的证券代码列。",
    }.get(code, "文件解析失败，请检查 CSV 结构。")


def _localized_classification_name(name: str) -> str:
    return _PROJECTION_CLASSIFICATION_NAMES.get(name.strip().casefold(), name)


_PROJECTION_CLASSIFICATION_NAMES = {
    "technology": "科技",
    "semiconductors": "半导体",
    "semiconductor": "半导体",
    "software": "软件",
    "cloud computing": "云计算",
    "ai data center": "AI 数据中心",
    "bitcoin mining": "比特币矿业",
    "energy infrastructure": "能源基础设施",
}


def _format_price(value: Decimal | None) -> str:
    return f"${value:,.2f}" if value is not None else "暂不可用"


def _format_market_value(value: Decimal | None) -> str:
    if value is None:
        return "暂不可用"
    if value >= Decimal(1_000_000_000_000):
        return f"${value / Decimal(1_000_000_000_000):.2f} 万亿"
    if value >= Decimal(100_000_000):
        return f"${value / Decimal(100_000_000):.1f} 亿"
    if value >= Decimal(10_000):
        return f"${value / Decimal(10_000):.1f} 万"
    return f"${value:,.0f}"


def _stored_decimal(value: object) -> Decimal | None:
    try:
        return (
            Decimal(str(value))
            if value is not None and value != ""
            else None
        )
    except (InvalidOperation, TypeError, ValueError):
        return None


def _format_stored_price(value: object) -> str:
    parsed = _stored_decimal(value)
    return _format_price(parsed) if parsed is not None else ""


def _format_stored_market_value(value: object) -> str:
    parsed = _stored_decimal(value)
    return _format_market_value(parsed) if parsed is not None else ""


def _reason_label(code: str) -> str:
    return {
        "": "",
        "invalid_symbol": "代码格式无效",
        "symbol_unavailable": "供应商没有返回该证券",
        "provider_incomplete": "供应商返回的基础资料不完整",
        "eligibility_unresolved": "无法确认是否为美股正股",
        "commit_canceled_or_failed": "保存被取消或失败",
        "LEVERAGED_ETF": "杠杆 ETF，不属于美股正股",
        "INVERSE_ETF": "反向 ETF，不属于美股正股",
        "ETF": "ETF，不属于美股正股",
        "REIT": "REIT，不属于当前支持范围",
    }.get(code, code)
