from __future__ import annotations

from pathlib import Path

from stock_toolbox.composition import build_application
from stock_toolbox.core.market_data.models import SnapshotDataset
from stock_toolbox.core.securities.models import (
    ProviderProfileError,
    ProviderProfilesResult,
)
from stock_toolbox.runtime.environment import RuntimeEnvironment


class _UnavailableSecurityProvider:
    provider_id = "test"

    def get_security_profiles(
        self,
        symbols,
        *,
        operation_control,
    ) -> ProviderProfilesResult:
        del operation_control
        return ProviderProfilesResult(
            (),
            tuple(
                ProviderProfileError(symbol, "symbol_unavailable")
                for symbol in symbols
            ),
            self.provider_id,
        )

    def get_security_snapshots(
        self,
        symbols,
        *,
        operation_control,
    ) -> SnapshotDataset:
        del operation_control
        return SnapshotDataset(
            self.provider_id,
            "Test",
            {},
            {symbol: "symbol_unavailable" for symbol in symbols},
        )


def test_global_refresh_marks_missing_security_unavailable_without_deleting_it(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="global-refresh",
    )
    application.import_securities("IREN")
    security = application.master_data.list_securities()[0]
    application.refresh_all_security_profiles()
    before = application.master_data.get_security(security.id)
    before_refresh = before.business_profile["refresh"]
    application._provider = _UnavailableSecurityProvider()  # type: ignore[assignment]

    result = application.refresh_all_security_profiles()

    refreshed = application.master_data.get_security(security.id)
    assert result.updated_count == 0
    assert result.unavailable_count == 1
    assert refreshed.business_profile["refresh"]["status"] == "UNAVAILABLE"
    assert (
        refreshed.business_profile["refresh"]["last_price"]
        == before_refresh["last_price"]
    )
    assert (
        refreshed.business_profile["refresh"]["market_value"]
        == before_refresh["market_value"]
    )
    assert application.master_data.list_securities() == (refreshed,)
