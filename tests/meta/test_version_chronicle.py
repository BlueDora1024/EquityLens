from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_version_chronicle import check_version_chronicle

pytestmark = pytest.mark.fast


def test_chronicle_covers_every_reachable_commit() -> None:
    if not Path("docs/development/VERSION_CHRONICLE.md").exists():
        pytest.skip("the public source mirror omits the private repository chronicle")
    assert check_version_chronicle(
        repo=Path("."),
        chronicle=Path("docs/development/VERSION_CHRONICLE.md"),
    ) == ()


def test_chronicle_starts_with_unreleased() -> None:
    if not Path("docs/development/VERSION_CHRONICLE.md").exists():
        pytest.skip("the public source mirror omits the private repository chronicle")
    text = Path("docs/development/VERSION_CHRONICLE.md").read_text(
        encoding="utf-8"
    )

    assert text.index("## Unreleased") < text.index("## 0.9.4")
    assert text.count("<!-- unreleased-after:") == 1
