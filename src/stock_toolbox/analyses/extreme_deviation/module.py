"""Product descriptor for extreme deviation."""

from __future__ import annotations

from stock_toolbox.analyses.contracts import (
    AnalysisDescriptor,
    DataRequirements,
)


class ExtremeDeviationModule:
    descriptor = AnalysisDescriptor(
        "extreme_deviation",
        "极值偏离",
        "1.0.0",
        "desktop/resources/toolbox.png",
        DataRequirements(
            ohlc_bars=True,
            quant_series=True,
            trading_calendar=True,
        ),
    )
