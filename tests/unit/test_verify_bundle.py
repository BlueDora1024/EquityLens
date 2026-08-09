from __future__ import annotations

import pytest

from scripts.verify_bundle import (
    VERSION,
    _missing_required_modules,
    _verify_bundle_footprint,
    _write_manifest,
)


def test_bundle_verification_only_writes_a_manifest_when_requested(tmp_path) -> None:
    bundle = tmp_path / "EquityLens.app"
    bundle.mkdir()
    manifest = {"version": "test"}

    _write_manifest(bundle, manifest, enabled=False)
    assert list(tmp_path.glob("*-manifest.json")) == []

    _write_manifest(bundle, manifest, enabled=True)
    output = tmp_path / f"EquityLens-v{VERSION}-manifest.json"
    assert output.is_file()


def test_bundle_footprint_rejects_unused_heavy_qt_framework(tmp_path) -> None:
    bundle = tmp_path / "EquityLens.app"
    framework = (
        bundle
        / "Contents/Frameworks/PySide6/Qt/lib/QtWebEngineCore.framework"
    )
    framework.mkdir(parents=True)

    with pytest.raises(SystemExit, match="unused heavyweight"):
        _verify_bundle_footprint(bundle)


def test_bundle_footprint_does_not_count_framework_symlinks_twice(tmp_path) -> None:
    bundle = tmp_path / "EquityLens.app"
    binary = bundle / "Contents/Frameworks/QtCore"
    binary.parent.mkdir(parents=True)
    with binary.open("wb") as stream:
        stream.truncate(160 * 1024 * 1024)
    binary.with_name("QtCore-current").symlink_to(binary.name)

    _verify_bundle_footprint(bundle)


def test_bundle_requires_embedded_futu_and_yahoo() -> None:
    assert _missing_required_modules(
        {"futu", "yfinance", "stock_toolbox"}
    ) == ()
    assert _missing_required_modules({"stock_toolbox"}) == (
        "futu",
        "yfinance",
    )
