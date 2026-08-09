"""Server-side derived-series definition for turning-point screening."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.market_data.quant import QuantSeriesRequest

SCRIPT_VERSION = "turning-point-quant-v3"
SERIES_NAMES = (
    "high",
    "close",
    "high_ema26",
    "high_ema89",
    "dif",
    "hist",
    "volume",
)
SCRIPT = """
indicator("Turning Point Core", calc_bars_count: 220);
let high_ema26 = ta.ema(high, 26);
let high_ema89 = ta.ema(high, 89);
let fast = ta.ema(close, 12);
let slow = ta.ema(close, 26);
let dif = fast - slow;
let dea = ta.ema(dif, 9);
let hist = (dif - dea) * 2.0;
plot(high, "high");
plot(close, "close");
plot(high_ema26, "high_ema26");
plot(high_ema89, "high_ema89");
plot(dif, "dif");
plot(hist, "hist");
plot(volume, "volume");
""".strip()

_LOOKBACK_DAYS = {
    CandleInterval.MIN_30: 90,
    CandleInterval.MIN_60: 180,
    CandleInterval.MIN_120: 360,
    CandleInterval.MIN_240: 720,
    CandleInterval.DAY: 400,
    CandleInterval.WEEK: 1_800,
}


def request_for(
    interval: CandleInterval,
    end_date: date,
) -> QuantSeriesRequest:
    return QuantSeriesRequest(
        SCRIPT_VERSION,
        interval,
        datetime.combine(
            end_date - timedelta(days=_LOOKBACK_DAYS[interval]),
            time.min,
            UTC,
        ),
        datetime.combine(end_date, time.max, UTC),
        SCRIPT,
        SERIES_NAMES,
    )
