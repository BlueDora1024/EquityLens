from __future__ import annotations

import hashlib
import plistlib
import zipfile
from pathlib import Path

import pytest

from stock_toolbox.infrastructure.updates.installer import (
    checksum_matches,
    find_single_app_bundle,
    replacement_script,
    safe_extract_zip,
    validate_bundle_identity,
)


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "app.zip"
    archive.write_bytes(b"payload")
    assert checksum_matches(archive, hashlib.sha256(b"payload").hexdigest())
    assert not checksum_matches(archive, "0" * 64)


def test_zip_slip_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="unsafe archive path"):
        safe_extract_zip(archive, tmp_path / "out")


def test_bundle_identity_validates_version_and_identifier(tmp_path: Path) -> None:
    app = tmp_path / "EquityLens.app"
    info = app / "Contents/Info.plist"
    info.parent.mkdir(parents=True)
    with info.open("wb") as stream:
        plistlib.dump(
            {
                "CFBundleIdentifier": "com.equitylens.desktop",
                "CFBundleShortVersionString": "1.1.0",
            },
            stream,
        )
    assert validate_bundle_identity(app, "1.1.0") is None
    with pytest.raises(ValueError, match="version"):
        validate_bundle_identity(app, "1.2.0")


def test_archive_must_contain_exactly_one_equitylens_app(tmp_path: Path) -> None:
    (tmp_path / "EquityLens.app").mkdir()
    assert find_single_app_bundle(tmp_path).name == "EquityLens.app"


def test_replacement_script_preserves_user_data_and_has_rollback() -> None:
    script = replacement_script(
        target=Path("/Applications/EquityLens.app"),
        staged=Path("/tmp/update/EquityLens.app"),
        parent_pid=123,
    )
    assert "Application Support" not in script
    assert "backup" in script
    assert 'open "$target"' in script
    assert "mv \"$backup\" \"$target\"" in script

