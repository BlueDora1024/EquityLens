"""Stable contracts implemented by every built-in analysis tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DataRequirements:
    """Provider-independent inputs required by an analysis."""

    daily_bars: bool = False
    ohlc_bars: bool = False
    quant_series: bool = False
    security_snapshots: bool = False
    company_profiles: bool = False
    trading_calendar: bool = False


@dataclass(frozen=True, slots=True)
class AnalysisDescriptor:
    """Identity and navigation metadata for one analysis tool."""

    analysis_id: str
    display_name: str
    version: str
    icon_resource: str
    requirements: DataRequirements


class AnalysisModule(Protocol):
    """A complete built-in analysis module."""

    @property
    def descriptor(self) -> AnalysisDescriptor: ...
