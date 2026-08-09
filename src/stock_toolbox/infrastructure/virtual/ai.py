"""Deterministic AI eligibility and business classifications."""

from __future__ import annotations

from decimal import Decimal

from stock_toolbox.core.operations.registry import OperationControl
from stock_toolbox.core.securities.models import (
    AIClassification,
    AICompanyAnalysis,
    ProviderProfile,
    StoredClassification,
)

_CLASSIFICATIONS = {
    "IREN.US": ("AI 数据中心", "比特币矿业"),
    "NVDA.US": ("半导体", "AI 基础设施"),
    "AMD.US": ("半导体", "AI 基础设施"),
    "AAPL.US": ("消费科技", "数字服务"),
    "MSFT.US": ("云计算", "企业软件", "AI 基础设施"),
}


class VirtualAI:
    def analyze_company(
        self,
        profile: ProviderProfile,
        existing: tuple[StoredClassification, ...],
        *,
        operation_control: OperationControl,
    ) -> AICompanyAnalysis:
        if operation_control.cancellation_requested():
            raise RuntimeError("canceled")
        reliable_types = {
            hint.normalized_type
            for hint in profile.asset_hints
            if hint.reliability == "reliable"
        }
        excluded = reliable_types & {
            "ETF",
            "LEVERAGED_ETF",
            "INVERSE_ETF",
            "REIT",
            "FUND",
            "CRYPTO",
        }
        if excluded:
            return AICompanyAnalysis(False, min(excluded), ())
        by_name = {
            item.normalized_name: item.id for item in existing
        }
        names = _CLASSIFICATIONS.get(profile.symbol, ("科技",))
        proposals = tuple(
            AIClassification(
                name,
                by_name.get(name.casefold()),
                Decimal("0.90") - Decimal(index) * Decimal("0.05"),
            )
            for index, name in enumerate(names[:3])
        )
        return AICompanyAnalysis(True, "COMMON_STOCK", proposals)
