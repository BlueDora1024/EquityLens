"""Explicit registry for product-shipped analysis modules."""

from __future__ import annotations

import re

from stock_toolbox.analyses.contracts import AnalysisModule

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class AnalysisRegistry:
    """Validated in-memory registry with deterministic ordering."""

    def __init__(self) -> None:
        self._modules: dict[str, AnalysisModule] = {}

    def register(self, module: AnalysisModule) -> None:
        descriptor = module.descriptor
        if not _ID_PATTERN.fullmatch(descriptor.analysis_id):
            raise ValueError("analysis id must be lower snake case")
        if not descriptor.display_name.strip():
            raise ValueError("display name must not be empty")
        if not _VERSION_PATTERN.fullmatch(descriptor.version):
            raise ValueError("semantic version must use major.minor.patch")
        if not descriptor.icon_resource.strip():
            raise ValueError("icon resource must not be empty")
        analysis_id = descriptor.analysis_id
        if analysis_id in self._modules:
            raise ValueError(f"duplicate analysis module: {analysis_id}")
        self._modules[analysis_id] = module

    def get(self, analysis_id: str) -> AnalysisModule:
        return self._modules[analysis_id]

    def list(self) -> tuple[AnalysisModule, ...]:
        return tuple(self._modules[key] for key in sorted(self._modules))
