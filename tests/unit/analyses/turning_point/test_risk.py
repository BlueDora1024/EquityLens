from stock_toolbox.analyses.turning_point.application.risk import (
    build_risk_annotation,
)


def test_risk_annotation_only_flags_market_value() -> None:
    assert build_risk_annotation(1_900_000_000) == ("SMALL_MARKET_CAP",)
    assert build_risk_annotation(20_000_000_000) == ()
    assert build_risk_annotation(None) == ("MARKET_VALUE_UNKNOWN",)
