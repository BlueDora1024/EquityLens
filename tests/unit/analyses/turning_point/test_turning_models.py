from stock_toolbox.analyses.turning_point.application.models import (
    PeriodScreenResult,
    SymbolTurningResult,
)
from stock_toolbox.core.market_data.models import CandleInterval


def test_symbol_result_only_keeps_market_value_risk_annotations() -> None:
    result = SymbolTurningResult.build(
        "IREN.US",
        "IREN",
        "数据中心",
        (
            PeriodScreenResult(
                CandleInterval.DAY,
                "MATCHED",
                "matched",
            ),
        ),
    )

    assert result.market_value_usd is None
    assert result.risk_flags == ()
    assert not hasattr(result, "return_250d")
    assert not hasattr(result, "risk_annotation_status")
