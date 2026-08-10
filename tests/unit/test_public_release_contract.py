from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_public_manifest_contains_maintainer_and_release_files() -> None:
    manifest = (ROOT / "scripts/public_manifest.txt").read_text(encoding="utf-8")

    for entry in (
        ".github/",
        "README.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "documentation/",
        "src/",
        "tests/",
    ):
        assert entry in manifest.splitlines()


def test_release_workflow_builds_native_arm_and_intel_artifacts() -> None:
    workflow_path = ROOT / ".github/workflows/release.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "runner: macos-15\n            arch: arm64" in workflow
    assert "runner: macos-15-intel\n            arch: x86_64" in workflow
    assert "permissions:\n  contents: write" in workflow


def test_release_workflow_builds_downloadable_artifacts_for_main_pushes() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "branches: [main]" in workflow
    assert "tags: [\"v*\"]" in workflow
    assert "if: startsWith(github.ref, 'refs/tags/')" in workflow


def test_public_project_identity_is_equitylens() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert project["name"] == "equitylens"
    assert "EquityLens" in readme
    assert "股票分析百宝箱" not in readme


def test_packaged_release_proves_fresh_production_profile_is_empty() -> None:
    acceptance = (ROOT / "scripts/run_packaged_acceptance.sh").read_text(
        encoding="utf-8"
    )

    assert 'Application Support/EquityLens/RSRadar.sqlite3' in acceptance
    assert "SELECT count(*) FROM $table" in acceptance
    assert "global_securities classifications calculation_watchlists analysis_runs" in acceptance
    assert "Application Support/Stock Analysis Toolbox" in acceptance
