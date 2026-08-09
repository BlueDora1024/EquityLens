import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import stock_toolbox.analyses.turning_point.domain.engine as engine_module
from stock_toolbox.analyses.turning_point.domain.engine import (
    TurningPointEngine,
    _divergence_state_from_macd,
    ema,
    left_cd_indexes,
    recent_cross_indexes,
)
from stock_toolbox.analyses.turning_point.domain.models import (
    ScreeningDecision,
    TurningPointTradeSide,
)
from stock_toolbox.core.market_data.models import CandleInterval, MarketCandle

pytestmark = pytest.mark.fast


def _candles(count: int, *, close: Decimal = Decimal(100)) -> tuple[MarketCandle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        MarketCandle(
            start + timedelta(minutes=30 * index),
            close,
            close + Decimal(1),
            close - Decimal(1),
            close,
            1000,
        )
        for index in range(count)
    )


def test_ema_matches_adjust_false_recurrence() -> None:
    assert ema((1.0, 2.0, 3.0), 3) == pytest.approx((1.0, 1.5, 2.25))


def test_engine_rejects_insufficient_history() -> None:
    result = TurningPointEngine().screen("NVDA.US", _candles(118))
    assert result.decision is ScreeningDecision.FAILED
    assert result.reason == "insufficient_bars"


def test_engine_rejects_non_finite_or_non_positive_prices() -> None:
    with pytest.raises(ValueError, match="OHLC"):
        MarketCandle(
            datetime(2026, 1, 1, tzinfo=UTC),
            Decimal(100),
            Decimal(101),
            Decimal(99),
            Decimal(0),
            1000,
        )


def test_flat_series_is_a_valid_non_match() -> None:
    result = TurningPointEngine().screen("NVDA.US", _candles(220))
    assert result.decision is ScreeningDecision.NOT_MATCHED
    assert result.reason == "NO_CD_SIGNAL"


def test_recent_cross_window_checks_five_complete_transitions() -> None:
    closes = (1.0, 1.0, 1.0, 1.0, 1.0, 3.0, 3.0, 3.0, 3.0, 3.0)
    average = (2.0,) * len(closes)

    assert recent_cross_indexes(closes, average, lookback=5) == (5,)


def test_left_cd_uses_exact_one_percent_dif_contraction_boundary() -> None:
    assert TurningPointTradeSide.RIGHT_CONFIRMED.value == "RIGHT_CONFIRMED"
    assert left_cd_indexes(
        (False, True, True, True),
        (-2.0, -2.0, -1.98, -1.90),
    ) == (2,)
    assert left_cd_indexes(
        (False, True, True),
        (-2.0, -2.0, -1.981),
    ) == ()


def test_left_cd_only_emits_when_contraction_first_becomes_true() -> None:
    assert left_cd_indexes(
        (False, True, True, True, True),
        (-2.0, -2.0, -1.98, -1.90, -1.80),
    ) == (2,)


def test_left_cd_rejects_misaligned_series() -> None:
    with pytest.raises(ValueError, match="invalid CD series"):
        left_cd_indexes((True,), (-1.0, -0.9))


def test_recent_signal_window_is_scaled_to_each_interval() -> None:
    recent_window_bars = getattr(engine_module, "recent_window_bars", None)

    assert recent_window_bars is not None
    assert {
        interval: recent_window_bars(interval)
        for interval in CandleInterval
    } == {
        CandleInterval.MIN_30: 65,
        CandleInterval.MIN_60: 35,
        CandleInterval.MIN_120: 20,
        CandleInterval.MIN_240: 10,
        CandleInterval.DAY: 20,
        CandleInterval.WEEK: 8,
    }


def test_left_side_matches_ccc_start_before_dif_enhancement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    size = 130
    signal_index = 80
    ccc = tuple(index >= signal_index for index in range(size))
    kinds = tuple(
        "RECENT_BULLISH_DIVERGENCE" if index == signal_index else None
        for index in range(size)
    )
    monkeypatch.setattr(
        engine_module,
        "_divergence_state_from_macd",
        lambda *_args: (ccc, kinds),
    )
    timestamps = tuple(
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=30 * index)
        for index in range(size)
    )

    result = TurningPointEngine().screen_derived(
        "IREN.US",
        timestamps,
        (101.0,) * size,
        (100.0,) * size,
        (102.0,) * size,
        (103.0,) * size,
        (-1.0,) * size,
        (-0.5,) * size,
        1.0,
        TurningPointTradeSide.LEFT_CD,
        signal_lookback=65,
    )

    assert result.decision is ScreeningDecision.MATCHED
    assert result.signal_at == timestamps[signal_index]
    assert result.enhanced_at is None


def test_right_side_uses_cd_time_trend_and_later_high_ema26_cross(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    size = 130
    signal_index = 100
    cross_index = 110
    ccc = tuple(index == signal_index for index in range(size))
    kinds = tuple(
        "RECENT_BULLISH_DIVERGENCE" if index == signal_index else None
        for index in range(size)
    )
    monkeypatch.setattr(
        engine_module,
        "_divergence_state_from_macd",
        lambda *_args: (ccc, kinds),
    )
    closes = [89.0] * size
    closes[cross_index] = 91.0
    high_ema26 = [90.0] * size
    high_ema89 = [80.0] * size
    high_ema89[signal_index] = 100.0
    timestamps = tuple(
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
        for index in range(size)
    )

    result = TurningPointEngine().screen_derived(
        "IREN.US",
        timestamps,
        (101.0,) * size,
        closes,
        high_ema26,
        high_ema89,
        (-1.0,) * size,
        (-0.5,) * size,
        1.0,
        TurningPointTradeSide.RIGHT_CONFIRMED,
        signal_lookback=35,
    )

    assert result.decision is ScreeningDecision.MATCHED
    assert result.signal_at == timestamps[signal_index]
    assert result.crossed_at == timestamps[cross_index]


def test_right_side_rejects_confirmation_more_than_twenty_bars_after_cd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    size = 130
    signal_index = 80
    cross_index = 101
    ccc = tuple(index == signal_index for index in range(size))
    kinds = tuple(
        "RECENT_BULLISH_DIVERGENCE" if index == signal_index else None
        for index in range(size)
    )
    monkeypatch.setattr(
        engine_module,
        "_divergence_state_from_macd",
        lambda *_args: (ccc, kinds),
    )
    closes = [89.0] * size
    closes[cross_index] = 91.0
    timestamps = tuple(
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
        for index in range(size)
    )

    result = TurningPointEngine().screen_derived(
        "IREN.US",
        timestamps,
        (101.0,) * size,
        closes,
        (90.0,) * size,
        (100.0,) * size,
        (-1.0,) * size,
        (-0.5,) * size,
        1.0,
        TurningPointTradeSide.RIGHT_CONFIRMED,
        signal_lookback=65,
    )

    assert result.decision is ScreeningDecision.NOT_MATCHED
    assert result.reason == "SIGNAL_EXPIRED"


def test_iren_30m_matches_original_barslast_ref_semantics() -> None:
    """Regression from Longbridge IREN 30m data ending 2026-07-29.

    The chart has two early divergence arrows, but only the first contracts
    enough on the following bar to become the original formula's DXDX/CD.
    """
    rows = (
        (35.48, -1.262755335934777, -0.5500649558068602),
        (35.25, -1.323329967868425, -0.536971375739324),
        (35.924, -1.301941659920502, -0.3953558078747821),
        (35.69, -1.289014163267048, -0.2956006516542993),
        (35.65, -1.267387045794777, -0.2018771333678062),
        (35.96, -1.21127022104249, -0.07171478709058521),
        (35.63, -1.179825184885658, -0.007059771821536831),
        (35.93, -1.117811835362374, 0.09357354178002453),
        (36.36, -1.022185287042284, 0.2278613107361651),
        (36.29, -0.9411994125801826, 0.3118664477282937),
        (32.75, -1.149416184297003, -0.08365367656427747),
        (32.91, -1.286686689952099, -0.2865557502995748),
        (33.92, -1.299001910166744, -0.2489489525830928),
        (34.395, -1.255955408509649, -0.1302847594151224),
        (34.71, -1.182788429621503, 0.01283935868893593),
        (34.165, -1.155460586565312, 0.05399603584105517),
        (34.45, -1.098147198568967, 0.1348982494669961),
        (33.934, -1.081891442177884, 0.1339278097993288),
        (33.733, -1.072860391533276, 0.1215919288708371),
        (33.49, -1.072943068190256, 0.09714126044550131),
        (33.525, -1.057988549124474, 0.101640238861652),
        (34.175, -0.9823633441683697, 0.2023125190190882),
        (33.93, -0.9314619631438674, 0.243292224854474),
        (32.0, -1.034927126578864, 0.02908951838758433),
        (30.965, -1.186759637799121, -0.2196604032423424),
        (31.01, -1.288602663538079, -0.3386771637762069),
        (30.72, -1.376843180415747, -0.4121265580252351),
        (30.521, -1.446161611810894, -0.4406107366524221),
        (30.635, -1.474896432854827, -0.398464302992231),
        (30.575, -1.48538785751483, -0.3355577218497898),
        (30.695, -1.467107488145729, -0.2391975864892695),
        (31.06, -1.406949278661145, -0.09510493401608144),
        (30.82, -1.362928467484778, -0.00565064933067827),
        (31.76, -1.237921524625975, 0.1954905891095429),
        (30.375, -1.236358574812087, 0.158893190989855),
        (29.31, -1.306001750031268, 0.015685472441195),
    )
    closes, dif, histogram = zip(*rows, strict=True)

    divergence, _kinds = _divergence_state_from_macd(
        closes,
        dif,
        histogram,
    )
    divergence_starts = tuple(
        index
        for index, active in enumerate(divergence)
        if active and (index == 0 or not divergence[index - 1])
    )

    assert divergence_starts == (11, 25)
    assert left_cd_indexes(divergence, dif) == (13,)


def test_left_cd_matches_without_right_side_trend_or_cross_confirmation() -> None:
    randomizer = random.Random(3)
    closes = [100.0]
    dif: list[float] = []
    histogram: list[float] = []
    current_dif = -2.0
    for index in range(130):
        if index:
            closes.append(max(1.0, closes[-1] + randomizer.uniform(-3.0, 2.7)))
        current_dif += randomizer.uniform(-0.3, 0.35)
        dif.append(current_dif)
        histogram.append(randomizer.uniform(-1.0, 1.0))
    timestamps = tuple(
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=30 * index)
        for index in range(130)
    )
    engine = TurningPointEngine()

    left = engine.screen_derived(
        "NVDA.US",
        timestamps,
        tuple(value + 1.0 for value in closes),
        closes,
        (200.0,) * 130,
        (100.0,) * 130,
        dif,
        histogram,
        1.2,
        TurningPointTradeSide.LEFT_CD,
    )
    right = engine.screen_derived(
        "NVDA.US",
        timestamps,
        tuple(value + 1.0 for value in closes),
        closes,
        (200.0,) * 130,
        (100.0,) * 130,
        dif,
        histogram,
        1.2,
        TurningPointTradeSide.RIGHT_CONFIRMED,
    )

    assert left.decision is ScreeningDecision.MATCHED
    assert left.signal_kind == "CD_LEFT_ENTRY"
    assert left.signal_at == timestamps[124]
    assert left.enhanced_at == timestamps[127]
    assert left.crossed_at is None
    assert right.decision is ScreeningDecision.NOT_MATCHED
    assert right.reason == "TREND_FILTER_NOT_MET"
