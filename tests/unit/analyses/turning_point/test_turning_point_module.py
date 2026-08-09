from stock_toolbox.analyses.turning_point.module import TurningPointModule


def test_descriptor_declares_shared_market_requirements() -> None:
    descriptor = TurningPointModule().descriptor
    assert descriptor.analysis_id == "turning_point"
    assert descriptor.display_name == "拐点筛选"
    assert descriptor.requirements.ohlc_bars
    assert descriptor.requirements.quant_series
    assert descriptor.requirements.security_snapshots
    assert descriptor.requirements.trading_calendar
