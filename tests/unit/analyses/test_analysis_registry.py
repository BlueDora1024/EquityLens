from __future__ import annotations

from dataclasses import dataclass

import pytest

from stock_toolbox.analyses.contracts import (
    AnalysisDescriptor,
    AnalysisModule,
    DataRequirements,
)
from stock_toolbox.analyses.registry import AnalysisRegistry

pytestmark = pytest.mark.fast


@dataclass(frozen=True, slots=True)
class _Module:
    descriptor: AnalysisDescriptor


def _module(
    analysis_id: str = "rs_strength",
    *,
    name: str = "RS 强度",
    version: str = "1.0.0",
) -> AnalysisModule:
    return _Module(
        AnalysisDescriptor(
            analysis_id,
            name,
            version,
            "icons/rs-strength.png",
            DataRequirements(daily_bars=True, trading_calendar=True),
        )
    )


def test_registry_rejects_duplicate_ids() -> None:
    registry = AnalysisRegistry()
    registry.register(_module())

    with pytest.raises(ValueError, match="duplicate analysis module"):
        registry.register(_module())


@pytest.mark.parametrize(
    ("analysis_id", "name", "version", "message"),
    (
        ("", "RS 强度", "1.0.0", "analysis id"),
        ("RS Strength", "RS 强度", "1.0.0", "analysis id"),
        ("rs_strength", "", "1.0.0", "display name"),
        ("rs_strength", "RS 强度", "v1", "semantic version"),
    ),
)
def test_registry_rejects_invalid_descriptors(
    analysis_id: str,
    name: str,
    version: str,
    message: str,
) -> None:
    registry = AnalysisRegistry()

    with pytest.raises(ValueError, match=message):
        registry.register(_module(analysis_id, name=name, version=version))


def test_registry_lists_modules_in_stable_id_order() -> None:
    registry = AnalysisRegistry()
    registry.register(_module("zeta", name="Zeta"))
    registry.register(_module("alpha", name="Alpha"))

    assert tuple(item.descriptor.analysis_id for item in registry.list()) == (
        "alpha",
        "zeta",
    )
    assert registry.get("zeta").descriptor.display_name == "Zeta"
