from stock_toolbox.analyses.extreme_deviation.module import ExtremeDeviationModule


def test_extreme_deviation_module_declares_shared_ohlc_requirement() -> None:
    descriptor = ExtremeDeviationModule().descriptor
    assert descriptor.analysis_id == "extreme_deviation"
    assert descriptor.display_name == "极值偏离"
    assert descriptor.requirements.ohlc_bars
    assert descriptor.requirements.quant_series
    assert descriptor.requirements.trading_calendar
