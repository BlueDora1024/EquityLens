"""Product descriptor for the turning-point screener."""

from __future__ import annotations

from stock_toolbox.analyses.contracts import (
    AnalysisDescriptor,
    DataRequirements,
)


class TurningPointModule:
    descriptor = AnalysisDescriptor(
        "turning_point",
        "拐点筛选",
        "1.0.0",
        "analyses/rs_strength/resources/rs-strength.png",
        DataRequirements(
            ohlc_bars=True,
            quant_series=True,
            security_snapshots=True,
            trading_calendar=True,
        ),
    )
