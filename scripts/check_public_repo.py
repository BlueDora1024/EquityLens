#!/usr/bin/env python3
"""Fail closed when a public source tree contains local state or secrets."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_FORBIDDEN_NAMES = {".DS_Store", ".env", ".env.local", "id_rsa", "id_ed25519"}
_FORBIDDEN_DIRS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
_DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".plist",
    ".py",
    ".qml",
    ".sh",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_SECRET = re.compile(r"\bsk-(?!test-)(?!12345678901234567890\b)[A-Za-z0-9_-]{20,}\b")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PRIVATE_MAC_PATH = re.compile(r"/" + r"Users/(?!runner(?:/|\b))[^/\s'\"]+")


class PublicRepoViolation(RuntimeError):
    """Raised when the public repository is not safe to publish."""


def check_public_repo(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    violations: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        if any(
            part in _FORBIDDEN_DIRS or part.endswith(".egg-info")
            for part in relative.parts
        ):
            continue
        if not path.is_file():
            continue
        if path.name in _FORBIDDEN_NAMES:
            violations.append(f"forbidden file: {relative}")
        if path.suffix.lower() in _DATABASE_SUFFIXES:
            violations.append(f"database: {relative}")
        if path.suffix.lower() == ".log":
            violations.append(f"log file: {relative}")
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _PRIVATE_KEY.search(content):
            violations.append(f"private key: {relative}")
        if _SECRET.search(content):
            violations.append(f"secret-like token: {relative}")
        if _PRIVATE_MAC_PATH.search(content):
            violations.append(f"private macOS path: {relative}")
    if violations:
        raise PublicRepoViolation("\n".join(sorted(set(violations))))
    return ()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    arguments = parser.parse_args()
    check_public_repo(arguments.root)
    print(f"public_repo_check=passed root={arguments.root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
