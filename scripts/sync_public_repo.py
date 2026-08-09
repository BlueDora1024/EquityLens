#!/usr/bin/env python3
"""Materialize the allowlisted public EquityLens source repository."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

try:
    from scripts.check_public_repo import check_public_repo
except ModuleNotFoundError:  # Direct `python scripts/sync_public_repo.py` execution.
    from check_public_repo import check_public_repo

_IGNORED_PARTS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


def _publishable(path: Path) -> bool:
    return (
        not any(part in _IGNORED_PARTS or part.endswith(".egg-info") for part in path.parts)
        and path.name != ".DS_Store"
    )


def _manifest_entries(source: Path, manifest: Path) -> tuple[str, ...]:
    entries: list[str] = []
    for raw_line in manifest.read_text(encoding="utf-8").splitlines():
        entry = raw_line.strip()
        if not entry or entry.startswith("#"):
            continue
        candidate = (source / entry.rstrip("/")).resolve()
        if source.resolve() not in candidate.parents and candidate != source.resolve():
            raise ValueError(f"manifest path escapes source tree: {entry}")
        if not candidate.exists():
            raise FileNotFoundError(f"manifest entry does not exist: {entry}")
        entries.append(entry)
    return tuple(entries)


def _clear_public_tree(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in destination.iterdir():
        if path.name == ".git":
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def sync_public_repo(source: Path, destination: Path, manifest: Path) -> tuple[str, ...]:
    source = source.resolve()
    destination = destination.resolve()
    entries = _manifest_entries(source, manifest.resolve())
    _clear_public_tree(destination)
    copied: list[str] = []
    for entry in entries:
        relative = Path(entry.rstrip("/"))
        origin = source / relative
        target = destination / relative
        if origin.is_dir():
            for file_path in sorted(
                path for path in origin.rglob("*") if path.is_file() and _publishable(path)
            ):
                file_relative = file_path.relative_to(source)
                output = destination / file_relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, output)
                copied.append(file_relative.as_posix())
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
            copied.append(relative.as_posix())
    check_public_repo(destination)
    return tuple(sorted(copied))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--manifest", type=Path)
    arguments = parser.parse_args()
    source = arguments.source.resolve()
    manifest = arguments.manifest or source / "scripts" / "public_manifest.txt"
    copied = sync_public_repo(source, arguments.destination, manifest)
    print(f"public_repo_sync=passed files={len(copied)} destination={arguments.destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
