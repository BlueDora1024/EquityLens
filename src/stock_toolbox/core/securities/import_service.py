"""Parse, validate, classify, and atomically commit a security import."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from stock_toolbox.core.operations.registry import OperationExecutionContext
from stock_toolbox.core.securities.models import (
    AIClassification,
    AICompanyAnalysisPort,
    Clock,
    IdGenerator,
    ProviderProfile,
    SecurityImportStorePort,
    SecurityProfilesPort,
    StoredClassification,
    ValidatedClassification,
    ValidatedImportBatch,
    ValidatedSecurityImport,
)

_TOKEN_SPLIT = re.compile(r"[\s,;]+")
_BASE_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")
_CJK_CHARACTER = re.compile(r"[\u3400-\u9fff]")
_HEADERS = frozenset({"ticker", "tickers", "symbol", "symbols"})
_ELIGIBLE_TYPES = frozenset({"COMMON_STOCK", "ADR"})
_EXCLUDED_TYPES = frozenset(
    {
        "ETF",
        "LEVERAGED_ETF",
        "INVERSE_ETF",
        "REIT",
        "FUND",
        "CRYPTO",
        "CRYPTO_CONTRACT",
        "OPTION",
        "FUTURE",
        "WARRANT",
        "BOND",
        "PREFERRED_STOCK",
        "OTC",
    }
)
_PROVIDER_CLASSIFICATION_NAMES = {
    "technology": "科技",
    "information technology": "科技",
    "semiconductors": "半导体",
    "semiconductor": "半导体",
    "software": "软件",
    "cloud computing": "云计算",
    "communication services": "通信服务",
    "consumer discretionary": "可选消费",
    "consumer staples": "必选消费",
    "financials": "金融",
    "financial services": "金融",
    "healthcare": "医疗健康",
    "health care": "医疗健康",
    "industrials": "工业",
    "energy": "能源",
    "utilities": "公用事业",
    "materials": "材料",
    "real estate": "房地产",
    "ai data center": "AI 数据中心",
    "bitcoin mining": "比特币矿业",
    "energy infrastructure": "能源基础设施",
    "ai infrastructure": "AI 基础设施",
    "consumer technology": "消费科技",
    "digital services": "数字服务",
    "enterprise software": "企业软件",
}


class ImportStatus(StrEnum):
    IMPORTED = "IMPORTED"
    IMPORTED_PENDING_CLASSIFICATION = "IMPORTED_PENDING_CLASSIFICATION"
    EXISTING = "EXISTING"
    INVALID_INPUT = "INVALID_INPUT"
    UNAVAILABLE = "UNAVAILABLE"
    EXCLUDED = "EXCLUDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ImportItemResult:
    symbol: str
    status: ImportStatus
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ImportResult:
    items: tuple[ImportItemResult, ...]
    duplicate_input_symbols: tuple[str, ...]
    committed: bool

    @property
    def success_symbols(self) -> tuple[str, ...]:
        return tuple(
            item.symbol
            for item in self.items
            if item.status
            in {
                ImportStatus.IMPORTED,
                ImportStatus.IMPORTED_PENDING_CLASSIFICATION,
            }
        )

    @property
    def success_count(self) -> int:
        return len(self.success_symbols)

    @property
    def existing_symbols(self) -> tuple[str, ...]:
        return self._symbols(ImportStatus.EXISTING)

    @property
    def invalid_inputs(self) -> tuple[str, ...]:
        return self._symbols(ImportStatus.INVALID_INPUT)

    @property
    def unavailable(self) -> tuple[tuple[str, str], ...]:
        return self._with_reason(ImportStatus.UNAVAILABLE)

    @property
    def excluded(self) -> tuple[tuple[str, str], ...]:
        return self._with_reason(ImportStatus.EXCLUDED)

    def _symbols(self, status: ImportStatus) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.items if item.status is status)

    def _with_reason(
        self,
        status: ImportStatus,
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            (item.symbol, item.reason or "") for item in self.items if item.status is status
        )


@dataclass(frozen=True, slots=True)
class ImportProgress:
    stage: str
    completed: int
    total: int
    symbol: str = ""
    status: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class _ParsedInput:
    symbols: tuple[str, ...]
    invalid: tuple[str, ...]
    duplicates: tuple[str, ...]


class ImportSecurities:
    def __init__(
        self,
        provider: SecurityProfilesPort,
        ai: AICompanyAnalysisPort,
        store: SecurityImportStorePort,
        *,
        clock: Clock,
        new_id: IdGenerator,
    ) -> None:
        self._provider = provider
        self._ai = ai
        self._store = store
        self._clock = clock
        self._new_id = new_id

    def execute(
        self,
        raw_input: str,
        context: OperationExecutionContext,
        *,
        progress: Callable[[ImportProgress], None] = lambda _item: None,
    ) -> ImportResult:
        parsed = self._parse(raw_input)
        total = (
            len(parsed.symbols)
            + len(parsed.invalid)
            + len(parsed.duplicates)
        )
        completed = 0
        item_results: list[ImportItemResult] = []
        progress(ImportProgress("PARSING", completed, total))

        def record(item: ImportItemResult, *, stage: str = "ITEM") -> None:
            nonlocal completed
            item_results.append(item)
            completed += 1
            progress(
                ImportProgress(
                    stage,
                    completed,
                    total,
                    item.symbol,
                    item.status.value,
                    item.reason or "",
                )
            )

        for value in parsed.invalid:
            record(
                ImportItemResult(
                    value,
                    ImportStatus.INVALID_INPUT,
                    "invalid_symbol",
                )
            )
        for symbol in parsed.duplicates:
            completed += 1
            progress(
                ImportProgress(
                    "ITEM",
                    completed,
                    total,
                    symbol,
                    "DUPLICATE",
                    "本批只处理首次出现项",
                )
            )
        existing = self._store.existing_symbols(parsed.symbols)
        for symbol in parsed.symbols:
            if symbol in existing:
                record(ImportItemResult(symbol, ImportStatus.EXISTING))
        requested = tuple(symbol for symbol in parsed.symbols if symbol not in existing)
        if not requested:
            progress(ImportProgress("DONE", total, total))
            return ImportResult(tuple(item_results), parsed.duplicates, True)

        progress(ImportProgress("FETCHING_PROFILES", completed, total))
        profiles_result = self._provider.get_security_profiles(
            requested,
            operation_control=context.operation_control,
        )
        errors = {error.symbol: error for error in profiles_result.errors}
        profiles = {profile.symbol: profile for profile in profiles_result.profiles}
        existing_classifications = self._store.list_classifications()
        classification_context = existing_classifications
        batch_classifications: dict[str, tuple[str, str]] = {}
        imports = []
        progress(ImportProgress("CLASSIFYING", completed, total))
        for symbol in requested:
            if symbol in errors:
                record(
                    ImportItemResult(
                        symbol,
                        ImportStatus.UNAVAILABLE,
                        errors[symbol].code,
                    )
                )
                continue
            profile = profiles.get(symbol)
            if profile is None:
                record(
                    ImportItemResult(
                        symbol,
                        ImportStatus.UNAVAILABLE,
                        "provider_incomplete",
                    )
                )
                continue
            outcome = self._prepare_import(
                profile,
                classification_context,
                batch_classifications,
                context,
            )
            if isinstance(outcome, ImportItemResult):
                record(outcome)
                continue
            imports.append(outcome)
            known_ids = {item.id for item in classification_context}
            classification_context += tuple(
                StoredClassification(
                    item.id,
                    item.display_name,
                    item.normalized_name,
                )
                for item in outcome.classifications
                if item.id not in known_ids
            )
            record(
                ImportItemResult(
                    symbol,
                    (
                        ImportStatus.IMPORTED
                        if outcome.classifications
                        else ImportStatus.IMPORTED_PENDING_CLASSIFICATION
                    ),
                )
            )
        if not imports:
            progress(ImportProgress("DONE", total, total))
            return ImportResult(tuple(item_results), parsed.duplicates, True)
        progress(ImportProgress("SAVING", completed, total))
        committed = self._store.commit(
            ValidatedImportBatch(
                tuple(imports),
                self._clock(),
                profiles_result.provider_id,
            ),
            operation_control=context.operation_control,
        )
        if not committed:
            imported_symbols = {item.profile.symbol for item in imports}
            item_results = [
                (
                    ImportItemResult(
                        item.symbol,
                        ImportStatus.FAILED,
                        "commit_canceled_or_failed",
                    )
                    if item.symbol in imported_symbols
                    else item
                )
                for item in item_results
            ]
        progress(ImportProgress("DONE", total, total))
        return ImportResult(tuple(item_results), parsed.duplicates, committed)

    def _prepare_import(
        self,
        profile: ProviderProfile,
        existing: tuple[StoredClassification, ...],
        batch_classifications: dict[str, tuple[str, str]],
        context: OperationExecutionContext,
    ) -> ValidatedSecurityImport | ImportItemResult:
        asset_type, reliable = self._asset_type(profile)
        if reliable and asset_type in _EXCLUDED_TYPES:
            return ImportItemResult(
                profile.symbol,
                ImportStatus.EXCLUDED,
                asset_type,
            )
        eligibility_source = "PROVIDER"
        if not reliable or asset_type not in _ELIGIBLE_TYPES:
            try:
                analysis = self._ai.analyze_company(
                    profile,
                    existing,
                    operation_control=context.operation_control,
                )
            except Exception:  # noqa: BLE001 - external adapter boundary
                return ImportItemResult(
                    profile.symbol,
                    ImportStatus.FAILED,
                    "eligibility_unresolved",
                )
            if not analysis.eligible:
                return ImportItemResult(
                    profile.symbol,
                    ImportStatus.EXCLUDED,
                    analysis.asset_type,
                )
            asset_type = analysis.asset_type
            eligibility_source = "AI"
            classifications = self._classifications(
                analysis.classifications,
                existing,
                batch_classifications,
            )
        else:
            try:
                analysis = self._ai.analyze_company(
                    profile,
                    existing,
                    operation_control=context.operation_control,
                )
                classifications = self._classifications(
                    analysis.classifications,
                    existing,
                    batch_classifications,
                )
            except Exception:  # noqa: BLE001 - eligible stock remains pending
                classifications = self._classifications(
                    self._provider_classifications(profile, existing),
                    existing,
                    batch_classifications,
                )
        return ValidatedSecurityImport(
            id=self._new_id(),
            receipt_id=self._new_id(),
            profile=profile,
            asset_type=asset_type,
            eligibility_source=eligibility_source,
            classifications=classifications,
        )

    def _classifications(
        self,
        proposals: tuple[AIClassification, ...],
        existing: tuple[StoredClassification, ...],
        batch_classifications: dict[str, tuple[str, str]],
    ) -> tuple[ValidatedClassification, ...]:
        existing_by_id = {item.id: item for item in existing}
        existing_by_name = {
            normalized: item
            for item in existing
            for normalized in (
                item.normalized_name,
                *(alias.casefold() for alias in item.aliases),
            )
        }
        output = []
        seen = set()
        for raw in proposals[:3]:
            proposal = raw
            classification_id = proposal.existing_classification_id
            if classification_id is not None and classification_id in existing_by_id:
                stored = existing_by_id[classification_id]
                display_name = stored.display_name
                normalized = stored.normalized_name
            else:
                proposed_name = " ".join(proposal.canonical_name.split())
                display_name = _PROVIDER_CLASSIFICATION_NAMES.get(
                    proposed_name.casefold(),
                    proposed_name,
                )
                normalized = display_name.casefold()
                stored_by_name = existing_by_name.get(normalized)
                batch_identity = batch_classifications.get(normalized)
                if stored_by_name is not None:
                    classification_id = stored_by_name.id
                    display_name = stored_by_name.display_name
                elif not _CJK_CHARACTER.search(display_name):
                    continue
                elif batch_identity is None:
                    classification_id = self._new_id()
                    batch_classifications[normalized] = (
                        classification_id,
                        display_name,
                    )
                else:
                    classification_id, display_name = batch_identity
            if normalized in seen or not display_name:
                continue
            seen.add(normalized)
            output.append(
                ValidatedClassification(
                    classification_id,
                    self._new_id(),
                    display_name,
                    normalized,
                    proposal.confidence,
                )
            )
        return tuple(output)

    @staticmethod
    def _provider_classifications(
        profile: ProviderProfile,
        existing: tuple[StoredClassification, ...],
    ) -> tuple[AIClassification, ...]:
        company = profile.business_profile.get("company")
        if not isinstance(company, dict):
            return ()
        existing_by_name = {
            item.normalized_name: item.id
            for item in existing
        }
        output: list[AIClassification] = []
        seen: set[str] = set()
        for key in ("sector", "category"):
            raw = company.get(key)
            if not isinstance(raw, str):
                continue
            localized = _PROVIDER_CLASSIFICATION_NAMES.get(raw.strip().casefold())
            if localized is None or localized in seen:
                continue
            seen.add(localized)
            output.append(
                AIClassification(
                    localized,
                    existing_by_name.get(localized.casefold()),
                    Decimal("0.60"),
                )
            )
        return tuple(output[:3])

    @staticmethod
    def _asset_type(profile: ProviderProfile) -> tuple[str, bool]:
        reliable = {
            hint.normalized_type for hint in profile.asset_hints if hint.reliability == "reliable"
        }
        if len(reliable) == 1:
            return next(iter(reliable)), True
        return "UNKNOWN", False

    @staticmethod
    def _parse(raw_input: str) -> _ParsedInput:
        symbols = []
        invalid = []
        duplicates = []
        seen = set()
        for raw in _TOKEN_SPLIT.split(raw_input.replace("\ufeff", "").strip()):
            token = raw.strip()
            if not token or token.casefold() in _HEADERS:
                continue
            upper = token.upper()
            base = upper.removesuffix(".US")
            if not _BASE_SYMBOL.fullmatch(base):
                invalid.append(token)
                continue
            symbol = f"{base}.US"
            if symbol in seen:
                duplicates.append(symbol)
                continue
            seen.add(symbol)
            symbols.append(symbol)
        return _ParsedInput(tuple(symbols), tuple(invalid), tuple(duplicates))
