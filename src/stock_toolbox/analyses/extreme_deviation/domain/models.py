"""Immutable values produced by the corrected extreme-deviation formula."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class IndicatorPoint:
    timestamp: datetime
    close: float
    buy_anchor: float
    sell_anchor: float
    buy_raw: float
    sell_raw: float
    range_position: float
    buy_deviation: float
    sell_deviation: float
    buy_trigger_age: int | None
    sell_trigger_age: int | None

    def is_finite(self) -> bool:
        return all(
            math.isfinite(value)
            for value in (
                self.close,
                self.buy_anchor,
                self.sell_anchor,
                self.buy_raw,
                self.sell_raw,
                self.range_position,
                self.buy_deviation,
                self.sell_deviation,
            )
        )
