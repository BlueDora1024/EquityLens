"""Server-side corrected extreme-deviation indicator definition."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from stock_toolbox.core.market_data.models import CandleInterval
from stock_toolbox.core.market_data.quant import QuantSeriesRequest

SCRIPT_VERSION = "extreme-deviation-original-v4"
SUPPORTED_INTERVALS = (
    CandleInterval.MIN_30,
    CandleInterval.MIN_60,
    CandleInterval.DAY,
    CandleInterval.WEEK,
)
SERIES_NAMES = (
    "open",
    "high",
    "low",
    "close",
    "buy_anchor",
    "sell_anchor",
    "buy_raw",
    "sell_raw",
    "range_position",
    "buy_deviation",
    "sell_deviation",
    "buy_trigger_age",
    "sell_trigger_age",
)
SCRIPT = """
indicator("Extreme Deviation Corrected", calc_bars_count: 650);
let hi500 = ta.ema(ta.highest(high, 500), 21);
let hi250 = ta.ema(ta.highest(high, 250), 21);
let hi90 = ta.ema(ta.highest(high, 90), 21);
let lo500 = ta.ema(ta.lowest(low, 500), 21);
let lo250 = ta.ema(ta.lowest(low, 250), 21);
let lo90 = ta.ema(ta.lowest(low, 90), 21);
let inst7 = ta.ema((lo500 * 0.96 + lo250 * 0.96 + lo90 * 0.96 + hi500 * 0.558 + hi250 * 0.558 + hi90 * 0.558) / 6.0, 21);
let inst8 = ta.ema((lo500 * 1.25 + lo250 * 1.23 + lo90 * 1.2 + hi500 * 0.55 + hi250 * 0.55 + hi90 * 0.65) / 6.0, 21);
let inst9 = ta.ema((lo500 * 1.3 + lo250 * 1.3 + lo90 * 1.3 + hi500 * 0.68 + hi250 * 0.68 + hi90 * 0.68) / 6.0, 21);
let buy_anchor = ta.ema((inst7 * 3.0 + inst8 * 2.0 + inst9) / 6.0 * 1.738, 21);
let sell_anchor = buy_anchor;
let buy_den = ta.rma(math.max(low - low[1], 0.0), 3);
let sell_den = ta.rma(math.max(high - high[1], 0.0), 3);
let buy_pressure = math.min(1000000.0, ta.rma(math.abs(low - low[1]), 3) / math.max(buy_den, 0.000000000001) * 100.0);
let sell_pressure = math.min(1000000.0, ta.rma(math.abs(high - high[1]), 3) / math.max(sell_den, 0.000000000001) * 100.0);
let buy_instd = ta.ema(close * 1.35 <= buy_anchor ? buy_pressure * 10.0 : buy_pressure / 10.0, 3);
let sell_instd = ta.ema(close * 0.65 >= sell_anchor ? sell_pressure * 10.0 : sell_pressure / 10.0, 3);
let low30 = ta.lowest(low, 30);
let high30 = ta.highest(high, 30);
let buy_trigger = low <= low30;
let sell_trigger = high >= high30;
let buy_raw = ta.ema(buy_trigger ? (buy_instd + ta.highest(buy_instd, 30) * 2.0) / 2.0 : 0.0, 3) / 0.618;
let sell_raw = ta.ema(sell_trigger ? (sell_instd + ta.lowest(sell_instd, 30) * 2.0) / 2.0 : 0.0, 3) / 0.618;
let width = high30 - low30;
let range_position = width <= 0.0 ? 0.5 : math.max(0.0, math.min(1.0, (close - low30) / width));
let buy_threshold = close * 1.35;
let buy_deviation = math.max(0.0, buy_anchor / buy_threshold - 1.0);
let sell_deviation = math.max(0.0, buy_threshold / sell_anchor - 1.0);
plot(open, "open");
plot(high, "high");
plot(low, "low");
plot(close, "close");
plot(buy_anchor, "buy_anchor");
plot(sell_anchor, "sell_anchor");
plot(buy_raw, "buy_raw");
plot(sell_raw, "sell_raw");
plot(range_position, "range_position");
plot(buy_deviation, "buy_deviation");
plot(sell_deviation, "sell_deviation");
plot(ta.bars_since(buy_trigger), "buy_trigger_age");
plot(ta.bars_since(sell_trigger), "sell_trigger_age");
""".strip()

_LOOKBACK_DAYS = {
    CandleInterval.MIN_30: 150,
    CandleInterval.MIN_60: 300,
    CandleInterval.DAY: 1_100,
    CandleInterval.WEEK: 5_500,
}


def request_for(
    interval: CandleInterval,
    end_date: date,
) -> QuantSeriesRequest:
    if interval not in SUPPORTED_INTERVALS:
        raise ValueError(
            f"unsupported extreme-deviation interval: {interval.value}"
        )
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
        # Each visible score needs its own trailing 100-point percentile window.
        # Retain 199 points to draw the latest 100 normalized scores in one request.
        retain_last=199,
    )
