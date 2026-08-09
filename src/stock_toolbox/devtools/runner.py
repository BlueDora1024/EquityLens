from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

from stock_toolbox.analyses.rs_strength.application.models import RunRequest
from stock_toolbox.composition import build_application
from stock_toolbox.core.operations.storage_guard import (
    CacheCleanupResult,
    StorageGuard,
)
from stock_toolbox.devtools.rs_benchmark import (
    CLASSIFICATION_COUNT,
    MEMBER_COUNT,
    run_frozen_benchmark,
)
from stock_toolbox.devtools.scenario import ScenarioDocument
from stock_toolbox.infrastructure.ai.openai_compatible import AIAdapterError
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.types import canonical_json
from stock_toolbox.infrastructure.virtual.provider import (
    VirtualProvider,
    VirtualProviderFault,
)
from stock_toolbox.runtime.environment import RuntimeEnvironment

_ALLOWED_ENVIRONMENTS = frozenset(
    {
        RuntimeEnvironment.DEVELOPMENT,
        RuntimeEnvironment.INTEGRATION,
        RuntimeEnvironment.SCENARIO,
    }
)


class _BusyOnHistoryConnection(sqlite3.Connection):
    busy_callback: Any = lambda: None
    write_callback: Any = lambda: None

    def execute(
        self,
        sql: str,
        parameters: Any = (),
    ) -> sqlite3.Cursor:
        normalized = sql.lstrip().upper()
        if normalized.startswith("INSERT INTO ANALYSIS_RUNS"):
            self.busy_callback()
            raise sqlite3.OperationalError("database is locked")
        cursor = super().execute(sql, parameters)
        if normalized.startswith("INSERT INTO RUN_SNAPSHOTS"):
            self.write_callback()
        return cursor


class _BusyOnHistoryFactory(SQLiteConnectionFactory):
    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self.failure_count = 0
        self.writes_before_fault = 0

    def open_writer(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            isolation_level=None,
            timeout=0,
            factory=_BusyOnHistoryConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 0")
        assert isinstance(connection, _BusyOnHistoryConnection)
        connection.busy_callback = self._record_failure
        connection.write_callback = self._record_write
        return connection

    def _record_failure(self) -> None:
        self.failure_count += 1

    def _record_write(self) -> None:
        self.writes_before_fault += 1


class _NoopCleaner:
    def clear_recomputable(self) -> CacheCleanupResult:
        return CacheCleanupResult()


class _DiskUsage:
    free = 0


class _ScriptedReport:
    model = "virtual-failure-report"

    def __init__(self, failure_code: str) -> None:
        self.failure_code = failure_code
        self.call_count = 0

    def generate(
        self,
        system_prompt: str,
        user_payload: dict[str, object],
        *,
        operation_control: object | None = None,
    ) -> str:
        del system_prompt, user_payload, operation_control
        self.call_count += 1
        if self.call_count == 1:
            return "已保存的稳定旧报告。"
        raise AIAdapterError(self.failure_code)


class ScenarioRunner:
    def validate_environment(self, environment: RuntimeEnvironment) -> None:
        if environment not in _ALLOWED_ENVIRONMENTS:
            raise PermissionError("scenario execution is forbidden in production")

    def verify_provider_call_budget(
        self,
        scenario: ScenarioDocument,
        *,
        actual_calls: int,
    ) -> None:
        limit = scenario.max_provider_calls
        if limit is not None and actual_calls > limit:
            raise ValueError(
                f"scenario provider call budget exceeded: {actual_calls}>{limit}"
            )

    def run(
        self,
        scenario: ScenarioDocument,
        *,
        home: Path,
    ) -> dict[str, Any]:
        run_id = f"{scenario.id}-{uuid.uuid4().hex}"
        bar_errors = {
            "virtual-partial-member-v1": {
                "AMD.US": "provider_error",
            },
            "virtual-benchmark-failure-v1": {
                "SPY.US": "provider_error",
            },
        }.get(scenario.provider_fixture)
        provider_faults = tuple(
            VirtualProviderFault(
                fault.target,
                fault.events,
                fault.symbol,
                fault.start_index,
            )
            for fault in scenario.fault_plan
            if fault.target == "daily"
        )
        provider = VirtualProvider(
            bar_errors=bar_errors,
            fault_plan=provider_faults,
        )
        report_fault = next(
            (
                fault
                for fault in scenario.fault_plan
                if fault.target == "ai_report"
            ),
            None,
        )
        report = (
            _ScriptedReport(
                report_fault.events[0]
                if report_fault is not None and report_fault.events
                else "service_unavailable"
            )
            if report_fault is not None
            else None
        )
        application = build_application(
            RuntimeEnvironment.SCENARIO,
            home=home,
            scenario_run_id=run_id,
            provider_override=provider,
            rs_report_override=report,
        )
        if any(
            fault.target == "storage"
            for fault in scenario.fault_plan
        ):
            application._storage_guard = StorageGuard(
                application.paths.data_root,
                _NoopCleaner(),
                disk_usage=lambda _path: _DiskUsage(),
            )
        busy_factory: _BusyOnHistoryFactory | None = None
        if any(
            fault.target == "database_save"
            for fault in scenario.fault_plan
        ):
            busy_factory = _BusyOnHistoryFactory(
                application.paths.database
            )
            application.factory = busy_factory
        history_count_before = len(application.list_history())
        summary: dict[str, Any] = {
            "id": scenario.id,
            "terminal": "succeeded",
            "security_count": 0,
            "excluded_count": 0,
            "unavailable_count": 0,
            "watchlist_member_count": 0,
            "run_status": None,
            "stock_result_count": 0,
            "history_count": 0,
            "history_count_before": history_count_before,
            "history_delta": 0,
            "exported": [],
            "operation_terminal": "NOT_STARTED",
            "provider_call_count": 0,
            "provider_calls_at_terminal": 0,
            "provider_calls_after_terminal": 0,
            "unexecuted_symbols": [],
            "attempted_symbols": [],
            "feedback_kinds": [],
            "scenario_assertions_passed": False,
        }
        watchlist_id: str | None = None
        latest_run_id: str | None = None
        for step in scenario.steps:
            if step.action == "bootstrap":
                continue
            if step.action == "import_securities":
                imported = application.import_securities(step.value or "")
                summary["security_count"] = imported.success_count
                summary["excluded_count"] = len(imported.excluded)
                summary["unavailable_count"] = len(imported.unavailable)
            elif step.action == "create_watchlist":
                watchlist_id = application.master_data.create_watchlist(step.value or "").id
            elif step.action == "add_all_classified":
                if watchlist_id is None:
                    raise ValueError("scenario watchlist is missing")
                securities = application.master_data.list_securities()
                watchlist = application.master_data.add_watchlist_members(
                    watchlist_id,
                    tuple(
                        (security.id, security.bindings[0].id)
                        for security in sorted(
                            securities,
                            key=lambda item: item.canonical_symbol,
                        )
                        if security.bindings
                    ),
                )
                summary["watchlist_member_count"] = len(watchlist.memberships)
            elif step.action == "run":
                if watchlist_id is None:
                    raise ValueError("scenario watchlist is missing")
                operation_id = f"{scenario.id}-operation"
                cancel_stage = next(
                    (
                        fault.stage
                        for fault in scenario.fault_plan
                        if fault.target == "cancel"
                    ),
                    "",
                )
                canceled = False

                def progress(
                    item: Any,
                    stage: str = cancel_stage,
                    active_operation_id: str = operation_id,
                ) -> None:
                    nonlocal canceled
                    if (
                        stage
                        and item.stage == stage
                        and not canceled
                    ):
                        application.cancel_operation(
                            active_operation_id
                        )
                        canceled = True

                result = application.run(
                    RunRequest(
                        watchlist_id,
                        step.benchmark or "SPY.US",
                        date.fromisoformat(step.end_date or ""),
                        step.ranges,
                        None,
                    ),
                    operation_id=operation_id,
                    progress=progress,
                )
                latest_run_id = result.run_id
                summary["run_status"] = result.status.value
                summary["run_error_code"] = result.error_code
                summary["stock_result_count"] = (
                    len(result.output.stock_results) if result.output is not None else 0
                )
                snapshot = application.registry.status(operation_id)
                summary["operation_terminal"] = (
                    snapshot.status.value
                    if snapshot is not None
                    else "NOT_STARTED"
                )
                summary["provider_calls_at_terminal"] = (
                    provider.external_call_count
                )
            elif step.action == "run_rs_benchmark":
                benchmark = run_frozen_benchmark()
                summary["watchlist_member_count"] = MEMBER_COUNT
                summary["run_status"] = "READY"
                summary["stock_result_count"] = len(benchmark.output.stock_results)
                summary["classification_result_count"] = (
                    len(benchmark.output.classification_period_results)
                )
                summary["session_count"] = benchmark.session_count
                summary["canonical_bytes"] = benchmark.canonical_bytes
                summary["canonical_sha256"] = benchmark.canonical_sha256
                if len(benchmark.output.classification_results) != CLASSIFICATION_COUNT:
                    raise ValueError("benchmark classification count changed")
            elif step.action == "export_latest":
                latest = application.latest_history()
                if latest is None:
                    raise ValueError("scenario history is missing")
                exported = []
                suffixes = {
                    "json": ".json",
                    "markdown": ".md",
                    "csv": ".zip",
                }
                for format_name in step.formats:
                    target = (
                        application.paths.exports_root / f"{scenario.id}{suffixes[format_name]}"
                    )
                    application.export_history(
                        latest.header.run_id,
                        format_name,
                        target,
                    )
                    exported.append(format_name)
                summary["exported"] = exported
            elif step.action == "generate_rs_report_twice":
                if latest_run_id is None or report is None:
                    raise ValueError("scenario report run is missing")
                application.generate_rs_strength_report(latest_run_id)
                old_snapshot = application.get_history(latest_run_id)
                old_reports = canonical_json(
                    old_snapshot.header.snapshot_extensions.get(
                        "ai_reports",
                        [],
                    )
                )
                before_fault = len(application.list_history())
                try:
                    application.generate_rs_strength_report(latest_run_id)
                except AIAdapterError as error:
                    summary["report_error"] = error.code
                else:
                    raise ValueError("scenario AI failure did not occur")
                current_snapshot = application.get_history(latest_run_id)
                current_reports = canonical_json(
                    current_snapshot.header.snapshot_extensions.get(
                        "ai_reports",
                        [],
                    )
                )
                summary["old_report_preserved"] = (
                    current_reports == old_reports
                )
                summary["history_count_before_fault"] = before_fault
                summary["history_count_after_fault"] = len(
                    application.list_history()
                )
                summary["report_call_count"] = report.call_count
        summary["history_count"] = len(application.list_history())
        summary["history_delta"] = (
            summary["history_count"] - history_count_before
        )
        summary["provider_call_count"] = provider.external_call_count
        summary["provider_calls_after_terminal"] = (
            provider.external_call_count
        )
        summary["unexecuted_symbols"] = list(
            provider.unexecuted_symbols
        )
        summary["attempted_symbols"] = list(
            provider.attempted_symbols
        )
        summary["feedback_kinds"] = list(provider.feedback_kinds)
        summary["database_busy_count"] = (
            busy_factory.failure_count
            if busy_factory is not None
            else 0
        )
        summary["writes_before_fault"] = (
            busy_factory.writes_before_fault
            if busy_factory is not None
            else 0
        )
        with closing(application.factory.open_reader()) as connection:
            summary["persisted_run_rows"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM run_snapshots"
                ).fetchone()[0]
            )
            summary["persisted_analysis_rows"] = int(
                connection.execute(
                    "SELECT COUNT(*) FROM analysis_runs"
                ).fetchone()[0]
            )
        self.verify_provider_call_budget(
            scenario,
            actual_calls=provider.external_call_count,
        )
        for key, expected in scenario.expected.items():
            if key not in summary or summary[key] != expected:
                raise ValueError(f"scenario expectation failed: {key}")
        summary["scenario_assertions_passed"] = True
        return summary
