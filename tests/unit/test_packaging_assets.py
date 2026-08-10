from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_product_and_rs_tool_icons_are_release_ready_and_distinct() -> None:
    assets = ROOT / "packaging" / "assets"
    pairs = (
        (
            assets / "stock-analysis-toolbox-icon.svg",
            assets / "StockAnalysisToolbox-1024.png",
            assets / "StockAnalysisToolbox.icns",
        ),
        (
            assets / "rs-strength-icon.svg",
            assets / "RSStrength-1024.png",
            assets / "RSStrength.icns",
        ),
    )
    for svg, png, icns in pairs:
        assert svg.read_text(encoding="utf-8").startswith("<svg")
        assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert icns.read_bytes().startswith(b"icns")
    assert pairs[0][1].read_bytes() != pairs[1][1].read_bytes()


def test_gui_spec_uses_the_release_icon() -> None:
    spec = (ROOT / "packaging" / "stock-toolbox.spec").read_text(encoding="utf-8")

    assert 'icon=str(ROOT / "packaging/assets/StockAnalysisToolbox.icns")' in spec
    assert 'bundle_identifier="com.equitylens.desktop"' in spec
    assert '"CFBundleDisplayName": "EquityLens"' in spec
    assert 'TARGET_ARCH = os.environ.get("EQUITYLENS_TARGET_ARCH")' in spec
    assert 'RELEASE_TAG = os.environ.get("EQUITYLENS_RELEASE_TAG")' in spec
    assert 'GIT_SHA = os.environ.get("EQUITYLENS_GIT_SHA")' in spec
    assert '"EquityLensReleaseTag": RELEASE_TAG' in spec
    assert '"EquityLensGitSHA": GIT_SHA' in spec
    assert '"stock_toolbox/desktop/resources"' in spec
    assert '"stock_toolbox/desktop_qml/qml"' in spec


def test_qml_sources_are_in_python_package_data() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"desktop_qml/qml/*.qml"' in pyproject
    assert '"desktop_qml/qml/components/*.qml"' in pyproject


def test_futu_sdk_is_pinned_and_bundled_in_gui_and_cli() -> None:
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "futu-api==10.9.6908" in project["project"]["dependencies"]

    for name in ("stock-toolbox.spec", "stock-toolbox-cli.spec"):
        spec = (ROOT / "packaging" / name).read_text(encoding="utf-8")
        assert '"futu"' in spec
        assert 'collect_data_files("futu", includes=["VERSION.txt"])' in spec
        assert "FUTU_DATA" in spec

    verifier = (ROOT / "scripts" / "verify_bundle.py").read_text(
        encoding="utf-8"
    )
    assert 'frozenset({"futu", "yfinance"})' in verifier
    assert '"futu-api"' in verifier
