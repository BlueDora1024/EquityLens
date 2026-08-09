"""Product descriptor for RS strength."""

from __future__ import annotations

from stock_toolbox.analyses.contracts import (
    AnalysisDescriptor,
    DataRequirements,
)


class RSStrengthModule:
    descriptor = AnalysisDescriptor(
        "rs_strength",
        "RS 强度",
        "1.0.0",
        "analyses/rs_strength/resources/rs-strength.png",
        DataRequirements(
            daily_bars=True,
            quant_series=True,
            trading_calendar=True,
        ),
    )
