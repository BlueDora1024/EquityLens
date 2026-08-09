from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from stock_toolbox.analyses.turning_point.application.backtest import (
    evaluate_signal_indexes,
)
from stock_toolbox.core.market_data.models import MarketCandle


def _candles(count: int) -> tuple[MarketCandle, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        MarketCandle(
            start + timedelta(days=index),
            Decimal(100 + index),
            Decimal(102 + index),
            Decimal(98 + index),
            Decimal(101 + index),
            1000,
        )
        for index in range(count)
    )


def test_backtest_enters_next_open_and_exits_tenth_close() -> None:
    result = evaluate_signal_indexes(_candles(20), (2,))

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_at == _candles(20)[3].timestamp
    assert trade.exit_at == _candles(20)[12].timestamp
    assert trade.return_5 == pytest.approx((108 / 103) - 1)
    assert trade.return_10 == pytest.approx((113 / 103) - 1)
    assert trade.won is True


def test_backtest_skips_overlap_and_excludes_unsettled_signal() -> None:
    result = evaluate_signal_indexes(_candles(20), (2, 4, 15))

    assert len(result.trades) == 1
    assert result.skipped_overlap == 1
    assert result.unsettled == 1
    assert result.win_rate == 1.0


def test_empty_backtest_has_no_misleading_win_rate() -> None:
    result = evaluate_signal_indexes(_candles(20), ())

    assert result.trades == ()
    assert result.win_rate is None
