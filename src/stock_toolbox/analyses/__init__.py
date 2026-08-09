"""Built-in analysis module contracts and registration."""

from stock_toolbox.analyses.contracts import (
    AnalysisDescriptor,
    AnalysisModule,
    DataRequirements,
)
from stock_toolbox.analyses.registry import AnalysisRegistry

__all__ = [
    "AnalysisDescriptor",
    "AnalysisModule",
    "AnalysisRegistry",
    "DataRequirements",
]
