from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dual_provider_product_and_setup_boundaries_are_documented() -> None:
    product = read("docs/product/README.md")
    first_run = read("docs/technical/FIRST_RUN_AND_SETTINGS.md")
    integrations = read("docs/technical/INTEGRATIONS.md")

    assert "Futu OpenD" in product
    assert "只能启用一个" in first_run
    assert "Futu OpenD" in integrations
    assert "不接入交易" in integrations


def test_futu_quota_and_algorithm_routing_are_documented() -> None:
    algorithms = read("docs/technical/ALGORITHMS.md")
    architecture = read("docs/technical/ARCHITECTURE.md")
    testing = read("docs/development/TESTING.md")

    assert "最近 7 天" in algorithms
    assert "Longbridge Quant" in architecture
    assert "富途本地算法" in architecture
    assert "RUN_LIVE_FUTU=1" in testing
