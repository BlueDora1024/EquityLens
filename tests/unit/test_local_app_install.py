from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_installer_enables_sync_and_replaces_existing_app(tmp_path: Path) -> None:
    source = tmp_path / "dist" / "EquityLens.app"
    payload = source / "Contents" / "Resources" / "version.txt"
    payload.parent.mkdir(parents=True)
    payload.write_text("first", encoding="utf-8")
    install_root = tmp_path / "Applications"
    marker = tmp_path / "support" / "auto-sync-enabled"
    environment = {
        **os.environ,
        "STOCK_TOOLBOX_SOURCE_APP": str(source),
        "STOCK_TOOLBOX_INSTALL_ROOT": str(install_root),
        "STOCK_TOOLBOX_SYNC_MARKER": str(marker),
        "STOCK_TOOLBOX_SKIP_SIGNATURE_VERIFY": "1",
        "STOCK_TOOLBOX_SKIP_BUNDLE_VERIFY": "1",
    }

    subprocess.run(
        ["sh", str(ROOT / "scripts" / "install_app.sh"), "--enable-sync"],
        check=True,
        env=environment,
    )

    installed_payload = (
        install_root
        / "EquityLens.app"
        / "Contents"
        / "Resources"
        / "version.txt"
    )
    assert installed_payload.read_text(encoding="utf-8") == "first"
    assert marker.is_file()

    payload.write_text("second", encoding="utf-8")
    subprocess.run(
        ["sh", str(ROOT / "scripts" / "install_app.sh")],
        check=True,
        env=environment,
    )

    assert installed_payload.read_text(encoding="utf-8") == "second"


def test_installer_removes_old_app_after_verified_replacement(tmp_path: Path) -> None:
    script = (ROOT / "scripts" / "install_app.sh").read_text(encoding="utf-8")

    assert script.index('mv "$STAGE" "$DESTINATION"') < script.index(
        'rm -rf "$OLD_APP"'
    )
    assert 'LEGACY_PRODUCT_APP="$INSTALL_ROOT/股票分析百宝箱.app"' in script
