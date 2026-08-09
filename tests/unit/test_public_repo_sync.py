from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_public_repo import PublicRepoViolation, check_public_repo
from scripts.sync_public_repo import sync_public_repo


def test_sync_public_repo_copies_manifest_and_preserves_git(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "public"
    (source / "src").mkdir(parents=True)
    (source / "src" / "app.py").write_text("PRODUCT = 'EquityLens'\n", encoding="utf-8")
    (source / "README.md").write_text("# EquityLens\n", encoding="utf-8")
    manifest = source / "scripts" / "public_manifest.txt"
    manifest.parent.mkdir()
    manifest.write_text("README.md\nsrc/\n", encoding="utf-8")
    (destination / ".git").mkdir(parents=True)
    (destination / ".git" / "config").write_text("keep", encoding="utf-8")
    (destination / "stale.txt").write_text("remove", encoding="utf-8")

    copied = sync_public_repo(source, destination, manifest)

    assert copied == ("README.md", "src/app.py")
    assert (destination / ".git" / "config").read_text(encoding="utf-8") == "keep"
    assert not (destination / "stale.txt").exists()
    assert (destination / "src" / "app.py").is_file()


def test_public_repo_check_rejects_user_state_and_real_secret(tmp_path: Path) -> None:
    (tmp_path / "RSRadar.sqlite3").write_bytes(b"SQLite format 3")
    (tmp_path / "config.txt").write_text(
        "home=/Users/" + "felix/private\napi_key=sk-" + "live-0123456789abcdefghijklmnop\n",
        encoding="utf-8",
    )

    with pytest.raises(PublicRepoViolation) as error:
        check_public_repo(tmp_path)

    message = str(error.value)
    assert "database" in message
    assert "private macOS path" in message
    assert "secret-like token" in message


def test_public_repo_check_allows_redaction_test_fixtures(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_redaction.py").write_text(
        'FAKE = "sk-12345678901234567890"\n',
        encoding="utf-8",
    )

    assert check_public_repo(tmp_path) == ()
