"""Environment-aware construction of the shared application core."""

from __future__ import annotations

import hashlib
import uuid
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

import httpx

from stock_toolbox import __version__
from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationProgress,
    ExtremeDeviationRequest,
    ExtremeDeviationRunResult,
    ExtremeDeviationRunStatus,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import (
    SCRIPT_VERSION as EXTREME_QUANT_VERSION,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import (
    SUPPORTED_INTERVALS as EXTREME_DEVIATION_INTERVALS,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import (
    request_for as extreme_quant_request,
)
from stock_toolbox.analyses.extreme_deviation.application.report import (
    DISCLAIMER,
    PROMPT_VERSION,
    TechnicalReport,
    build_report_payload,
    system_prompt,
)
from stock_toolbox.analyses.extreme_deviation.application.service import (
    StartExtremeDeviationRun,
)
from stock_toolbox.analyses.extreme_deviation.module import ExtremeDeviationModule
from stock_toolbox.analyses.registry import AnalysisRegistry
from stock_toolbox.analyses.resource_budget import (
    AnalysisBudgetService,
    AnalysisBudgetSnapshot,
)
from stock_toolbox.analyses.rs_strength.application.models import (
    BarsResult,
    RunProgress,
    RunRequest,
    RunResult,
    RunStatus,
)
from stock_toolbox.analyses.rs_strength.application.report import (
    DISCLAIMER as RS_REPORT_DISCLAIMER,
)
from stock_toolbox.analyses.rs_strength.application.report import (
    PROMPT_VERSION as RS_REPORT_PROMPT_VERSION,
)
from stock_toolbox.analyses.rs_strength.application.report import (
    RSStrengthReport,
)
from stock_toolbox.analyses.rs_strength.application.report import (
    build_report_payload as build_rs_report_payload,
)
from stock_toolbox.analyses.rs_strength.application.report import (
    normalize_report_text as normalize_rs_report_text,
)
from stock_toolbox.analyses.rs_strength.application.report import (
    system_prompt as rs_report_system_prompt,
)
from stock_toolbox.analyses.rs_strength.application.service import StartRun
from stock_toolbox.analyses.rs_strength.module import RSStrengthModule
from stock_toolbox.analyses.turning_point.application.backtest import (
    BacktestCell,
    TurningPointBacktest,
    backtest_candles,
)
from stock_toolbox.analyses.turning_point.application.models import (
    TurningPointProgress,
    TurningPointRequest,
    TurningPointRunResult,
    TurningPointRunStatus,
)
from stock_toolbox.analyses.turning_point.application.quant import (
    SCRIPT_VERSION as TURNING_QUANT_VERSION,
)
from stock_toolbox.analyses.turning_point.application.quant import (
    request_for as turning_quant_request,
)
from stock_toolbox.analyses.turning_point.application.report import (
    DISCLAIMER as TURNING_REPORT_DISCLAIMER,
)
from stock_toolbox.analyses.turning_point.application.report import (
    PROMPT_VERSION as TURNING_REPORT_PROMPT_VERSION,
)
from stock_toolbox.analyses.turning_point.application.report import (
    TurningPointReport,
)
from stock_toolbox.analyses.turning_point.application.report import (
    build_report_payload as build_turning_report_payload,
)
from stock_toolbox.analyses.turning_point.application.report import (
    system_prompt as turning_report_system_prompt,
)
from stock_toolbox.analyses.turning_point.application.service import (
    StartTurningPointRun,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    TurningPointTradeSide,
)
from stock_toolbox.analyses.turning_point.module import TurningPointModule
from stock_toolbox.core.diagnostics.models import (
    DiagnosticLogger,
    NullDiagnosticLogger,
)
from stock_toolbox.core.market_data.cache import CachedCandleService
from stock_toolbox.core.market_data.daily_cache import CachedDailyBarsProvider
from stock_toolbox.core.market_data.date_policy import display_today
from stock_toolbox.core.market_data.fallback import (
    FallbackConsent,
    FallbackDailyBarsProvider,
    FallbackMarketDataPort,
    FallbackSession,
    WholeRunFallbackRequested,
    restart_whole_run_on_accept,
)
from stock_toolbox.core.market_data.models import (
    CandleDataset,
    CandleInterval,
    DailyBarsProviderPort,
    DailySeriesProgress,
    DailySeriesProgressSink,
    ScreeningMarketDataPort,
    SecuritySnapshot,
    SnapshotDataset,
)
from stock_toolbox.core.market_data.provider_health import (
    HistoryQuotaSnapshot,
    ProviderIdentity,
)
from stock_toolbox.core.market_data.quant import (
    CachedQuantMarketDataService,
    QuantMarketDataPort,
    QuantProgress,
    QuantProgressSink,
    QuantSeriesDataset,
    QuantSeriesRequest,
)
from stock_toolbox.core.market_data.quant_daily import (
    SCRIPT_VERSION as DAILY_QUANT_VERSION,
)
from stock_toolbox.core.market_data.quant_daily import QuantDailyBarsService
from stock_toolbox.core.market_data.service import SharedMarketDataService
from stock_toolbox.core.operations.executor import (
    ExecuteReservedOperation,
    OperationCandidate,
)
from stock_toolbox.core.operations.registry import (
    CancelResult,
    OperationControl,
    OperationExecutionContext,
    OperationRegistry,
    OperationStatus,
)
from stock_toolbox.core.operations.storage_guard import StorageGuard, StorageState
from stock_toolbox.core.securities.import_service import (
    ImportProgress,
    ImportResult,
    ImportSecurities,
)
from stock_toolbox.core.securities.models import (
    AICompanyAnalysis,
    AICompanyAnalysisPort,
    AssetHint,
    ProviderProfile,
    ProviderProfileError,
    ProviderProfilesResult,
    SecurityProfilesPort,
    StoredClassification,
)
from stock_toolbox.core.settings.models import (
    ServiceSettingsDTO,
    ServiceSettingsInput,
    ServiceTestResult,
)
from stock_toolbox.core.settings.network import apply_proxy_environment
from stock_toolbox.infrastructure.ai.openai_compatible import (
    AIAdapterError,
    AIServiceConfig,
    OpenAICompatibleAI,
    discover_models,
)
from stock_toolbox.infrastructure.ai.technical_report import (
    OpenAICompatibleTechnicalReport,
)
from stock_toolbox.infrastructure.diagnostics.jsonl import JsonlDiagnosticLogger
from stock_toolbox.infrastructure.persistence.analysis_payload_store import (
    AnalysisPayloadStore,
)
from stock_toolbox.infrastructure.persistence.candle_cache import SQLiteCandleCache
from stock_toolbox.infrastructure.persistence.completed_run_store import (
    PersistentCompletedRunStore,
)
from stock_toolbox.infrastructure.persistence.connections import SQLiteConnectionFactory
from stock_toolbox.infrastructure.persistence.daily_series_cache import (
    SQLiteDailySeriesCache,
)
from stock_toolbox.infrastructure.persistence.global_ai_config import (
    GlobalAIConfigStore,
)
from stock_toolbox.infrastructure.persistence.history_records import HistorySnapshotRecord
from stock_toolbox.infrastructure.persistence.history_service import HistoryService
from stock_toolbox.infrastructure.persistence.master_data_store import SQLiteMasterDataStore
from stock_toolbox.infrastructure.persistence.migrations import MigrationRunner
from stock_toolbox.infrastructure.persistence.quant_result_cache import (
    SQLiteQuantResultCache,
)
from stock_toolbox.infrastructure.persistence.recomputable_cache import (
    SQLiteRecomputableCacheCleaner,
)
from stock_toolbox.infrastructure.persistence.security_import_store import (
    PersistentSecurityImportStore,
)
from stock_toolbox.infrastructure.persistence.service_settings import (
    ServiceSettingsStore,
)
from stock_toolbox.infrastructure.persistence.types import canonical_json
from stock_toolbox.infrastructure.providers.futu import (
    FutuProvider,
    FutuProviderError,
    FutuQuotePort,
)
from stock_toolbox.infrastructure.providers.futu_factory import (
    FutuQuoteContextFactory,
)
from stock_toolbox.infrastructure.providers.futu_opend import (
    FutuOpenDService,
    FutuOpenDStatus,
)
from stock_toolbox.infrastructure.providers.longbridge import (
    LongbridgeProvider,
)
from stock_toolbox.infrastructure.providers.longbridge_oauth import (
    InvalidLongbridgeClientIdError,
    LongbridgeOAuthService,
)
from stock_toolbox.infrastructure.providers.yahoo import YahooFallbackProvider
from stock_toolbox.infrastructure.virtual.ai import VirtualAI
from stock_toolbox.infrastructure.virtual.provider import VirtualProvider
from stock_toolbox.runtime.environment import RuntimeEnvironment
from stock_toolbox.runtime.paths import RuntimePaths
from stock_toolbox.runtime.reset import reset_local_state


def _open_browser(url: str) -> None:
    webbrowser.open(url)


def _decimal_text(value: Decimal | None) -> str:
    return format(value, "f") if value is not None else ""


def _refreshed_business_profile(
    existing: Mapping[str, object],
    incoming: Mapping[str, object],
    snapshot: SecuritySnapshot | None,
    checked_at: datetime,
) -> dict[str, object]:
    merged = dict(existing)
    merged.update(incoming)
    existing_company = existing.get("company")
    incoming_company = incoming.get("company")
    if isinstance(existing_company, Mapping) or isinstance(
        incoming_company,
        Mapping,
    ):
        company = dict(existing_company) if isinstance(existing_company, Mapping) else {}
        if isinstance(incoming_company, Mapping):
            company.update(incoming_company)
        merged["company"] = company
    previous_refresh = existing.get("refresh")
    previous = dict(previous_refresh) if isinstance(previous_refresh, Mapping) else {}
    refresh: dict[str, object] = {
        "status": "ACTIVE",
        "error": "",
        "checked_at": checked_at.astimezone(UTC).isoformat(),
    }
    last_price = (
        _decimal_text(snapshot.last_price)
        if snapshot is not None
        else str(previous.get("last_price") or "")
    )
    market_value = (
        _decimal_text(snapshot.total_market_value)
        if snapshot is not None
        else str(previous.get("market_value") or "")
    )
    if last_price:
        refresh["last_price"] = last_price
    if market_value:
        refresh["market_value"] = market_value
    merged["refresh"] = refresh
    return merged


class ApplicationProvider(
    SecurityProfilesPort,
    ScreeningMarketDataPort,
    Protocol,
):
    provider_id: str

    def latest_completed_trading_day(
        self,
        *,
        operation_control: OperationControl,
        on_or_before: date | None = None,
    ) -> date | None: ...


class TechnicalReportAdapter(Protocol):
    model: str

    def generate(
        self,
        system_prompt: str,
        user_payload: dict[str, object],
        *,
        operation_control: OperationControl | None = None,
    ) -> str: ...


class FutuOpenDPort(Protocol):
    def probe(self) -> FutuOpenDStatus: ...

    def open(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class SecurityRefreshProgress:
    stage: str
    completed: int
    total: int
    symbol: str = ""
    status: str = ""


@dataclass(frozen=True, slots=True)
class SecurityRefreshResult:
    updated_count: int
    unavailable_count: int
    failed_count: int
    details: tuple[tuple[str, str, str], ...]


@dataclass(slots=True)
class StockToolboxApplication:
    paths: RuntimePaths
    home: Path
    diagnostics: DiagnosticLogger
    factory: SQLiteConnectionFactory
    registry: OperationRegistry
    analyses: AnalysisRegistry
    master_data: SQLiteMasterDataStore
    _import_service: ImportSecurities
    _provider: ApplicationProvider
    _ai: AICompanyAnalysisPort
    _history: HistoryService
    _analysis_payloads: AnalysisPayloadStore
    _settings_store: ServiceSettingsStore
    _adapter_builder: Callable[
        [],
        tuple[ApplicationProvider, AICompanyAnalysisPort],
    ]
    _longbridge_oauth: LongbridgeOAuthService
    _futu_opend: FutuOpenDPort
    _global_ai_store: GlobalAIConfigStore
    _storage_guard: StorageGuard
    _rs_report_override: TechnicalReportAdapter | None
    _clock: Callable[[], datetime]
    _new_id: Callable[[], str]
    _fallback_provider_override: FallbackMarketDataPort | None = None

    def import_securities(
        self,
        raw_input: str,
        *,
        operation_id: str | None = None,
        progress: Callable[[ImportProgress], None] = lambda _item: None,
    ) -> ImportResult:
        active_operation_id = operation_id or self._new_id()
        self.registry.reserve(
            active_operation_id,
            self._new_id(),
            "security_import",
        )
        executed = ExecuteReservedOperation(self.registry).execute(
            active_operation_id,
            lambda context: self._import_candidate(
                raw_input,
                context,
                progress,
            ),
        )
        if executed.payload is None:
            raise RuntimeError(
                str(
                    executed.snapshot.summary.get(
                        "error_code",
                        "security_import_failed",
                    )
                )
            )
        return cast(ImportResult, executed.payload)

    def get_security_snapshot(
        self,
        security_id: str,
    ) -> SecuritySnapshot | None:
        security = self.master_data.get_security(security_id)
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "security_snapshot",
        )

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            dataset = self._provider.get_security_snapshots(
                (security.canonical_symbol,),
                operation_control=context.operation_control,
            )
            snapshot = dataset.snapshots_by_symbol.get(security.canonical_symbol)
            if snapshot is None:
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {
                        "error_code": dataset.errors.get(
                            security.canonical_symbol,
                            "snapshot_unavailable",
                        )
                    },
                )
            return OperationCandidate(
                OperationStatus.SUCCEEDED,
                {"symbol": security.canonical_symbol},
                snapshot,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        return executed.payload if isinstance(executed.payload, SecuritySnapshot) else None

    def refresh_all_security_profiles(
        self,
        *,
        operation_id: str | None = None,
        progress: Callable[
            [SecurityRefreshProgress],
            None,
        ] = lambda _item: None,
    ) -> SecurityRefreshResult:
        active_operation_id = operation_id or self._new_id()
        self.registry.reserve(
            active_operation_id,
            self._new_id(),
            "global_security_refresh",
        )

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            securities = self.master_data.list_securities()
            total = len(securities)
            if total == 0:
                result = SecurityRefreshResult(0, 0, 0, ())
                return OperationCandidate(
                    OperationStatus.SUCCEEDED,
                    {"updated": 0, "unavailable": 0, "failed": 0},
                    result,
                )
            profiles: dict[str, ProviderProfile] = {}
            profile_errors: dict[str, str] = {}
            snapshots: dict[str, SecuritySnapshot] = {}
            provider_id = self._provider.provider_id
            for offset in range(0, total, 50):
                batch = securities[offset : offset + 50]
                symbols = tuple(item.canonical_symbol for item in batch)
                profile_result = self._provider.get_security_profiles(
                    symbols,
                    operation_control=context.operation_control,
                )
                snapshot_result = self._provider.get_security_snapshots(
                    symbols,
                    operation_control=context.operation_control,
                )
                profiles.update({item.symbol: item for item in profile_result.profiles})
                provider_id = profile_result.provider_id
                profile_errors.update({item.symbol: item.code for item in profile_result.errors})
                snapshots.update(snapshot_result.snapshots_by_symbol)
                progress(
                    SecurityRefreshProgress(
                        "FETCHING",
                        min(total, offset + len(batch)),
                        total * 2,
                    )
                )
            if not context.operation_control.try_enter_committing():
                result = SecurityRefreshResult(0, 0, total, ())
                return OperationCandidate(
                    OperationStatus.CANCELED,
                    {"updated": 0, "unavailable": 0, "failed": total},
                    result,
                )

            updated = 0
            unavailable = 0
            failed = 0
            details: list[tuple[str, str, str]] = []
            for index, security in enumerate(securities, start=1):
                symbol = security.canonical_symbol
                profile = profiles.get(symbol)
                snapshot = snapshots.get(symbol)
                status = "UPDATED"
                reason = ""
                try:
                    if profile is None:
                        reason = profile_errors.get(
                            symbol,
                            "profile_unavailable",
                        )
                        availability = (
                            "UNAVAILABLE" if reason == "symbol_unavailable" else "CHECK_FAILED"
                        )
                        self.master_data.record_security_refresh(
                            security.id,
                            availability_status=availability,
                            error_code=reason,
                            last_price=_decimal_text(
                                snapshot.last_price if snapshot is not None else None
                            ),
                            market_value=_decimal_text(
                                snapshot.total_market_value if snapshot is not None else None
                            ),
                        )
                        if availability == "UNAVAILABLE":
                            unavailable += 1
                            status = "UNAVAILABLE"
                        else:
                            failed += 1
                            status = "CHECK_FAILED"
                    else:
                        business_profile = _refreshed_business_profile(
                            security.business_profile,
                            profile.business_profile,
                            snapshot,
                            self._clock(),
                        )
                        self.master_data.refresh_security_profile(
                            security.id,
                            replace(
                                profile,
                                business_profile=business_profile,
                            ),
                            provider_id=provider_id,
                        )
                        updated += 1
                except RuntimeError:
                    failed += 1
                    status = "CHECK_FAILED"
                    reason = "persistence_failed"
                details.append((symbol, status, reason))
                progress(
                    SecurityRefreshProgress(
                        "UPDATING",
                        total + index,
                        total * 2,
                        symbol,
                        status,
                    )
                )
            result = SecurityRefreshResult(
                updated,
                unavailable,
                failed,
                tuple(details),
            )
            return OperationCandidate(
                OperationStatus.SUCCEEDED,
                {
                    "updated": updated,
                    "unavailable": unavailable,
                    "failed": failed,
                },
                result,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            active_operation_id,
            handler,
        )
        if isinstance(executed.payload, SecurityRefreshResult):
            return executed.payload
        raise RuntimeError("global_security_refresh_failed")

    def _import_candidate(
        self,
        raw_input: str,
        context: OperationExecutionContext,
        progress: Callable[[ImportProgress], None],
    ) -> OperationCandidate:
        result = self._import_service.execute(
            raw_input,
            context,
            progress=progress,
        )
        return OperationCandidate(
            OperationStatus.SUCCEEDED,
            {
                "success_count": result.success_count,
                "committed": result.committed,
            },
            result,
        )

    def run(
        self,
        request: RunRequest,
        *,
        operation_id: str | None = None,
        progress: Callable[[RunProgress], None] = lambda _item: None,
        fallback_consent: FallbackConsent | None = None,
        force_yahoo: bool = False,
    ) -> RunResult:
        storage = self._storage_guard.prepare_run()
        if storage.state is StorageState.BLOCKED:
            return RunResult(
                RunStatus.FAILED,
                error_code=storage.error_code,
            )
        active_operation_id = operation_id or self._new_id()
        self.registry.reserve(active_operation_id, self._new_id(), "run")
        raw_primary_provider: DailyBarsProviderPort = (
            self._fallback_provider() if force_yahoo else self._provider
        )
        primary_provider = self._cached_daily_provider(raw_primary_provider)
        quant_market_data = (
            None if force_yahoo else self._quant_market_data_for(DAILY_QUANT_VERSION)
        )
        daily_provider: DailyBarsProviderPort = (
            QuantDailyBarsService(
                quant_market_data,
                etf_fallback=primary_provider,
            )
            if quant_market_data is not None
            else primary_provider
        )
        fallback_provider = (
            self._cached_daily_provider(self._fallback_provider())
            if fallback_consent is not None and not force_yahoo
            else None
        )
        if fallback_consent is not None and fallback_provider is not None:
            daily_provider = FallbackDailyBarsProvider(
                daily_provider,
                fallback_provider,
                FallbackSession(restart_whole_run_on_accept(fallback_consent)),
                operation_kind="rs",
            )

        def service_for(provider: DailyBarsProviderPort) -> StartRun:
            return StartRun(
                self.master_data,
                provider,
                PersistentCompletedRunStore(
                    self.factory,
                    new_id=self._new_id,
                ),
                clock=self._clock,
                new_id=self._new_id,
                progress=progress,
                today=lambda: display_today(
                    self.settings().display_timezone,
                    self._clock(),
                ),
            )

        service = service_for(daily_provider)

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            try:
                result = service.execute(request, context)
            except WholeRunFallbackRequested:
                assert fallback_provider is not None
                result = service_for(fallback_provider).execute(
                    request,
                    context,
                )
            terminal = {
                RunStatus.READY: OperationStatus.SUCCEEDED,
                RunStatus.PARTIAL: OperationStatus.SUCCEEDED,
                RunStatus.FAILED: OperationStatus.FAILED,
                RunStatus.CANCELED: OperationStatus.CANCELED,
            }[result.status]
            return OperationCandidate(
                terminal,
                {
                    "run_status": result.status.value,
                    "error_code": result.error_code or "",
                },
                result,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            active_operation_id,
            handler,
        )
        if executed.payload is None:
            return RunResult(
                (
                    RunStatus.CANCELED
                    if executed.snapshot.status is OperationStatus.CANCELED
                    else RunStatus.FAILED
                ),
                error_code=str(
                    executed.snapshot.summary.get(
                        "error_code",
                        "run_failed",
                    )
                ),
            )
        return cast(RunResult, executed.payload)

    def _quant_market_data(self) -> CachedQuantMarketDataService:
        provider_id = str(getattr(self._provider, "provider_id", "longbridge"))
        provider_name = str(
            getattr(
                self._provider,
                "provider_display_name",
                provider_id,
            )
        )
        return CachedQuantMarketDataService(
            cast(QuantMarketDataPort, self._provider),
            SQLiteQuantResultCache(self.factory, clock=self._clock),
            provider_id,
            provider_name,
        )

    def _fallback_provider(self) -> FallbackMarketDataPort:
        if self._fallback_provider_override is not None:
            return self._fallback_provider_override
        settings = self.settings()
        return YahooFallbackProvider(
            proxy_url=(settings.proxy_url if settings.proxy_mode == "custom" else ""),
            timeout_seconds=float(settings.timeout_seconds),
            now=self._clock,
        )

    def _cached_daily_provider(
        self,
        provider: DailyBarsProviderPort,
    ) -> DailyBarsProviderPort:
        provider_id = str(getattr(provider, "provider_id", ""))
        if provider_id not in {"futu", "yahoo"}:
            return provider
        return CachedDailyBarsProvider(
            provider,
            SQLiteDailySeriesCache(self.factory, clock=self._clock),
        )

    def _analysis_budget_service(self) -> AnalysisBudgetService:
        provider_id = str(getattr(self._provider, "provider_id", "longbridge"))
        provider_name = str(
            getattr(
                self._provider,
                "provider_display_name",
                provider_id,
            )
        )
        raw_history_quota = getattr(
            self._provider,
            "get_history_quota",
            None,
        )
        history_quota = (
            cast(Callable[[], HistoryQuotaSnapshot], raw_history_quota)
            if callable(raw_history_quota)
            else None
        )
        return AnalysisBudgetService(
            self.master_data,
            SQLiteQuantResultCache(self.factory, clock=self._clock),
            provider_id=provider_id,
            provider_display_name=provider_name,
            quant_script_versions=set(
                getattr(
                    self._provider,
                    "quant_script_versions",
                    (),
                )
            ),
            storage_guard=self._storage_guard,
            history_quota=history_quota,
            candle_cache=SQLiteCandleCache(self.factory, clock=self._clock),
            daily_cache=SQLiteDailySeriesCache(self.factory, clock=self._clock),
        )

    def estimate_rs_budget(
        self,
        request: RunRequest,
    ) -> AnalysisBudgetSnapshot:
        return self._analysis_budget_service().estimate_rs(request)

    def estimate_turning_budget(
        self,
        request: TurningPointRequest,
    ) -> AnalysisBudgetSnapshot:
        return self._analysis_budget_service().estimate_turning(request)

    def estimate_extreme_budget(
        self,
        request: ExtremeDeviationRequest,
    ) -> AnalysisBudgetSnapshot:
        return self._analysis_budget_service().estimate_extreme(request)

    def _supports_quant(self, script_version: str) -> bool:
        capabilities = getattr(
            self._provider,
            "quant_script_versions",
            (),
        )
        return (
            callable(getattr(self._provider, "get_quant_series", None))
            and script_version in capabilities
        )

    def _quant_market_data_for(
        self,
        script_version: str,
    ) -> CachedQuantMarketDataService | None:
        """Select Quant once; execution errors never trigger raw-data fallback."""

        return self._quant_market_data() if self._supports_quant(script_version) else None

    def run_turning_point(
        self,
        request: TurningPointRequest,
        *,
        operation_id: str | None = None,
        progress: Callable[[TurningPointProgress], None] = lambda _item: None,
        fallback_consent: FallbackConsent | None = None,
        force_yahoo: bool = False,
    ) -> TurningPointRunResult:
        storage = self._storage_guard.prepare_run()
        if storage.state is StorageState.BLOCKED:
            return TurningPointRunResult(
                TurningPointRunStatus.FAILED,
                error_code=storage.error_code,
            )
        active_operation_id = operation_id or self._new_id()
        self.registry.reserve(
            active_operation_id,
            self._new_id(),
            "turning_point_run",
        )
        primary_provider = self._fallback_provider() if force_yahoo else self._provider
        quant_market_data = (
            None if force_yahoo else self._quant_market_data_for(TURNING_QUANT_VERSION)
        )
        fallback_provider = (
            self._fallback_provider() if fallback_consent is not None and not force_yahoo else None
        )
        fallback_session = (
            FallbackSession(restart_whole_run_on_accept(fallback_consent))
            if fallback_consent is not None
            else None
        )
        primary_provider_id = str(getattr(primary_provider, "provider_id", "market"))
        primary_provider_name = str(
            getattr(primary_provider, "provider_display_name", primary_provider_id)
        )
        cached_primary_candles = CachedCandleService(
            SharedMarketDataService(primary_provider),
            SQLiteCandleCache(self.factory, clock=self._clock),
            primary_provider_id,
            primary_provider_name,
        )
        cached_fallback_candles = (
            CachedCandleService(
                SharedMarketDataService(fallback_provider),
                SQLiteCandleCache(self.factory, clock=self._clock),
                str(getattr(fallback_provider, "provider_id", "yahoo")),
                str(
                    getattr(
                        fallback_provider,
                        "provider_display_name",
                        "Yahoo 备用数据",
                    )
                ),
            )
            if fallback_provider is not None
            else None
        )
        service = StartTurningPointRun(
            self.master_data,
            cached_primary_candles,
            self._analysis_payloads,
            quant_market_data=quant_market_data,
            fallback_market_data=cached_fallback_candles,
            fallback_session=fallback_session,
            clock=self._clock,
            new_id=self._new_id,
            progress=progress,
            today=lambda: display_today(
                self.settings().display_timezone,
                self._clock(),
            ),
        )
        if cached_fallback_candles is not None:
            fallback_service = StartTurningPointRun(
                self.master_data,
                cached_fallback_candles,
                self._analysis_payloads,
                quant_market_data=None,
                fallback_market_data=None,
                fallback_session=None,
                clock=self._clock,
                new_id=self._new_id,
                progress=progress,
                today=lambda: display_today(
                    self.settings().display_timezone,
                    self._clock(),
                ),
            )
        else:
            fallback_service = None

        def handler(context: OperationExecutionContext) -> OperationCandidate:
            try:
                result = service.execute(request, context)
            except WholeRunFallbackRequested:
                assert fallback_service is not None
                result = fallback_service.execute(request, context)
            terminal = {
                TurningPointRunStatus.READY: OperationStatus.SUCCEEDED,
                TurningPointRunStatus.PARTIAL: OperationStatus.SUCCEEDED,
                TurningPointRunStatus.FAILED: OperationStatus.FAILED,
                TurningPointRunStatus.CANCELED: OperationStatus.CANCELED,
            }[result.status]
            return OperationCandidate(
                terminal,
                {
                    "run_status": result.status.value,
                    "error_code": result.error_code or "",
                },
                result,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            active_operation_id,
            handler,
        )
        if isinstance(executed.payload, TurningPointRunResult):
            return executed.payload
        return TurningPointRunResult(
            (
                TurningPointRunStatus.CANCELED
                if executed.snapshot.status is OperationStatus.CANCELED
                else TurningPointRunStatus.FAILED
            ),
            error_code=str(
                executed.snapshot.summary.get(
                    "error_code",
                    "turning_point_run_failed",
                )
            ),
        )

    def backtest_turning_point(
        self,
        symbols: tuple[str, ...],
        intervals: tuple[CandleInterval, ...],
        end_date: date,
        *,
        count: int = 1000,
        trade_sides: tuple[TurningPointTradeSide, ...] = (
            TurningPointTradeSide.LEFT_CD,
            TurningPointTradeSide.RIGHT_CONFIRMED,
        ),
    ) -> TurningPointBacktest:
        normalized = tuple(
            dict.fromkeys(
                symbol.strip().upper()
                if symbol.strip().upper().endswith(".US")
                else f"{symbol.strip().upper()}.US"
                for symbol in symbols
                if symbol.strip()
            )
        )
        if not normalized or not intervals or not trade_sides:
            raise ValueError("symbols, intervals and trade_sides are required")
        requested_count = max(220, min(1000, count))
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "turning_point_backtest",
        )

        def handler(context: OperationExecutionContext) -> OperationCandidate:
            cells: list[BacktestCell] = []
            errors: list[tuple[str, str, str]] = []
            provider_id = str(getattr(self._provider, "provider_id", ""))
            provider_name = str(getattr(self._provider, "provider_display_name", provider_id))
            end_at = datetime.combine(end_date, time.max, UTC)
            for interval in intervals:
                dataset = self._provider.get_candle_series(
                    normalized,
                    interval,
                    requested_count,
                    end_at,
                    operation_control=context.operation_control,
                )
                provider_id = dataset.provider_id
                provider_name = dataset.provider_display_name
                for symbol in normalized:
                    series = dataset.series_by_symbol.get(symbol)
                    if series is None:
                        errors.append(
                            (
                                symbol,
                                interval.value,
                                dataset.errors.get(
                                    symbol,
                                    "candles_unavailable",
                                ),
                            )
                        )
                        continue
                    cells.extend(
                        backtest_candles(
                            symbol,
                            interval,
                            series.candles,
                            trade_sides,
                        )
                    )
            report = TurningPointBacktest(
                provider_id,
                provider_name,
                end_date,
                requested_count,
                tuple(cells),
                tuple(errors),
            )
            return OperationCandidate(
                OperationStatus.SUCCEEDED,
                {
                    "cell_count": len(cells),
                    "error_count": len(errors),
                },
                report,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        if executed.payload is None:
            raise RuntimeError("turning point backtest failed")
        return cast(TurningPointBacktest, executed.payload)

    def list_turning_point_history(
        self,
        *,
        limit: int = 10,
    ) -> tuple[dict[str, object], ...]:
        return self._analysis_payloads.list("turning_point", limit=limit)

    def export_turning_point_history(
        self,
        run_id: str,
        format_name: str,
    ) -> str:
        return self._analysis_payloads.export(run_id, format_name)

    def pin_turning_point_history(self, run_id: str, pinned: bool) -> None:
        self._analysis_payloads.set_pinned(run_id, pinned)

    def delete_turning_point_history(self, run_id: str) -> None:
        self._analysis_payloads.delete(run_id)

    def generate_turning_point_report(
        self,
        run_id: str,
        *,
        operation_control: OperationControl | None = None,
    ) -> TurningPointReport:
        history_payload = self._analysis_payloads.get_payload(
            run_id,
            "turning_point",
        )
        report_payload = build_turning_report_payload(history_payload)
        if not report_payload["results"]:
            raise RuntimeError("turning_point_report_evidence_unavailable")
        config = self._settings_store.global_ai_config()
        if self.paths.environment in {
            RuntimeEnvironment.SCENARIO,
            RuntimeEnvironment.INTEGRATION,
        }:
            model = "virtual-turning-point-report"
            content = (
                "1. 整体反转聚集\n已按冻结的多周期结果完成复盘。\n\n"
                "2. 强烈关注与重点观察\n优先查看中长周期共同命中项。\n\n"
                "3. 普通观察\n短周期单独命中仍需等待确认。\n\n"
                "4. 周期共振和分歧\n以本地综合关注度和命中周期为准。\n\n"
                "5. 数据失败与局限\n已保留逐周期失败与质量证据。\n\n"
                "6. 后续复盘顺序\n先长周期共振，再观察短周期延续。\n\n"
                f"{TURNING_REPORT_DISCLAIMER}"
            )
        else:
            if config is None:
                raise RuntimeError("ai_configuration_invalid")
            model = config.model
            adapter = OpenAICompatibleTechnicalReport(
                AIServiceConfig(
                    config.base_url,
                    config.model,
                    config.revision,
                    Decimal(config.timeout_seconds),
                    config.max_retries,
                ),
                self._global_ai_store,
            )
            content = adapter.generate(
                turning_report_system_prompt(str(report_payload["trade_side"])),
                report_payload,
                operation_control=operation_control,
            )
            if TURNING_REPORT_DISCLAIMER not in content:
                content = f"{content.rstrip()}\n\n{TURNING_REPORT_DISCLAIMER}"
        generated_at = self._clock()
        report = TurningPointReport(
            model,
            TURNING_REPORT_PROMPT_VERSION,
            content,
            generated_at,
            hashlib.sha256(canonical_json(report_payload).encode("utf-8")).hexdigest(),
        )
        self._enter_report_commit(operation_control)
        self._analysis_payloads.attach_ai_report(
            run_id,
            "turning_point",
            {
                "model": report.model,
                "prompt_version": report.prompt_version,
                "content": report.content,
                "generated_at": report.generated_at.isoformat(),
                "input_sha256": report.input_sha256,
                "input": report_payload,
            },
        )
        return report

    def run_extreme_deviation(
        self,
        request: ExtremeDeviationRequest,
        *,
        operation_id: str | None = None,
        progress: Callable[[ExtremeDeviationProgress], None] = lambda _item: None,
        fallback_consent: FallbackConsent | None = None,
        force_yahoo: bool = False,
    ) -> ExtremeDeviationRunResult:
        storage = self._storage_guard.prepare_run()
        if storage.state is StorageState.BLOCKED:
            return ExtremeDeviationRunResult(
                ExtremeDeviationRunStatus.FAILED,
                error_code=storage.error_code,
            )
        active_operation_id = operation_id or self._new_id()
        self.registry.reserve(
            active_operation_id,
            self._new_id(),
            "extreme_deviation_run",
        )
        primary_provider = self._fallback_provider() if force_yahoo else self._provider
        provider_id = str(getattr(primary_provider, "provider_id", "longbridge"))
        provider_name = str(getattr(primary_provider, "provider_display_name", provider_id))
        fallback_provider = (
            self._fallback_provider() if fallback_consent is not None and not force_yahoo else None
        )
        fallback_session = (
            FallbackSession(restart_whole_run_on_accept(fallback_consent))
            if fallback_consent is not None and not force_yahoo
            else None
        )
        service = StartExtremeDeviationRun(
            self.master_data,
            CachedCandleService(
                SharedMarketDataService(primary_provider),
                SQLiteCandleCache(self.factory, clock=self._clock),
                provider_id,
                provider_name,
            ),
            self._analysis_payloads,
            # Extreme deviation intentionally uses raw candles plus the local
            # corrected formula.  Provider-side formula semantics differ for
            # partial 500-bar history and can suppress valid pressure pulses.
            quant_market_data=None,
            fallback_market_data=(
                SharedMarketDataService(fallback_provider)
                if fallback_provider is not None
                else None
            ),
            fallback_session=fallback_session,
            clock=self._clock,
            new_id=self._new_id,
            progress=progress,
        )
        fallback_service = (
            StartExtremeDeviationRun(
                self.master_data,
                CachedCandleService(
                    SharedMarketDataService(fallback_provider),
                    SQLiteCandleCache(self.factory, clock=self._clock),
                    str(getattr(fallback_provider, "provider_id", "yahoo")),
                    str(
                        getattr(
                            fallback_provider,
                            "provider_display_name",
                            "Yahoo 备用数据",
                        )
                    ),
                ),
                self._analysis_payloads,
                quant_market_data=None,
                fallback_market_data=None,
                fallback_session=None,
                clock=self._clock,
                new_id=self._new_id,
                progress=progress,
            )
            if fallback_provider is not None
            else None
        )

        def handler(context: OperationExecutionContext) -> OperationCandidate:
            try:
                result = service.execute(request, context)
            except WholeRunFallbackRequested:
                assert fallback_service is not None
                result = fallback_service.execute(request, context)
            terminal = {
                ExtremeDeviationRunStatus.READY: OperationStatus.SUCCEEDED,
                ExtremeDeviationRunStatus.PARTIAL: OperationStatus.SUCCEEDED,
                ExtremeDeviationRunStatus.FAILED: OperationStatus.FAILED,
                ExtremeDeviationRunStatus.CANCELED: OperationStatus.CANCELED,
            }[result.status]
            return OperationCandidate(
                terminal,
                {
                    "run_status": result.status.value,
                    "error_code": result.error_code or "",
                },
                result,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            active_operation_id,
            handler,
        )
        if isinstance(executed.payload, ExtremeDeviationRunResult):
            return executed.payload
        return ExtremeDeviationRunResult(
            (
                ExtremeDeviationRunStatus.CANCELED
                if executed.snapshot.status is OperationStatus.CANCELED
                else ExtremeDeviationRunStatus.FAILED
            ),
            error_code=str(
                executed.snapshot.summary.get(
                    "error_code",
                    "extreme_deviation_run_failed",
                )
            ),
        )

    def list_extreme_deviation_history(
        self,
        *,
        limit: int = 10,
    ) -> tuple[dict[str, object], ...]:
        return self._analysis_payloads.list(
            "extreme_deviation",
            limit=limit,
        )

    def export_extreme_deviation_history(
        self,
        run_id: str,
        format_name: str,
    ) -> str:
        return self._analysis_payloads.export(run_id, format_name)

    def pin_extreme_deviation_history(
        self,
        run_id: str,
        pinned: bool,
    ) -> None:
        self._analysis_payloads.set_pinned(run_id, pinned)

    def delete_extreme_deviation_history(self, run_id: str) -> None:
        self._analysis_payloads.delete(run_id)

    def generate_extreme_deviation_report(
        self,
        run_id: str,
        selected_symbols: tuple[str, ...],
        *,
        operation_control: OperationControl | None = None,
    ) -> TechnicalReport:
        history_payload = self._analysis_payloads.get_payload(
            run_id,
            "extreme_deviation",
        )
        report_payload = build_report_payload(
            history_payload,
            selected_symbols,
        )
        config = self._settings_store.global_ai_config()
        if self.paths.environment in {
            RuntimeEnvironment.SCENARIO,
            RuntimeEnvironment.INTEGRATION,
        }:
            model = "virtual-technical-report"
            content = (
                "1. 多周期总体结论\n已按冻结评分完成复盘。\n\n"
                "2. 买卖方向和最主要依据\n以确定性评分为准。\n\n"
                "3. 长短周期共振或分歧\n详见多周期结论。\n\n"
                "4. 最值得关注的证券及原因\n详见所选证券。\n\n"
                "5. 数据不足、低置信度和异常项\n已保留原始状态。\n\n"
                "6. 后续观察条件\n等待下一完整收盘周期。\n\n"
                f"{DISCLAIMER}"
            )
        else:
            if config is None:
                raise RuntimeError("ai_configuration_invalid")
            model = config.model
            adapter = OpenAICompatibleTechnicalReport(
                AIServiceConfig(
                    config.base_url,
                    config.model,
                    config.revision,
                    Decimal(config.timeout_seconds),
                    config.max_retries,
                ),
                self._global_ai_store,
            )
            content = adapter.generate(
                system_prompt(),
                report_payload,
                operation_control=operation_control,
            )
            if DISCLAIMER not in content:
                content = f"{content.rstrip()}\n\n{DISCLAIMER}"
        generated_at = self._clock()
        report = TechnicalReport(
            tuple(item["symbol"] for item in report_payload["results"]),
            model,
            PROMPT_VERSION,
            content,
            generated_at,
            hashlib.sha256(canonical_json(report_payload).encode("utf-8")).hexdigest(),
        )
        self._enter_report_commit(operation_control)
        self._analysis_payloads.attach_ai_report(
            run_id,
            "extreme_deviation",
            {
                "selected_symbols": list(report.selected_symbols),
                "model": report.model,
                "prompt_version": report.prompt_version,
                "content": report.content,
                "generated_at": report.generated_at.isoformat(),
                "input_sha256": report.input_sha256,
                "input": report_payload,
            },
        )
        return report

    @staticmethod
    def _enter_report_commit(
        operation_control: OperationControl | None,
    ) -> None:
        if operation_control is not None and not operation_control.try_enter_committing():
            raise AIAdapterError("canceled")

    def cancel_operation(self, operation_id: str) -> CancelResult:
        return self.registry.cancel(operation_id)

    def test_provider_connection(self) -> ServiceTestResult:
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "provider_connection_test",
        )

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            result = self._provider.get_security_profiles(
                ("AAPL.US",),
                operation_control=context.operation_control,
            )
            if result.profiles:
                payload = ServiceTestResult(
                    "provider",
                    True,
                    "PROVIDER_OK",
                    (result.provider_id,),
                )
                return OperationCandidate(
                    OperationStatus.SUCCEEDED,
                    {"code": payload.code},
                    payload,
                )
            code = result.errors[0].code if result.errors else "provider_invalid_response"
            payload = ServiceTestResult("provider", False, code)
            return OperationCandidate(
                OperationStatus.FAILED,
                {"code": code},
                payload,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        if isinstance(executed.payload, ServiceTestResult):
            return executed.payload
        return ServiceTestResult(
            "provider",
            False,
            str(executed.snapshot.summary.get("code", "provider_error")),
        )

    def test_market_data_connection(
        self,
        symbol: str,
        benchmark_symbol: str,
    ) -> ServiceTestResult:
        normalized_symbol = symbol.strip().upper()
        normalized_benchmark = benchmark_symbol.strip().upper()
        if not normalized_symbol.endswith(".US") or normalized_benchmark not in {
            "SPY.US",
            "QQQ.US",
        }:
            return ServiceTestResult(
                "provider",
                False,
                "invalid_smoke_symbols",
            )
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "market_data_connection_test",
        )

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            profiles = self._provider.get_security_profiles(
                (normalized_symbol,),
                operation_control=context.operation_control,
            )
            if not profiles.profiles:
                code = profiles.errors[0].code if profiles.errors else "profile_unavailable"
                payload = ServiceTestResult("provider", False, code)
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": code},
                    payload,
                )
            end_date = self._provider.latest_completed_trading_day(
                operation_control=context.operation_control,
            )
            if end_date is None:
                payload = ServiceTestResult(
                    "provider",
                    False,
                    "market_calendar_unavailable",
                )
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": payload.code},
                    payload,
                )
            bars = QuantDailyBarsService(
                self._quant_market_data(),
                etf_fallback=self._provider,
            ).get_daily_series(
                (normalized_benchmark, normalized_symbol),
                end_date - timedelta(days=45),
                end_date,
                operation_control=context.operation_control,
            )
            if bars.errors:
                code = next(iter(bars.errors.values()))
                payload = ServiceTestResult("provider", False, code)
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": code},
                    payload,
                )
            stock_series = bars.series_by_symbol.get(normalized_symbol)
            benchmark_series = bars.series_by_symbol.get(normalized_benchmark)
            if (
                stock_series is None
                or benchmark_series is None
                or len(stock_series.points) < 2
                or len(benchmark_series.points) < 2
            ):
                payload = ServiceTestResult(
                    "provider",
                    False,
                    "bars_incomplete",
                )
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": payload.code},
                    payload,
                )
            payload = ServiceTestResult(
                "provider",
                True,
                "MARKET_DATA_OK",
                (
                    normalized_symbol,
                    end_date.isoformat(),
                    str(len(stock_series.points)),
                    normalized_benchmark,
                    str(len(benchmark_series.points)),
                    bars.provider_id,
                ),
            )
            return OperationCandidate(
                OperationStatus.SUCCEEDED,
                {"code": payload.code},
                payload,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        return (
            executed.payload
            if isinstance(executed.payload, ServiceTestResult)
            else ServiceTestResult(
                "provider",
                False,
                str(
                    executed.snapshot.summary.get(
                        "code",
                        "market_data_test_failed",
                    )
                ),
            )
        )

    def test_turning_point_market_data_connection(
        self,
        symbol: str,
    ) -> ServiceTestResult:
        normalized = symbol.strip().upper()
        if not normalized.endswith(".US"):
            return ServiceTestResult(
                "provider",
                False,
                "invalid_smoke_symbols",
            )
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "turning_point_market_data_connection_test",
        )

        def handler(context: OperationExecutionContext) -> OperationCandidate:
            end_date = self._provider.latest_completed_trading_day(
                operation_control=context.operation_control,
            )
            if end_date is None:
                payload = ServiceTestResult(
                    "provider",
                    False,
                    "market_calendar_unavailable",
                )
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": payload.code},
                    payload,
                )
            snapshots = self._provider.get_security_snapshots(
                (normalized,),
                operation_control=context.operation_control,
            )
            snapshot = snapshots.snapshots_by_symbol.get(normalized)
            if self._supports_quant(TURNING_QUANT_VERSION):
                derived = self._quant_market_data().get_quant_series(
                    (normalized,),
                    turning_quant_request(
                        CandleInterval.MIN_30,
                        end_date,
                    ),
                    operation_control=context.operation_control,
                )
                quant_series = derived.series_by_symbol.get(normalized)
                series_count = len(quant_series.timestamps) if quant_series is not None else 0
                provider_id = derived.provider_id
                error = snapshots.errors.get(normalized) or derived.errors.get(normalized)
            else:
                candles = self._provider.get_candle_series(
                    (normalized,),
                    CandleInterval.MIN_30,
                    120,
                    datetime.combine(end_date, time.max, UTC),
                    operation_control=context.operation_control,
                )
                candle_series = candles.series_by_symbol.get(normalized)
                series_count = len(candle_series.candles) if candle_series is not None else 0
                provider_id = candles.provider_id
                error = snapshots.errors.get(normalized) or candles.errors.get(normalized)
            if error is not None or snapshot is None or series_count == 0:
                payload = ServiceTestResult(
                    "provider",
                    False,
                    error or "turning_point_data_incomplete",
                )
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": payload.code},
                    payload,
                )
            payload = ServiceTestResult(
                "provider",
                True,
                "TURNING_POINT_MARKET_DATA_OK",
                (
                    normalized,
                    end_date.isoformat(),
                    str(series_count),
                    CandleInterval.MIN_30.value,
                    provider_id,
                ),
            )
            return OperationCandidate(
                OperationStatus.SUCCEEDED,
                {"code": payload.code},
                payload,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        return (
            executed.payload
            if isinstance(executed.payload, ServiceTestResult)
            else ServiceTestResult(
                "provider",
                False,
                str(
                    executed.snapshot.summary.get(
                        "code",
                        "turning_point_market_data_failed",
                    )
                ),
            )
        )

    def test_extreme_deviation_market_data_connection(
        self,
        symbol: str,
    ) -> ServiceTestResult:
        normalized = symbol.strip().upper()
        if not normalized.endswith(".US"):
            return ServiceTestResult(
                "provider",
                False,
                "invalid_smoke_symbols",
            )
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "extreme_deviation_market_data_connection_test",
        )

        def handler(context: OperationExecutionContext) -> OperationCandidate:
            end_date = self._provider.latest_completed_trading_day(
                operation_control=context.operation_control,
            )
            if end_date is None:
                payload = ServiceTestResult(
                    "provider",
                    False,
                    "market_calendar_unavailable",
                )
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": payload.code},
                    payload,
                )
            details = [normalized, end_date.isoformat()]
            for interval in EXTREME_DEVIATION_INTERVALS:
                if self._supports_quant(EXTREME_QUANT_VERSION):
                    derived = self._quant_market_data().get_quant_series(
                        (normalized,),
                        extreme_quant_request(interval, end_date),
                        operation_control=context.operation_control,
                    )
                    quant_series = derived.series_by_symbol.get(normalized)
                    series_count = len(quant_series.timestamps) if quant_series is not None else 0
                    error = derived.errors.get(normalized)
                else:
                    candles = self._provider.get_candle_series(
                        (normalized,),
                        interval,
                        650,
                        datetime.combine(end_date, time.max, UTC),
                        operation_control=context.operation_control,
                    )
                    candle_series = candles.series_by_symbol.get(normalized)
                    series_count = len(candle_series.candles) if candle_series is not None else 0
                    error = candles.errors.get(normalized)
                if error is not None or series_count == 0:
                    payload = ServiceTestResult(
                        "provider",
                        False,
                        error or "extreme_deviation_data_incomplete",
                        tuple(details),
                    )
                    return OperationCandidate(
                        OperationStatus.FAILED,
                        {"code": payload.code},
                        payload,
                    )
                details.append(f"{interval.value}:{series_count}")
            payload = ServiceTestResult(
                "provider",
                True,
                "EXTREME_DEVIATION_MARKET_DATA_OK",
                tuple(details),
            )
            return OperationCandidate(
                OperationStatus.SUCCEEDED,
                {"code": payload.code},
                payload,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        return (
            executed.payload
            if isinstance(executed.payload, ServiceTestResult)
            else ServiceTestResult(
                "provider",
                False,
                str(
                    executed.snapshot.summary.get(
                        "code",
                        "extreme_deviation_market_data_failed",
                    )
                ),
            )
        )

    def refresh_security_profile(
        self,
        security_id: str,
    ) -> ServiceTestResult:
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "security_profile_refresh",
        )

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            security = self.master_data.get_security(security_id)
            result = self._provider.get_security_profiles(
                (security.canonical_symbol,),
                operation_control=context.operation_control,
            )
            if not result.profiles:
                code = result.errors[0].code if result.errors else "profile_unavailable"
                payload = ServiceTestResult("provider", False, code)
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": code},
                    payload,
                )
            if not context.operation_control.try_enter_committing():
                payload = ServiceTestResult(
                    "provider",
                    False,
                    "canceled",
                )
                return OperationCandidate(
                    OperationStatus.CANCELED,
                    {"code": payload.code},
                    payload,
                )
            self.master_data.refresh_security_profile(
                security_id,
                result.profiles[0],
                provider_id=result.provider_id,
            )
            payload = ServiceTestResult(
                "provider",
                True,
                "PROFILE_REFRESHED",
                (security.canonical_symbol,),
            )
            return OperationCandidate(
                OperationStatus.SUCCEEDED,
                {"code": payload.code},
                payload,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        return (
            executed.payload
            if isinstance(executed.payload, ServiceTestResult)
            else ServiceTestResult(
                "provider",
                False,
                str(
                    executed.snapshot.summary.get(
                        "code",
                        "profile_refresh_failed",
                    )
                ),
            )
        )

    def reanalyze_security(
        self,
        security_id: str,
    ) -> ServiceTestResult:
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "security_ai_reanalysis",
        )

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            security = self.master_data.get_security(security_id)
            before_ids = {item.id for item in security.bindings}
            profile = ProviderProfile(
                security.canonical_symbol,
                security.display_name,
                "US",
                None,
                None,
                "US",
                security.description,
                (AssetHint(security.asset_type, "reliable"),),
                security.business_profile,
                None,
            )
            existing = tuple(
                StoredClassification(
                    item.id,
                    item.display_name,
                    item.normalized_name,
                    item.aliases,
                )
                for item in self.master_data.list_classifications()
            )
            try:
                analysis = self._ai.analyze_company(
                    profile,
                    existing,
                    operation_control=context.operation_control,
                )
            except Exception:  # noqa: BLE001 - sanitized AI boundary
                payload = ServiceTestResult(
                    "ai",
                    False,
                    "ai_request_failed",
                )
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": payload.code},
                    payload,
                )
            if not analysis.eligible:
                payload = ServiceTestResult(
                    "ai",
                    False,
                    "ai_rejected_existing_security",
                )
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": payload.code},
                    payload,
                )
            if not context.operation_control.try_enter_committing():
                payload = ServiceTestResult("ai", False, "canceled")
                return OperationCandidate(
                    OperationStatus.CANCELED,
                    {"code": payload.code},
                    payload,
                )
            updated = self.master_data.add_ai_classifications(
                security_id,
                tuple(
                    (
                        item.existing_classification_id,
                        item.canonical_name,
                        item.confidence,
                    )
                    for item in analysis.classifications
                ),
            )
            added = tuple(
                item.classification_name for item in updated.bindings if item.id not in before_ids
            )
            payload = ServiceTestResult(
                "ai",
                True,
                "AI_CLASSIFICATIONS_ADDED" if added else "AI_NO_CHANGE",
                added,
            )
            return OperationCandidate(
                OperationStatus.SUCCEEDED,
                {"code": payload.code},
                payload,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        return (
            executed.payload
            if isinstance(executed.payload, ServiceTestResult)
            else ServiceTestResult(
                "ai",
                False,
                str(
                    executed.snapshot.summary.get(
                        "code",
                        "ai_reanalysis_failed",
                    )
                ),
            )
        )

    def latest_completed_trading_day(
        self,
        *,
        on_or_before: date | None = None,
    ) -> date | None:
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "latest_completed_trading_day",
        )

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            result = self._provider.latest_completed_trading_day(
                operation_control=context.operation_control,
                on_or_before=on_or_before,
            )
            if result is None:
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": "market_calendar_unavailable"},
                )
            return OperationCandidate(
                OperationStatus.SUCCEEDED,
                {"code": "MARKET_CALENDAR_OK"},
                result,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        return executed.payload if isinstance(executed.payload, date) else None

    def preview_ai_classification(self) -> ServiceTestResult:
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "ai_classification_preview",
        )

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            profile = ProviderProfile(
                "IREN.US",
                "IREN Limited",
                "US",
                "NASDAQ",
                "USD",
                "US",
                ("Builds and operates data centers for AI cloud computing and bitcoin mining."),
                (AssetHint("COMMON_STOCK", "reliable"),),
                {},
                None,
            )
            existing = tuple(
                StoredClassification(
                    item.id,
                    item.display_name,
                    item.normalized_name,
                    item.aliases,
                )
                for item in self.master_data.list_classifications()
            )
            try:
                analysis = self._ai.analyze_company(
                    profile,
                    existing,
                    operation_control=context.operation_control,
                )
            except Exception:  # noqa: BLE001 - sanitized external boundary
                payload = ServiceTestResult(
                    "ai",
                    False,
                    "ai_request_failed",
                )
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": payload.code},
                    payload,
                )
            details = tuple(item.canonical_name for item in analysis.classifications)
            payload = ServiceTestResult(
                "ai",
                bool(details),
                "AI_OK" if details else "ai_invalid_response",
                details,
            )
            return OperationCandidate(
                (OperationStatus.SUCCEEDED if payload.ok else OperationStatus.FAILED),
                {"code": payload.code},
                payload,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        if isinstance(executed.payload, ServiceTestResult):
            return executed.payload
        return ServiceTestResult(
            "ai",
            False,
            str(executed.snapshot.summary.get("code", "ai_request_failed")),
        )

    def test_profile_ai_classification(
        self,
        symbol: str,
    ) -> ServiceTestResult:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol.endswith(".US"):
            return ServiceTestResult(
                "ai",
                False,
                "invalid_smoke_symbols",
            )
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "provider_ai_classification_test",
        )

        def handler(
            context: OperationExecutionContext,
        ) -> OperationCandidate:
            profiles = self._provider.get_security_profiles(
                (normalized_symbol,),
                operation_control=context.operation_control,
            )
            if not profiles.profiles:
                code = profiles.errors[0].code if profiles.errors else "profile_unavailable"
                payload = ServiceTestResult("ai", False, code)
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": code},
                    payload,
                )
            existing = tuple(
                StoredClassification(
                    item.id,
                    item.display_name,
                    item.normalized_name,
                    item.aliases,
                )
                for item in self.master_data.list_classifications()
            )
            try:
                analysis = self._ai.analyze_company(
                    profiles.profiles[0],
                    existing,
                    operation_control=context.operation_control,
                )
            except Exception:  # noqa: BLE001 - sanitized external boundary
                payload = ServiceTestResult(
                    "ai",
                    False,
                    "ai_request_failed",
                )
                return OperationCandidate(
                    OperationStatus.FAILED,
                    {"code": payload.code},
                    payload,
                )
            details = tuple(item.canonical_name for item in analysis.classifications)
            payload = ServiceTestResult(
                "ai",
                analysis.eligible and bool(details),
                ("PROVIDER_AI_OK" if analysis.eligible and details else "ai_invalid_response"),
                details,
            )
            return OperationCandidate(
                (OperationStatus.SUCCEEDED if payload.ok else OperationStatus.FAILED),
                {"code": payload.code},
                payload,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        if isinstance(executed.payload, ServiceTestResult):
            return executed.payload
        return ServiceTestResult(
            "ai",
            False,
            str(executed.snapshot.summary.get("code", "ai_request_failed")),
        )

    def test_extreme_deviation_ai_connection(self) -> ServiceTestResult:
        config = self._settings_store.global_ai_config()
        if config is None:
            return ServiceTestResult(
                "ai",
                False,
                "ai_configuration_invalid",
            )
        adapter = OpenAICompatibleTechnicalReport(
            AIServiceConfig(
                config.base_url,
                config.model,
                config.revision,
                Decimal(config.timeout_seconds),
                config.max_retries,
            ),
            self._global_ai_store,
        )
        smoke_payload = {
            "prompt_version": PROMPT_VERSION,
            "algorithm_version": "extreme-deviation-v2",
            "field_semantics": {
                "score": "-100 buy observation; +100 sell observation",
                "confidence": "FULL",
                "consensus": "NEUTRAL",
            },
            "results": [
                {
                    "symbol": "SMOKE.US",
                    "company_name": "Smoke Test",
                    "classification_name": "Unclassified",
                    "consensus": {"kind": "NEUTRAL", "score": 0},
                    "periods": [
                        {
                            "interval": "1d",
                            "candle_count": 650,
                            "error_code": None,
                            "score": 0,
                            "label": "中性",
                            "confidence": "FULL",
                            "buy_deviation": 0.0,
                            "sell_deviation": 0.0,
                            "latest_at": "2026-07-24T20:00:00+00:00",
                        }
                    ],
                }
            ],
        }
        try:
            content = adapter.generate(system_prompt(), smoke_payload)
        except Exception:  # noqa: BLE001 - sanitized external boundary
            return ServiceTestResult(
                "ai",
                False,
                "extreme_deviation_ai_request_failed",
            )
        if not content.strip():
            return ServiceTestResult(
                "ai",
                False,
                "extreme_deviation_ai_invalid_response",
            )
        return ServiceTestResult(
            "ai",
            True,
            "EXTREME_DEVIATION_AI_OK",
            (config.model, PROMPT_VERSION),
        )

    def latest_history(self) -> HistorySnapshotRecord | None:
        snapshots = self._history.list(limit=1)
        return snapshots[0] if snapshots else None

    def list_history(
        self,
        *,
        limit: int | None = None,
    ) -> tuple[HistorySnapshotRecord, ...]:
        return self._history.list(limit=limit)

    def get_history(self, run_id: str) -> HistorySnapshotRecord:
        return self._history.get(run_id)

    def generate_rs_strength_report(
        self,
        run_id: str,
        *,
        operation_control: OperationControl | None = None,
    ) -> RSStrengthReport:
        snapshot = self._history.get(run_id)
        report_payload = build_rs_report_payload(snapshot)
        if not report_payload["securities"]:
            raise RuntimeError("rs_report_evidence_unavailable")
        config = self._settings_store.global_ai_config()
        if self._rs_report_override is not None:
            model = self._rs_report_override.model
            content = self._rs_report_override.generate(
                rs_report_system_prompt(),
                report_payload,
                operation_control=operation_control,
            )
        elif self.paths.environment in {
            RuntimeEnvironment.SCENARIO,
            RuntimeEnvironment.INTEGRATION,
        }:
            model = "virtual-rs-strength-report"
            content = (
                "一、总体结论\n"
                "1. 最强方向\n已按冻结分类综合分整理领先方向。\n\n"
                "2. 最弱方向\n已按冻结分类综合分整理落后方向。\n\n"
                "二、强势分类\n"
                "1. 领先分类\n以分类综合分和区间覆盖为准。\n\n"
                "三、弱势分类\n"
                "1. 落后分类\n以分类综合分和区间覆盖为准。\n\n"
                "四、个股观察\n"
                "1. 跨周期个股\n已整理各区间领先项和落后项。\n\n"
                "五、短期强度跃迁\n"
                "1. 短期排名变化\n已比较短周期与长周期的相对名次。\n\n"
                "六、数据说明\n"
                "样本不足分类仅在此集中说明；本报告只解释冻结数据。\n\n"
                f"{RS_REPORT_DISCLAIMER}"
            )
        else:
            if config is None:
                raise RuntimeError("ai_configuration_invalid")
            model = config.model
            adapter = OpenAICompatibleTechnicalReport(
                AIServiceConfig(
                    config.base_url,
                    config.model,
                    config.revision,
                    Decimal(config.timeout_seconds),
                    config.max_retries,
                ),
                self._global_ai_store,
            )
            content = adapter.generate(
                rs_report_system_prompt(),
                report_payload,
                operation_control=operation_control,
            )
            if RS_REPORT_DISCLAIMER not in content:
                content = f"{content.rstrip()}\n\n{RS_REPORT_DISCLAIMER}"
        if RS_REPORT_DISCLAIMER not in content:
            content = f"{content.rstrip()}\n\n{RS_REPORT_DISCLAIMER}"
        content = normalize_rs_report_text(content)
        generated_at = self._clock()
        report = RSStrengthReport(
            model,
            RS_REPORT_PROMPT_VERSION,
            content,
            generated_at,
            hashlib.sha256(canonical_json(report_payload).encode("utf-8")).hexdigest(),
        )
        self._enter_report_commit(operation_control)
        self._history.attach_ai_report(
            run_id,
            {
                "model": report.model,
                "prompt_version": report.prompt_version,
                "content": report.content,
                "generated_at": report.generated_at.isoformat(),
                "input_sha256": report.input_sha256,
            },
        )
        return report

    def export_history(
        self,
        run_id: str,
        format_name: str,
        target: Path,
    ) -> None:
        self._history.publish(run_id, format_name, target)

    def render_history_export(
        self,
        run_id: str,
        format_name: str,
    ) -> bytes:
        return self._history.export(run_id, format_name)

    def publish_history_export(
        self,
        content: bytes,
        target: Path,
        *,
        cancellation_requested: Callable[[], bool],
        progress: Callable[[int, int], None],
    ) -> bool:
        return self._history.publish_content(
            content,
            target,
            cancellation_requested=cancellation_requested,
            progress=progress,
        )

    def import_history(self, content: bytes) -> HistorySnapshotRecord:
        return self._history.import_json(content)

    def update_history(
        self,
        run_id: str,
        *,
        display_name: str,
        note: str,
        pinned: bool,
    ) -> None:
        self._history.update(
            run_id,
            display_name=display_name,
            note=note,
            pinned=pinned,
        )

    def delete_history(self, run_id: str) -> None:
        self._history.delete(run_id)

    def delete_histories(self, run_ids: tuple[str, ...]) -> int:
        return self._history.delete_many(run_ids)

    def clear_unpinned_history(self) -> int:
        return self._history.clear_unpinned()

    def settings(self) -> ServiceSettingsDTO:
        return self._settings_store.load()

    def appearance_mode(self) -> str:
        return self._settings_store.load_appearance_mode()

    def save_appearance_mode(self, mode: str) -> None:
        self._settings_store.save_appearance_mode(mode)

    def save_settings(
        self,
        settings: ServiceSettingsInput,
        *,
        ai_api_key: bytearray | None = None,
    ) -> ServiceSettingsDTO:
        result = self._settings_store.save(
            settings,
            ai_api_key=ai_api_key,
        )
        self._reload_adapters()
        return result

    def provider_identity(self) -> ProviderIdentity:
        settings = self.settings()
        return ProviderIdentity(
            str(getattr(self._provider, "provider_id", settings.provider_mode)),
            str(
                getattr(
                    self._provider,
                    "provider_display_name",
                    settings.provider_mode,
                )
            ),
            settings.provider_configured,
        )

    def open_futu_opend(self) -> bool:
        return self._futu_opend.open()

    def futu_opend_status(self) -> FutuOpenDStatus:
        return self._futu_opend.probe()

    def quality_futu(self) -> ServiceTestResult:
        status = self._futu_opend.probe()
        if not status.port_open:
            return ServiceTestResult("provider", False, status.code)
        completed = ["opend"]
        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "futu_provider_quality",
        )
        context = self.registry.begin_reserved(operation_id)
        if context is None:
            return ServiceTestResult(
                "provider",
                False,
                "provider_quality_not_started",
                tuple(completed),
            )
        provider: ApplicationProvider | None = None
        try:
            provider = _futu_provider(self.settings())
            day = provider.latest_completed_trading_day(
                operation_control=context.operation_control,
            )
            if day is None:
                raise RuntimeError("PROVIDER_TRADING_DAY_FAILED")
            completed.append("trading_day")
            profiles = provider.get_security_profiles(
                ("AAPL.US",),
                operation_control=context.operation_control,
            )
            if not profiles.profiles:
                raise RuntimeError("PROVIDER_PROFILE_FAILED")
            completed.append("company_profile")
            snapshots = provider.get_security_snapshots(
                ("AAPL.US",),
                operation_control=context.operation_control,
            )
            if "AAPL.US" not in snapshots.snapshots_by_symbol:
                raise RuntimeError("PROVIDER_SNAPSHOT_FAILED")
            completed.append("snapshot")
            bars = provider.get_daily_series(
                ("AAPL.US",),
                day - timedelta(days=14),
                day,
                operation_control=context.operation_control,
            )
            series = bars.series_by_symbol.get("AAPL.US")
            if series is None or not series.points:
                raise RuntimeError("PROVIDER_DAILY_BARS_FAILED")
            completed.append("daily_bars")
            quota_reader = getattr(provider, "get_history_quota", None)
            if not callable(quota_reader):
                raise TypeError("PROVIDER_QUOTA_FAILED")
            quota_reader(operation_control=context.operation_control)
            completed.append("history_quota")
        except Exception as exception:  # noqa: BLE001 - provider boundary
            code = "PROVIDER_FUTU_FAILED"
            if isinstance(exception, FutuProviderError):
                code = exception.code
            elif str(exception) in {
                "PROVIDER_TRADING_DAY_FAILED",
                "PROVIDER_PROFILE_FAILED",
                "PROVIDER_SNAPSHOT_FAILED",
                "PROVIDER_DAILY_BARS_FAILED",
                "PROVIDER_QUOTA_FAILED",
            }:
                code = str(exception)
            elif completed:
                code = {
                    "opend": "PROVIDER_TRADING_DAY_FAILED",
                    "trading_day": "PROVIDER_PROFILE_FAILED",
                    "company_profile": "PROVIDER_SNAPSHOT_FAILED",
                    "snapshot": "PROVIDER_DAILY_BARS_FAILED",
                    "daily_bars": "PROVIDER_QUOTA_FAILED",
                }.get(completed[-1], code)
            self.registry.try_complete(
                operation_id,
                OperationStatus.FAILED,
                {"code": code},
            )
            return ServiceTestResult(
                "provider",
                False,
                code,
                tuple(completed),
            )
        finally:
            self._close_provider(provider)
        self._settings_store.save_provider_candidate(
            "futu",
            configured=True,
        )
        self.registry.try_complete(
            operation_id,
            OperationStatus.SUCCEEDED,
            {"code": "PROVIDER_QUALITY_OK"},
        )
        return ServiceTestResult(
            "provider",
            True,
            "PROVIDER_QUALITY_OK",
            tuple(completed),
        )

    def activate_provider(self, provider_id: str) -> ServiceSettingsDTO:
        result = self._settings_store.activate_provider(provider_id)
        self._reload_adapters()
        return result

    def authorize_longbridge(
        self,
        client_id: str | None = None,
        *,
        on_open_url: Callable[[str], None] = _open_browser,
    ) -> ServiceTestResult:
        candidate = ""
        try:
            candidate = (
                client_id.strip() if client_id is not None else self._longbridge_oauth.register()
            )
            self._longbridge_oauth.authorize(
                candidate,
                on_open_url,
            )
        except InvalidLongbridgeClientIdError:
            return ServiceTestResult(
                "provider",
                False,
                "OAUTH_CLIENT_ID_INVALID",
            )
        except Exception:  # noqa: BLE001 - sanitized OAuth boundary
            return ServiceTestResult(
                "provider",
                False,
                "OAUTH_AUTHORIZATION_FAILED",
            )
        return ServiceTestResult(
            "provider",
            True,
            "OAUTH_AUTHORIZED",
            (candidate,),
        )

    def quality_longbridge(self, client_id: str) -> ServiceTestResult:
        candidate = client_id.strip()
        current = self.settings()
        completed: list[str] = []
        operation_id = ""
        try:
            candidate_settings = replace(
                current,
                provider_mode="longbridge",
                provider_configured=True,
                longbridge_client_id=candidate,
            )
            provider = _longbridge_provider(
                candidate_settings,
                self._longbridge_oauth,
            )
            completed.append("oauth")
            operation_id = self._new_id()
            self.registry.reserve(
                operation_id,
                self._new_id(),
                "provider_quality",
            )
            context = self.registry.begin_reserved(operation_id)
            if context is None:
                raise RuntimeError("provider_quality_not_started")
            day = provider.latest_completed_trading_day(
                operation_control=context.operation_control,
            )
            if day is None:
                return self._failed_longbridge_quality(
                    candidate,
                    current,
                    "PROVIDER_TRADING_DAY_FAILED",
                    completed,
                    operation_id,
                )
            completed.append("trading_day")
            profiles = provider.get_security_profiles(
                ("AAPL.US",),
                operation_control=context.operation_control,
            )
            if not profiles.profiles:
                return self._failed_longbridge_quality(
                    candidate,
                    current,
                    "PROVIDER_PROFILE_FAILED",
                    completed,
                    operation_id,
                )
            completed.append("company_profile")
            bars = provider.get_daily_series(
                ("AAPL.US",),
                day - timedelta(days=14),
                day,
                operation_control=context.operation_control,
            )
            series = bars.series_by_symbol.get("AAPL.US")
            if series is None or not series.points:
                return self._failed_longbridge_quality(
                    candidate,
                    current,
                    "PROVIDER_DAILY_BARS_FAILED",
                    completed,
                    operation_id,
                )
            completed.append("daily_bars")
        except Exception:  # noqa: BLE001 - sanitized provider boundary
            return self._failed_longbridge_quality(
                candidate,
                current,
                "PROVIDER_OAUTH_FAILED",
                completed,
                operation_id,
            )
        self._settings_store.save(
            ServiceSettingsInput(
                "longbridge",
                current.timeout_seconds,
                current.max_retries,
                current.ai_base_url,
                current.ai_model,
                current.developer_mode_enabled,
                candidate,
            )
        )
        if current.longbridge_client_id and current.longbridge_client_id != candidate:
            self._longbridge_oauth.clear(current.longbridge_client_id)
        self._reload_adapters()
        self.registry.try_complete(
            operation_id,
            OperationStatus.SUCCEEDED,
            {"code": "PROVIDER_QUALITY_OK"},
        )
        return ServiceTestResult(
            "provider",
            True,
            "PROVIDER_QUALITY_OK",
            tuple(completed),
        )

    def complete_first_run(self) -> ServiceSettingsDTO:
        return self._settings_store.complete_first_run()

    def dismiss_product_tour(self) -> ServiceSettingsDTO:
        return self._settings_store.dismiss_product_tour()

    def reset_counts(self) -> tuple[int, int, int, int]:
        return (
            len(self.master_data.list_securities()),
            len(self.master_data.list_classifications()),
            len(self.master_data.list_watchlists()),
            len(self.list_history()),
        )

    def reset_local_data(self) -> None:
        if self.registry.non_terminal_snapshots():
            raise RuntimeError("operations_active")
        current = self.settings()
        reset_local_state(
            self.paths,
            self._longbridge_oauth,
            current.longbridge_client_id,
            clear_diagnostics=(
                self.diagnostics.clear
                if isinstance(
                    self.diagnostics,
                    JsonlDiagnosticLogger,
                )
                else None
            ),
        )
        self.paths.data_root.mkdir(parents=True, exist_ok=True)
        self.paths.log_root.mkdir(parents=True, exist_ok=True)
        self.paths.exports_root.mkdir(parents=True, exist_ok=True)
        MigrationRunner(
            self.paths.database,
            app_version=__version__,
            now=self._clock,
        ).bootstrap()
        self._global_ai_store.ensure_schema()
        self._reload_adapters()

    def discover_ai_models(
        self,
        base_url: str,
        api_key: bytearray,
    ) -> tuple[str, ...]:
        return discover_models(base_url, api_key)

    def discover_saved_ai_models(self) -> tuple[str, ...]:
        """Discover models with the saved local credential without exposing it to QML."""

        config = self._global_ai_store.load()
        if config is None:
            return ()
        api_key = self._global_ai_store.read_secret(config.revision)
        try:
            return discover_models(config.base_url, api_key)
        finally:
            api_key[:] = b"\x00" * len(api_key)

    def test_network_connection(self) -> ServiceTestResult:
        try:
            response = httpx.get(
                "https://openapi.longbridge.com/.well-known/oauth-authorization-server",
                follow_redirects=True,
                timeout=10,
            )
        except httpx.HTTPError:
            return ServiceTestResult(
                "network",
                False,
                "NETWORK_QUALITY_FAILED",
            )
        return ServiceTestResult(
            "network",
            response.status_code < 500,
            ("NETWORK_QUALITY_OK" if response.status_code < 500 else "NETWORK_QUALITY_FAILED"),
        )

    def test_yahoo_connection(self) -> ServiceTestResult:
        """Read one small completed NVDA daily window through the real fallback path."""

        operation_id = self._new_id()
        self.registry.reserve(
            operation_id,
            self._new_id(),
            "yahoo_fallback_quality",
        )

        def handler(context: OperationExecutionContext) -> OperationCandidate:
            end_date = display_today(
                self.settings().display_timezone,
                self._clock(),
            ) - timedelta(days=1)
            dataset = self._fallback_provider().get_daily_series(
                ("NVDA.US",),
                end_date - timedelta(days=10),
                end_date,
                operation_control=context.operation_control,
            )
            ok = bool(dataset.series_by_symbol.get("NVDA.US"))
            result = ServiceTestResult(
                "yahoo",
                ok,
                "YAHOO_QUALITY_OK" if ok else dataset.errors.get("NVDA.US", "data_unavailable"),
                ("NVDA.US", "1d") if ok else (),
            )
            return OperationCandidate(
                OperationStatus.SUCCEEDED if ok else OperationStatus.FAILED,
                {"code": result.code},
                result,
            )

        executed = ExecuteReservedOperation(self.registry).execute(
            operation_id,
            handler,
        )
        if isinstance(executed.payload, ServiceTestResult):
            return executed.payload
        return ServiceTestResult(
            "yahoo",
            False,
            str(executed.snapshot.summary.get("code", "network_error")),
        )

    def configure_ai(
        self,
        base_url: str,
        model: str,
        api_key: bytearray,
    ) -> ServiceTestResult:
        working_key = bytearray(api_key)
        operation_id = ""

        class SecretReader:
            @staticmethod
            def read(_reference: str | int) -> bytearray:
                return bytearray(working_key)

        try:
            current = self.settings()
            ai = OpenAICompatibleAI(
                AIServiceConfig(
                    base_url,
                    model,
                    1,
                    Decimal(current.timeout_seconds),
                    current.max_retries,
                ),
                SecretReader(),
            )
            operation_id = self._new_id()
            self.registry.reserve(
                operation_id,
                self._new_id(),
                "ai_quality",
            )
            context = self.registry.begin_reserved(operation_id)
            if context is None:
                raise RuntimeError("ai_quality_not_started")
            analysis = ai.analyze_company(
                ProviderProfile(
                    "IREN.US",
                    "IREN Limited",
                    "US",
                    "NASDAQ",
                    "USD",
                    "US",
                    "Builds AI data centers and Bitcoin mining infrastructure.",
                    (AssetHint("COMMON_STOCK", "reliable"),),
                    {},
                    None,
                ),
                (),
                operation_control=context.operation_control,
            )
            details = tuple(item.canonical_name for item in analysis.classifications)
            if not details:
                raise RuntimeError("ai_quality_empty")
            self.save_settings(
                ServiceSettingsInput(
                    current.provider_mode,
                    current.timeout_seconds,
                    current.max_retries,
                    base_url,
                    model,
                    current.developer_mode_enabled,
                    current.longbridge_client_id,
                ),
                ai_api_key=bytearray(working_key),
            )
            self.complete_first_run()
            self.registry.try_complete(
                operation_id,
                OperationStatus.SUCCEEDED,
                {"code": "AI_QUALITY_OK"},
            )
            return ServiceTestResult(
                "ai",
                True,
                "AI_QUALITY_OK",
                details,
            )
        except Exception:  # noqa: BLE001 - sanitized AI boundary
            if operation_id:
                self.registry.try_complete(
                    operation_id,
                    OperationStatus.FAILED,
                    {"code": "AI_QUALITY_FAILED"},
                )
            return ServiceTestResult(
                "ai",
                False,
                "AI_QUALITY_FAILED",
            )
        finally:
            working_key[:] = b"\x00" * len(working_key)
            api_key[:] = b"\x00" * len(api_key)

    def _failed_longbridge_quality(
        self,
        candidate: str,
        current: ServiceSettingsDTO,
        code: str,
        completed: list[str],
        operation_id: str = "",
    ) -> ServiceTestResult:
        if candidate and candidate != current.longbridge_client_id:
            try:
                self._longbridge_oauth.clear(candidate)
            except (InvalidLongbridgeClientIdError, OSError):
                pass
        if operation_id:
            self.registry.try_complete(
                operation_id,
                OperationStatus.FAILED,
                {"code": code},
            )
        return ServiceTestResult(
            "provider",
            False,
            code,
            tuple(completed),
        )

    def _reload_adapters(self) -> None:
        previous = self._provider
        self._provider, self._ai = self._adapter_builder()
        self._close_provider(previous)
        self._import_service = ImportSecurities(
            self._provider,
            self._ai,
            PersistentSecurityImportStore(self.factory),
            clock=self._clock,
            new_id=self._new_id,
        )

    @staticmethod
    def _close_provider(provider: object | None) -> None:
        if provider is None:
            return
        close = getattr(provider, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - cleanup must not block switching
                return

    def close(self) -> None:
        self._close_provider(self._provider)

    def delete_service_credentials(self, service: str) -> ServiceSettingsDTO:
        if service == "provider":
            current = self.settings()
            if current.longbridge_client_id:
                self._longbridge_oauth.clear(current.longbridge_client_id)
        result = self._settings_store.delete_credentials(service)
        if service == "provider":
            result = self._settings_store.save(
                ServiceSettingsInput(
                    result.provider_mode,
                    result.timeout_seconds,
                    result.max_retries,
                    result.ai_base_url,
                    result.ai_model,
                    result.developer_mode_enabled,
                    "",
                )
            )
        self._reload_adapters()
        return result


def build_application(
    environment: RuntimeEnvironment,
    *,
    home: Path,
    scenario_run_id: str | None = None,
    provider_override: ApplicationProvider | None = None,
    ai_override: AICompanyAnalysisPort | None = None,
    rs_report_override: TechnicalReportAdapter | None = None,
    diagnostics_override: DiagnosticLogger | None = None,
    futu_opend_override: FutuOpenDPort | None = None,
) -> StockToolboxApplication:
    clock = lambda: datetime.now(UTC)
    resolved_home = home.expanduser().resolve()
    paths = RuntimePaths.resolve(
        environment,
        home=home,
        scenario_run_id=scenario_run_id,
    )
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.log_root.mkdir(parents=True, exist_ok=True)
    paths.exports_root.mkdir(parents=True, exist_ok=True)
    new_id = lambda: str(uuid.uuid4())
    diagnostics: DiagnosticLogger = (
        diagnostics_override
        if diagnostics_override is not None
        else (
            JsonlDiagnosticLogger(
                paths.log_root,
                app_version=__version__,
            )
            if environment
            in {
                RuntimeEnvironment.PRODUCTION,
                RuntimeEnvironment.DEVELOPMENT,
            }
            and resolved_home == Path.home().resolve()
            else NullDiagnosticLogger()
        )
    )
    MigrationRunner(
        paths.database,
        app_version=__version__,
        now=clock,
    ).bootstrap()
    factory = SQLiteConnectionFactory(
        paths.database,
        diagnostics=diagnostics,
    )
    registry = OperationRegistry(clock=clock, diagnostics=diagnostics)
    global_ai_store = GlobalAIConfigStore(
        paths.global_ai_database,
        clock=clock,
        new_id=new_id,
    )
    oauth_service = LongbridgeOAuthService(
        home=home.expanduser().resolve(),
    )
    futu_opend = futu_opend_override or FutuOpenDService()
    settings_store = ServiceSettingsStore(
        factory,
        global_ai_store,
        clock=clock,
        new_id=new_id,
        oauth_token_present=oauth_service.is_authorized,
        default_provider_mode=(
            "longbridge"
            if environment
            in {
                RuntimeEnvironment.PRODUCTION,
                RuntimeEnvironment.DEVELOPMENT,
            }
            else "virtual"
        ),
    )

    def adapters() -> tuple[
        ApplicationProvider,
        AICompanyAnalysisPort,
    ]:
        settings = settings_store.load()
        apply_proxy_environment(settings.proxy_mode, settings.proxy_url)
        if settings.provider_mode == "longbridge":
            provider: ApplicationProvider = (
                _longbridge_provider(
                    settings,
                    oauth_service,
                )
                if settings.provider_configured
                else UnavailableProvider("longbridge", "Longbridge")
            )
        elif settings.provider_mode == "futu":
            if settings.provider_configured:
                try:
                    provider = _futu_provider(settings)
                except Exception:  # noqa: BLE001 - disconnected OpenD is recoverable
                    provider = UnavailableProvider("futu", "富途")
            else:
                provider = UnavailableProvider("futu", "富途")
        else:
            provider = VirtualProvider()
        ai_config = settings_store.global_ai_config()
        if environment in {
            RuntimeEnvironment.SCENARIO,
            RuntimeEnvironment.INTEGRATION,
        }:
            ai: AICompanyAnalysisPort = VirtualAI()
        elif ai_config is not None:
            ai = OpenAICompatibleAI(
                AIServiceConfig(
                    ai_config.base_url,
                    ai_config.model,
                    ai_config.revision,
                    Decimal(ai_config.timeout_seconds),
                    ai_config.max_retries,
                ),
                global_ai_store,
            )
        else:
            ai = VirtualAI() if settings.provider_mode == "virtual" else UnavailableAI()
        return provider, ai

    provider, ai = adapters()
    if provider_override is not None:
        provider = provider_override
    if ai_override is not None:
        ai = ai_override
    master_data = SQLiteMasterDataStore(
        factory,
        clock=clock,
        new_id=new_id,
    )
    import_service = ImportSecurities(
        provider,
        ai,
        PersistentSecurityImportStore(factory),
        clock=clock,
        new_id=new_id,
    )
    history = HistoryService(factory, clock=clock, new_id=new_id)
    analysis_payloads = AnalysisPayloadStore(factory)
    analyses = build_analysis_registry()
    return StockToolboxApplication(
        paths,
        resolved_home,
        diagnostics,
        factory,
        registry,
        analyses,
        master_data,
        import_service,
        provider,
        ai,
        history,
        analysis_payloads,
        settings_store,
        adapters,
        oauth_service,
        futu_opend,
        global_ai_store,
        StorageGuard(
            paths.data_root,
            SQLiteRecomputableCacheCleaner(factory),
        ),
        rs_report_override,
        clock,
        new_id,
    )


def build_analysis_registry() -> AnalysisRegistry:
    """Return the explicit set of product-shipped analysis modules."""

    analyses = AnalysisRegistry()
    analyses.register(RSStrengthModule())
    analyses.register(TurningPointModule())
    analyses.register(ExtremeDeviationModule())
    return analyses


def _longbridge_provider(
    settings: ServiceSettingsDTO,
    oauth_service: LongbridgeOAuthService,
) -> LongbridgeProvider:
    contexts = oauth_service.contexts(
        settings.longbridge_client_id,
    )
    return LongbridgeProvider(
        contexts.quote,
        fundamental_context=contexts.fundamental,
        async_quote_factory=contexts.async_quote_factory,
        quant_http_factory=contexts.quant_http_factory,
        max_retries=settings.max_retries,
        quant_request_interval_seconds=0.125,
    )


def _futu_provider(settings: ServiceSettingsDTO) -> FutuProvider:
    context = FutuQuoteContextFactory(
        settings.futu_opend_host,
        settings.futu_opend_port,
    ).create()
    return FutuProvider(
        cast(FutuQuotePort, context),
        max_retries=settings.max_retries,
    )


class UnavailableProvider:
    def __init__(
        self,
        provider_id: str = "longbridge",
        provider_display_name: str = "Longbridge",
    ) -> None:
        self.provider_id = provider_id
        self.provider_display_name = provider_display_name
        self.quant_script_versions = (
            frozenset(
                {
                    DAILY_QUANT_VERSION,
                    TURNING_QUANT_VERSION,
                }
            )
            if provider_id == "longbridge"
            else frozenset()
        )

    def latest_completed_trading_day(
        self,
        *,
        operation_control: OperationControl,
        on_or_before: date | None = None,
    ) -> date | None:
        del operation_control, on_or_before
        return None

    def get_security_profiles(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> ProviderProfilesResult:
        return ProviderProfilesResult(
            (),
            tuple(
                ProviderProfileError(
                    symbol,
                    "configuration_invalid",
                )
                for symbol in symbols
            ),
            self.provider_id,
        )

    def get_daily_series(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        *,
        operation_control: OperationControl,
        progress: DailySeriesProgressSink | None = None,
    ) -> BarsResult:
        if progress is not None:
            for completed, symbol in enumerate(symbols, start=1):
                progress(
                    DailySeriesProgress(
                        completed,
                        len(symbols),
                        symbol,
                        0,
                        completed,
                    )
                )
        return BarsResult(
            self.provider_id,
            self.provider_display_name,
            {},
            {symbol: "configuration_invalid" for symbol in symbols},
        )

    def get_security_snapshots(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: OperationControl,
    ) -> SnapshotDataset:
        del operation_control
        return SnapshotDataset(
            self.provider_id,
            self.provider_display_name,
            {},
            {symbol: "configuration_invalid" for symbol in symbols},
        )

    def get_candle_series(
        self,
        symbols: tuple[str, ...],
        interval: CandleInterval,
        count: int,
        end_at: datetime,
        *,
        operation_control: OperationControl,
    ) -> CandleDataset:
        del count, end_at, operation_control
        return CandleDataset(
            self.provider_id,
            self.provider_display_name,
            interval,
            {},
            {symbol: "configuration_invalid" for symbol in symbols},
        )

    def get_quant_series(
        self,
        symbols: tuple[str, ...],
        request: QuantSeriesRequest,
        *,
        operation_control: OperationControl,
        progress: QuantProgressSink | None = None,
    ) -> QuantSeriesDataset:
        del request, operation_control
        if progress is not None:
            for completed, symbol in enumerate(symbols, start=1):
                progress(
                    QuantProgress(
                        completed,
                        len(symbols),
                        symbol,
                        0,
                        completed,
                    )
                )
        return QuantSeriesDataset(
            self.provider_id,
            self.provider_display_name,
            {},
            {symbol: "configuration_invalid" for symbol in symbols},
        )


class UnavailableAI:
    def analyze_company(
        self,
        profile: ProviderProfile,
        existing: tuple[StoredClassification, ...],
        *,
        operation_control: OperationControl,
    ) -> AICompanyAnalysis:
        del profile, existing, operation_control
        raise RuntimeError("ai_configuration_invalid")
