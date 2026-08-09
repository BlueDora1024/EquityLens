from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from stock_toolbox.core.operations.registry import OperationRegistry
from stock_toolbox.core.securities.import_service import (
    ImportProgress,
    ImportSecurities,
    ImportStatus,
)
from stock_toolbox.core.securities.models import (
    AIClassification,
    AICompanyAnalysis,
    AssetHint,
    ProviderProfile,
    ProviderProfileError,
    ProviderProfilesResult,
    StoredClassification,
    ValidatedImportBatch,
)

NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)


@dataclass
class Provider:
    profiles: dict[str, ProviderProfile]
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def get_security_profiles(
        self,
        symbols: tuple[str, ...],
        *,
        operation_control: object,
    ) -> ProviderProfilesResult:
        self.calls.append(symbols)
        found = tuple(self.profiles[symbol] for symbol in symbols if symbol in self.profiles)
        errors = tuple(
            ProviderProfileError(symbol, "symbol_unavailable")
            for symbol in symbols
            if symbol not in self.profiles
        )
        return ProviderProfilesResult(found, errors)


@dataclass
class AI:
    results: dict[str, AICompanyAnalysis]
    calls: list[str] = field(default_factory=list)

    def analyze_company(
        self,
        profile: ProviderProfile,
        existing: tuple[StoredClassification, ...],
        *,
        operation_control: object,
    ) -> AICompanyAnalysis:
        self.calls.append(profile.symbol)
        return self.results[profile.symbol]


@dataclass
class Store:
    existing: set[str] = field(default_factory=set)
    classifications: tuple[StoredClassification, ...] = ()
    batches: list[ValidatedImportBatch] = field(default_factory=list)

    def existing_symbols(self, symbols: tuple[str, ...]) -> frozenset[str]:
        return frozenset(symbol for symbol in symbols if symbol in self.existing)

    def list_classifications(self) -> tuple[StoredClassification, ...]:
        return self.classifications

    def commit(
        self,
        batch: ValidatedImportBatch,
        *,
        operation_control: object,
    ) -> bool:
        self.batches.append(batch)
        return True


def profile(symbol: str, asset_type: str, reliability: str = "reliable") -> ProviderProfile:
    return ProviderProfile(
        symbol=symbol,
        name=symbol.removesuffix(".US"),
        market="US",
        exchange="NASDAQ",
        currency="USD",
        listing_country="US",
        description=f"{symbol} company",
        asset_hints=(AssetHint(asset_type, reliability),),
        business_profile={},
        source_updated_at=NOW,
    )


def context():
    registry = OperationRegistry(clock=lambda: NOW)
    registry.reserve("op-1", "key", "security_import")
    result = registry.begin_reserved("op-1")
    assert result is not None
    return result


def test_parser_normalizes_first_occurrence_and_reports_invalid_and_duplicate() -> None:
    provider = Provider({"AAPL.US": profile("AAPL.US", "COMMON_STOCK")})
    service = ImportSecurities(provider, AI({}), Store(), clock=lambda: NOW, new_id=lambda: "id")

    result = service.execute(" ticker\n aapl\nAAPL.US\nbad/us\n", context())

    assert provider.calls == [("AAPL.US",)]
    assert result.success_count == 1
    assert result.duplicate_input_symbols == ("AAPL.US",)
    assert result.invalid_inputs == ("bad/us",)


def test_import_progress_reports_total_and_each_terminal_item() -> None:
    provider = Provider({"AAPL.US": profile("AAPL.US", "COMMON_STOCK")})
    service = ImportSecurities(
        provider,
        AI({}),
        Store(),
        clock=lambda: NOW,
        new_id=lambda: "id",
    )
    events: list[ImportProgress] = []

    service.execute(
        "AAPL, AAPL, bad/us",
        context(),
        progress=events.append,
    )

    item_events = [event for event in events if event.symbol]
    assert all(event.total == 3 for event in events)
    assert [(event.symbol, event.status) for event in item_events] == [
        ("bad/us", "INVALID_INPUT"),
        ("AAPL.US", "DUPLICATE"),
        ("AAPL.US", "IMPORTED_PENDING_CLASSIFICATION"),
    ]
    assert item_events[-1].completed == 3


def test_existing_is_skipped_and_profiles_are_requested_once_for_remaining() -> None:
    provider = Provider({"NVDA.US": profile("NVDA.US", "COMMON_STOCK")})
    store = Store(existing={"AAPL.US"})
    service = ImportSecurities(provider, AI({}), store, clock=lambda: NOW, new_id=lambda: "id")

    result = service.execute("AAPL, NVDA", context())

    assert result.existing_symbols == ("AAPL.US",)
    assert provider.calls == [("NVDA.US",)]
    assert result.success_symbols == ("NVDA.US",)


def test_unavailable_and_excluded_assets_are_separate_results() -> None:
    provider = Provider({"TQQQ.US": profile("TQQQ.US", "LEVERAGED_ETF")})
    service = ImportSecurities(provider, AI({}), Store(), clock=lambda: NOW, new_id=lambda: "id")

    result = service.execute("MISSING TQQQ", context())

    assert result.unavailable == (("MISSING.US", "symbol_unavailable"),)
    assert result.excluded == (("TQQQ.US", "LEVERAGED_ETF"),)
    assert result.success_count == 0


def test_uncertain_asset_uses_ai_and_applies_at_most_three_classifications() -> None:
    uncertain = profile("IREN.US", "UNKNOWN", "ambiguous")
    ai = AI(
        {
            "IREN.US": AICompanyAnalysis(
                eligible=True,
                asset_type="COMMON_STOCK",
                classifications=(
                    AIClassification("AI Data Center", None, Decimal("0.95")),
                    AIClassification("Bitcoin Mining", None, Decimal("0.90")),
                    AIClassification("Energy Infrastructure", None, Decimal("0.75")),
                ),
            )
        }
    )
    store = Store()
    ids = iter(f"id-{number}" for number in range(20))
    service = ImportSecurities(Provider({"IREN.US": uncertain}), ai, store, clock=lambda: NOW, new_id=lambda: next(ids))

    result = service.execute("IREN", context())

    assert ai.calls == ["IREN.US"]
    assert result.success_symbols == ("IREN.US",)
    assert len(store.batches[0].items[0].classifications) == 3


def test_batch_ai_can_reuse_classification_proposed_by_previous_security() -> None:
    @dataclass
    class ReusingAI:
        seen_existing: list[tuple[StoredClassification, ...]] = field(
            default_factory=list
        )

        def analyze_company(
            self,
            profile: ProviderProfile,
            existing: tuple[StoredClassification, ...],
            *,
            operation_control: object,
        ) -> AICompanyAnalysis:
            self.seen_existing.append(existing)
            reusable = next(
                (
                    item
                    for item in existing
                    if item.display_name == "AI 基础设施"
                ),
                None,
            )
            return AICompanyAnalysis(
                eligible=True,
                asset_type="COMMON_STOCK",
                classifications=(
                    AIClassification(
                        "AI 基础设施",
                        reusable.id if reusable else None,
                        Decimal("0.92"),
                    ),
                ),
            )

    ai = ReusingAI()
    store = Store()
    ids = iter(f"id-{number}" for number in range(30))
    service = ImportSecurities(
        Provider(
            {
                symbol: profile(symbol, "COMMON_STOCK")
                for symbol in ("NVDA.US", "AMD.US")
            }
        ),
        ai,
        store,
        clock=lambda: NOW,
        new_id=lambda: next(ids),
    )

    service.execute("NVDA, AMD", context())

    assert ai.seen_existing[0] == ()
    assert [item.display_name for item in ai.seen_existing[1]] == [
        "AI 基础设施"
    ]
    classification_ids = {
        item.classifications[0].id for item in store.batches[0].items
    }
    assert len(classification_ids) == 1


def test_new_ai_classification_must_be_a_reusable_chinese_label() -> None:
    raw = profile("NVDA.US", "COMMON_STOCK")
    ai = AI(
        {
            "NVDA.US": AICompanyAnalysis(
                eligible=True,
                asset_type="COMMON_STOCK",
                classifications=(
                    AIClassification(
                        "Ultra Specific GPU Product 2026",
                        None,
                        Decimal("0.95"),
                    ),
                ),
            )
        }
    )
    store = Store()
    service = ImportSecurities(
        Provider({"NVDA.US": raw}),
        ai,
        store,
        clock=lambda: NOW,
        new_id=lambda: "id",
    )

    result = service.execute("NVDA", context())

    assert result.items[0].status is ImportStatus.IMPORTED_PENDING_CLASSIFICATION
    assert store.batches[0].items[0].classifications == ()


def test_eligible_security_is_saved_pending_when_business_ai_fails() -> None:
    class FailingAI(AI):
        def analyze_company(
            self,
            profile: ProviderProfile,
            existing: tuple[StoredClassification, ...],
            *,
            operation_control: object,
        ) -> AICompanyAnalysis:
            raise RuntimeError("model unavailable")

    service = ImportSecurities(
        Provider({"AMD.US": profile("AMD.US", "COMMON_STOCK")}),
        FailingAI({}),
        Store(),
        clock=lambda: NOW,
        new_id=lambda: "id",
    )

    result = service.execute("AMD", context())

    assert result.items[0].status is ImportStatus.IMPORTED_PENDING_CLASSIFICATION
    assert result.success_count == 1


def test_eligible_security_uses_coarse_chinese_provider_classification_when_ai_fails() -> None:
    class FailingAI(AI):
        def analyze_company(
            self,
            profile: ProviderProfile,
            existing: tuple[StoredClassification, ...],
            *,
            operation_control: object,
        ) -> AICompanyAnalysis:
            raise RuntimeError("AI is not configured")

    raw = profile("NVDA.US", "COMMON_STOCK")
    enriched = ProviderProfile(
        raw.symbol,
        "英伟达",
        raw.market,
        raw.exchange,
        raw.currency,
        raw.listing_country,
        "设计加速计算芯片和人工智能平台。",
        raw.asset_hints,
        {
            "company": {
                "sector": "Technology",
                "category": "Semiconductors",
            }
        },
        raw.source_updated_at,
    )
    store = Store()
    ids = iter(f"id-{number}" for number in range(20))
    service = ImportSecurities(
        Provider({"NVDA.US": enriched}),
        FailingAI({}),
        store,
        clock=lambda: NOW,
        new_id=lambda: next(ids),
    )

    result = service.execute("NVDA", context())

    assert result.items[0].status is ImportStatus.IMPORTED
    assert [
        item.display_name for item in store.batches[0].items[0].classifications
    ] == ["科技", "半导体"]


def test_provider_fallback_reuses_existing_chinese_classification() -> None:
    class FailingAI(AI):
        def analyze_company(
            self,
            profile: ProviderProfile,
            existing: tuple[StoredClassification, ...],
            *,
            operation_control: object,
        ) -> AICompanyAnalysis:
            raise RuntimeError("AI is not configured")

    raw = profile("NVDA.US", "COMMON_STOCK")
    enriched = ProviderProfile(
        raw.symbol,
        raw.name,
        raw.market,
        raw.exchange,
        raw.currency,
        raw.listing_country,
        raw.description,
        raw.asset_hints,
        {"company": {"category": "Technology"}},
        raw.source_updated_at,
    )
    stored = StoredClassification("existing-tech", "科技", "科技")
    store = Store(classifications=(stored,))
    ids = iter(f"id-{number}" for number in range(20))
    service = ImportSecurities(
        Provider({"NVDA.US": enriched}),
        FailingAI({}),
        store,
        clock=lambda: NOW,
        new_id=lambda: next(ids),
    )

    service.execute("NVDA", context())

    classification = store.batches[0].items[0].classifications[0]
    assert classification.id == "existing-tech"
    assert classification.display_name == "科技"
