from __future__ import annotations

from datetime import date
from inspect import signature
from pathlib import Path

from stock_toolbox.analyses.extreme_deviation.application.models import (
    ExtremeDeviationRequest,
    ExtremeDeviationRunResult,
    ExtremeDeviationRunStatus,
)
from stock_toolbox.analyses.extreme_deviation.application.quant import (
    SCRIPT_VERSION as EXTREME_VERSION,
)
from stock_toolbox.analyses.turning_point.application.quant import (
    SCRIPT_VERSION as TURNING_VERSION,
)
from stock_toolbox.composition import StockToolboxApplication, build_application
from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.market_data.quant_daily import (
    SCRIPT_VERSION as DAILY_VERSION,
)
from stock_toolbox.infrastructure.providers.longbridge import (
    LongbridgeProvider,
)
from stock_toolbox.runtime.environment import RuntimeEnvironment


class Quote:
    pass


def test_longbridge_routes_only_compatible_algorithms_through_quant(
    tmp_path: Path,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="quant-routing",
    )
    application._provider = LongbridgeProvider(Quote())  # type: ignore[assignment]

    assert application._quant_market_data_for(DAILY_VERSION) is not None
    assert application._quant_market_data_for(TURNING_VERSION) is not None
    assert application._quant_market_data_for(EXTREME_VERSION) is None


def test_unknown_script_does_not_claim_quant_support(tmp_path: Path) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="quant-routing-unknown",
    )
    application._provider = LongbridgeProvider(Quote())  # type: ignore[assignment]

    assert application._quant_market_data_for("unknown-v1") is None


def test_analysis_entry_points_accept_one_run_scoped_fallback_consent() -> None:
    for method in (
        StockToolboxApplication.run,
        StockToolboxApplication.run_turning_point,
        StockToolboxApplication.run_extreme_deviation,
    ):
        assert "fallback_consent" in signature(method).parameters


def test_extreme_run_uses_raw_candles_even_when_longbridge_supports_quant(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application = build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="extreme-raw-routing",
    )
    application._provider = LongbridgeProvider(Quote())  # type: ignore[assignment]
    captured: list[object] = []

    class ServiceProbe:
        def __init__(self, *args, **kwargs) -> None:
            del args
            captured.append(kwargs.get("quant_market_data", "missing"))

        def execute(self, request, context) -> ExtremeDeviationRunResult:
            del request, context
            return ExtremeDeviationRunResult(ExtremeDeviationRunStatus.FAILED)

    monkeypatch.setattr(
        "stock_toolbox.composition.StartExtremeDeviationRun",
        ServiceProbe,
    )

    application.run_extreme_deviation(
        ExtremeDeviationRequest(
            "",
            (CandleInterval.MIN_30,),
            date(2026, 8, 7),
            security_id="security",
        )
    )

    assert captured == [None]
