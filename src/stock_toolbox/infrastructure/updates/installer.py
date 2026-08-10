"""Validate and stage a macOS application replacement without touching user data."""

from __future__ import annotations

import hashlib
import os
import plistlib
import shlex
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def checksum_matches(path: Path, expected: str) -> bool:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().casefold() == expected.casefold()


def safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError("unsafe archive path")
    if sys.platform == "darwin":
        subprocess.run(
            ["ditto", "-x", "-k", str(archive), str(destination)],
            check=True,
            capture_output=True,
        )
    else:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)


def find_single_app_bundle(root: Path) -> Path:
    candidates = [path for path in root.rglob("EquityLens.app") if path.is_dir()]
    if len(candidates) != 1:
        raise ValueError("archive must contain one EquityLens.app")
    return candidates[0]


def validate_bundle_identity(bundle: Path, version: str) -> None:
    info_path = bundle / "Contents/Info.plist"
    if not info_path.is_file():
        raise ValueError("bundle metadata is missing")
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleIdentifier") != "com.equitylens.desktop":
        raise ValueError("bundle identifier is invalid")
    if info.get("CFBundleShortVersionString") != version:
        raise ValueError("bundle version is invalid")


def replacement_script(*, target: Path, staged: Path, parent_pid: int) -> str:
    target_text = shlex.quote(str(target))
    staged_text = shlex.quote(str(staged))
    return f'''#!/bin/zsh
set -eu
target={target_text}
staged={staged_text}
backup="${{target}}.update-backup"
while kill -0 {parent_pid} 2>/dev/null; do sleep 0.2; done
rm -rf "$backup"
mv "$target" "$backup"
if mv "$staged" "$target"; then
  xattr -dr com.apple.quarantine "$target" 2>/dev/null || true
  if codesign --verify --deep --strict "$target" 2>/dev/null; then
    open "$target"
    rm -rf "$backup"
    exit 0
  fi
fi
rm -rf "$target"
mv "$backup" "$target"
open "$target"
exit 1
'''


def stage_update(
    archive: Path,
    expected_sha256: str,
    *,
    version: str,
    target: Path,
) -> tuple[Path, Path]:
    if not checksum_matches(archive, expected_sha256):
        raise ValueError("download checksum mismatch")
    staging_root = Path(tempfile.mkdtemp(prefix="equitylens-update-"))
    extracted = staging_root / "extracted"
    safe_extract_zip(archive, extracted)
    bundle = find_single_app_bundle(extracted)
    validate_bundle_identity(bundle, version)
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(bundle)],
        check=True,
        capture_output=True,
    )
    if not os.access(target.parent, os.W_OK):
        raise PermissionError("application directory is not writable")
    script = staging_root / "install-update.zsh"
    script.write_text(
        replacement_script(target=target, staged=bundle, parent_pid=os.getpid()),
        encoding="utf-8",
    )
    script.chmod(0o700)
    return bundle, script


def launch_replacement(script: Path) -> None:
    subprocess.Popen(
        ["/bin/zsh", str(script)],
        start_new_session=True,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
