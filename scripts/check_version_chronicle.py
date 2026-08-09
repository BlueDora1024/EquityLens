#!/usr/bin/env python3
"""Verify that the version chronicle covers every reachable commit once."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

_RANGE = re.compile(
    r"<!-- commits: ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40}) -->"
)
_UNRELEASED = re.compile(r"<!-- unreleased-after: ([0-9a-f]{7,40}) -->")


def check_version_chronicle(
    *,
    repo: Path,
    chronicle: Path,
) -> tuple[str, ...]:
    commits = _commits(repo)
    positions = {commit: index for index, commit in enumerate(commits)}
    text = chronicle.read_text(encoding="utf-8")
    assigned: Counter[str] = Counter()
    issues: list[str] = []

    for start_ref, end_ref in _RANGE.findall(text):
        start = _resolve(repo, start_ref)
        end = _resolve(repo, end_ref)
        if start not in positions or end not in positions:
            issues.append(f"unknown range: {start_ref}..{end_ref}")
            continue
        start_index = positions[start]
        end_index = positions[end]
        if start_index > end_index:
            issues.append(f"reversed range: {start_ref}..{end_ref}")
            continue
        assigned.update(commits[start_index : end_index + 1])

    markers = _UNRELEASED.findall(text)
    if len(markers) != 1:
        issues.append("chronicle must contain exactly one unreleased-after marker")
    else:
        marker = _resolve(repo, markers[0])
        if marker not in positions:
            issues.append(f"unknown unreleased marker: {markers[0]}")
        else:
            assigned.update(commits[positions[marker] + 1 :])

    issues.extend(
        f"uncovered commit: {commit}"
        for commit in commits
        if assigned[commit] == 0
    )
    issues.extend(
        f"multiply assigned commit: {commit}"
        for commit in commits
        if assigned[commit] > 1
    )
    return tuple(issues)


def _commits(repo: Path) -> tuple[str, ...]:
    output = subprocess.run(
        ["git", "rev-list", "--reverse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return tuple(line for line in output.splitlines() if line)


def _resolve(repo: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ref


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    issues = check_version_chronicle(
        repo=repo,
        chronicle=repo / "docs/development/VERSION_CHRONICLE.md",
    )
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print("Version chronicle covers every reachable commit exactly once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
