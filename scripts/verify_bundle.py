#!/usr/bin/env python3
"""Fail-closed structural checks for the local macOS application bundle."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import plistlib
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
VERSION = str(PROJECT["project"]["version"])
MAX_BUNDLE_BYTES = 300 * 1024 * 1024
FORBIDDEN_QT_FRAMEWORKS = {
    "Qt3DCore.framework",
    "QtMultimedia.framework",
    "QtWebEngineCore.framework",
}
REQUIRED_PYTHON_MODULES = frozenset({"futu", "yfinance"})


def _architecture(path: Path) -> str:
    return subprocess.run(
        ["file", "-b", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_manifest(
    bundle: Path,
    manifest: dict[str, object],
    *,
    enabled: bool,
) -> None:
    if not enabled:
        return
    output = bundle.parent / f"EquityLens-v{VERSION}-manifest.json"
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_bundle_footprint(bundle: Path) -> None:
    size = sum(
        path.stat().st_size
        for path in bundle.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    if size > MAX_BUNDLE_BYTES:
        raise SystemExit("bundle exceeds the 300 MiB footprint budget")
    frameworks = bundle / "Contents/Frameworks/PySide6/Qt/lib"
    included = {path.name for path in frameworks.glob("Qt*.framework")}
    if included & FORBIDDEN_QT_FRAMEWORKS:
        raise SystemExit("bundle contains unused heavyweight Qt frameworks")


def _missing_required_modules(available: set[str]) -> tuple[str, ...]:
    return tuple(sorted(REQUIRED_PYTHON_MODULES - available))


def _verify_embedded_modules(executable: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader  # type: ignore[import-untyped]

    archive = CArchiveReader(str(executable))
    python_archive = archive.open_embedded_archive("PYZ.pyz")
    missing = _missing_required_modules(set(python_archive.toc))
    if missing:
        raise SystemExit(
            "bundle is missing required Python modules: "
            + ", ".join(missing)
        )


def main() -> int:
    arguments = sys.argv[1:]
    write_manifest = bool(arguments and arguments[0] == "--write-manifest")
    if write_manifest:
        arguments = arguments[1:]
    if len(arguments) != 1:
        raise SystemExit(
            "usage: verify_bundle.py [--write-manifest] <EquityLens.app>"
        )
    bundle = Path(arguments[0]).resolve()
    gui = bundle / "Contents/MacOS/EquityLens"
    cli = bundle / "Contents/MacOS/equitylens-cli"
    compatibility_cli = bundle / "Contents/MacOS/stock-toolbox"
    legacy_cli = bundle / "Contents/MacOS/rs-radar-cli"
    plist_path = bundle / "Contents/Info.plist"
    required = (gui, cli, compatibility_cli, legacy_cli, plist_path)
    if not bundle.is_dir() or not all(item.is_file() for item in required):
        raise SystemExit("bundle structure is incomplete")
    with plist_path.open("rb") as stream:
        plist = plistlib.load(stream)
    if (
        plist.get("CFBundleIdentifier") != "com.equitylens.desktop"
        or plist.get("CFBundleDisplayName") != "EquityLens"
        or plist.get("CFBundleShortVersionString") != VERSION
    ):
        raise SystemExit("bundle identity is invalid")
    icon_name = plist.get("CFBundleIconFile")
    if not isinstance(icon_name, str) or not icon_name:
        raise SystemExit("bundle icon declaration is missing")
    if not icon_name.endswith(".icns"):
        icon_name += ".icns"
    if not (bundle / "Contents" / "Resources" / icon_name).is_file():
        raise SystemExit("bundle icon resource is missing")
    subprocess.run(
        [
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            "--verbose=2",
            str(bundle),
        ],
        check=True,
    )
    forbidden = {".env", "tests", "docs", ".git", "rs-radar.sqlite3"}
    names = {item.name for item in bundle.rglob("*")}
    if names & forbidden:
        raise SystemExit("bundle contains forbidden source or user artifacts")
    _verify_bundle_footprint(bundle)
    architectures = {
        "gui": _architecture(gui),
        "cli": _architecture(cli),
    }
    expected_arch = os.environ.get("EQUITYLENS_TARGET_ARCH") or platform.machine()
    if expected_arch not in {"arm64", "x86_64"}:
        raise SystemExit(f"unsupported expected architecture: {expected_arch}")
    if any(expected_arch not in value for value in architectures.values()):
        raise SystemExit(f"bundle is not {expected_arch}")
    _verify_embedded_modules(cli)
    manifest = {
        "schema_version": "bundle-manifest-v1",
        "bundle_identifier": plist["CFBundleIdentifier"],
        "version": plist["CFBundleShortVersionString"],
        "build_host": platform.platform(),
        "python": platform.python_version(),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
        ).stdout.strip(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in (
                "httpx",
                "futu-api",
                "longbridge",
                "PyInstaller",
                "PySide6",
                "pydantic",
                "yfinance",
            )
        },
        "embedded_modules": sorted(REQUIRED_PYTHON_MODULES),
        "architectures": architectures,
        "gui_sha256": hashlib.sha256(gui.read_bytes()).hexdigest(),
        "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
    }
    _write_manifest(bundle, manifest, enabled=write_manifest)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
