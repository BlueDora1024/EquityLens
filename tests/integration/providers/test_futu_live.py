from __future__ import annotations

import os
from datetime import timedelta

import pytest

from stock_toolbox.infrastructure.providers.futu import FutuProvider
from stock_toolbox.infrastructure.providers.futu_factory import (
    FutuQuoteContextFactory,
)
from stock_toolbox.infrastructure.providers.futu_opend import FutuOpenDService


class _Control:
    def cancellation_requested(self) -> bool:
        return False


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_FUTU") != "1",
        reason="set RUN_LIVE_FUTU=1 for the explicit Futu OpenD smoke",
    ),
]


def test_futu_opend_aapl_read_only_capabilities() -> None:
    status = FutuOpenDService().probe()
    if not status.port_open:
        pytest.skip(
            "Futu OpenD is not logged in on 127.0.0.1:11111"
        )
    context = FutuQuoteContextFactory().create()
    provider = FutuProvider(context, minimum_request_interval=0)
    try:
        day = provider.latest_completed_trading_day(
            operation_control=_Control(),
        )
        assert day is not None
        profiles = provider.get_security_profiles(
            ("AAPL.US",),
            operation_control=_Control(),
        )
        assert profiles.profiles
        snapshots = provider.get_security_snapshots(
            ("AAPL.US",),
            operation_control=_Control(),
        )
        assert "AAPL.US" in snapshots.snapshots_by_symbol
        quota = provider.get_history_quota()
        assert quota.total > 0
        daily = provider.get_daily_series(
            ("AAPL.US",),
            day - timedelta(days=14),
            day,
            operation_control=_Control(),
        )
        assert daily.series_by_symbol["AAPL.US"].points
    finally:
        provider.close()
