from __future__ import annotations

from stock_toolbox.infrastructure.providers.catalog import (
    list_provider_descriptors,
    provider_development_prompt,
)


def test_catalog_exposes_longbridge_and_futu_as_builtin_providers() -> None:
    providers = list_provider_descriptors()

    assert [provider.provider_id for provider in providers] == [
        "longbridge",
        "futu",
    ]
    assert [provider.display_name for provider in providers] == ["长桥", "富途"]
    assert all(provider.builtin for provider in providers)


def test_provider_development_prompt_is_repository_native_and_executable() -> None:
    prompt = provider_development_prompt()

    for heading in (
        "【先填写】",
        "【第一阶段：只做调查和计划】",
        "【第二阶段：按 TDD 实施】",
        "【强制工程契约】",
        "【完成门槛】",
        "【最终交付报告】",
    ):
        assert heading in prompt

    for requirement in (
        "供应商名称",
        "官方开发文档",
        "认证方式与只读权限",
        "官方 SDK",
        "LongbridgeProvider",
        "FutuProvider",
        "DailyBarsProviderPort",
        "ScreeningMarketDataPort",
        "QuantMarketDataPort",
        "ProviderDescriptor",
        "600 只股票",
        "候选供应商",
        "原子切换",
        "真实只读 smoke",
        "/Applications/EquityLens.app",
    ):
        assert requirement in prompt


def test_provider_development_prompt_rejects_unsafe_or_fake_integrations() -> None:
    prompt = provider_development_prompt()

    for requirement in (
        "禁止申请或调用资产、账户、持仓、订单和交易权限",
        "不得读取 AI API Key",
        "不得创建第二套行情领域模型",
        "不得修改 RS、拐点筛选或极值偏离算法",
        "不得伪造服务端量化能力",
        "不得把 Mock 通过当作真实供应商已经可用",
        "不得覆盖用户已有修改",
    ):
        assert requirement in prompt

    assert "所有供应商都必须单批最多 100 个标的" not in prompt
    assert "所有供应商都必须单页最多 200 根" not in prompt
