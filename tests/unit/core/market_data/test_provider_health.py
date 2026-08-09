from __future__ import annotations

import pytest

from stock_toolbox.core.market_data.provider_health import (
    HistoryQuotaSnapshot,
    ProviderIdentity,
    ProviderQualityResult,
)


def test_history_quota_normalizes_reusable_symbols() -> None:
    quota = HistoryQuotaSnapshot(
        used=2,
        remaining=98,
        reusable_symbols=frozenset({"us.aapl", "US.NVDA"}),
    )

    assert quota.reusable_symbols == frozenset({"US.AAPL", "US.NVDA"})
    assert quota.total == 100


@pytest.mark.parametrize(("used", "remaining"), ((-1, 1), (1, -1)))
def test_history_quota_rejects_negative_values(
    used: int,
    remaining: int,
) -> None:
    with pytest.raises(ValueError):
        HistoryQuotaSnapshot(used, remaining, frozenset())


def test_provider_identity_requires_supported_provider() -> None:
    assert ProviderIdentity("futu", "富途").configured
    with pytest.raises(ValueError):
        ProviderIdentity("", "富途")


def test_provider_quality_normalizes_completed_checks() -> None:
    result = ProviderQualityResult(
        "futu",
        True,
        "PROVIDER_OK",
        ("opend", "opend", "quote_login"),
    )

    assert result.completed_checks == ("opend", "quote_login")
