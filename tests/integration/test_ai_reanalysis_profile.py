from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from stock_toolbox.composition import build_application
from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.core.securities.models import (
    AIClassification,
    AICompanyAnalysis,
    ProviderProfile,
    StoredClassification,
)
from stock_toolbox.infrastructure.virtual.provider import VirtualProvider
from stock_toolbox.runtime.environment import RuntimeEnvironment


class RecordingAI:
    def __init__(self) -> None:
        self.profiles: list[ProviderProfile] = []

    def analyze_company(
        self,
        profile: ProviderProfile,
        existing: tuple[StoredClassification, ...],
        *,
        operation_control: OperationControl,
    ) -> AICompanyAnalysis:
        del existing, operation_control
        self.profiles.append(profile)
        return AICompanyAnalysis(
            True,
            "COMMON_STOCK",
            (
                AIClassification(
                    "AI Data Center",
                    None,
                    Decimal("0.91"),
                ),
            ),
        )


def test_reanalysis_reuses_stored_provider_business_profile(
    tmp_path: Path,
) -> None:
    ai = RecordingAI()
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="ai-reanalysis-business-profile",
        ai_override=ai,
    )
    imported = application.import_securities("IREN")
    assert imported.success_count == 1
    security = application.master_data.list_securities()[0]
    application.master_data.refresh_security_profile(
        security.id,
        ProviderProfile(
            "IREN.US",
            "IREN Limited",
            "US",
            "NASDAQ",
            "USD",
            "US",
            "Operates AI data centers.",
            (),
            {
                "company": {
                    "sector": "123",
                    "category": "Technology",
                }
            },
            datetime(2026, 7, 26, tzinfo=UTC),
        ),
        provider_id="longbridge",
    )
    ai.profiles.clear()

    result = application.reanalyze_security(security.id)

    assert result.ok
    assert ai.profiles[0].business_profile == {
        "company": {
            "sector": "123",
            "category": "Technology",
        }
    }


def test_live_classification_check_uses_real_provider_profile(
    tmp_path: Path,
) -> None:
    ai = RecordingAI()
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="live-provider-to-ai-profile",
        provider_override=VirtualProvider(),
        ai_override=ai,
    )

    result = application.test_profile_ai_classification("IREN.US")

    assert result.ok
    assert ai.profiles[0].symbol == "IREN.US"
    assert ai.profiles[0].description is not None
    assert "data center" in ai.profiles[0].description.casefold()
    assert application.master_data.list_securities() == ()
    assert application.list_history() == ()
