from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast

_GATES = ("fast", "smoke", "batch", "full", "package", "live")


def test_supported_test_gates_have_one_authoritative_entry() -> None:
    script = Path("scripts/test.sh").read_text(encoding="utf-8")
    docs = Path("docs/development/TESTING.md").read_text(encoding="utf-8")

    for gate in _GATES:
        assert re.search(rf"^    {re.escape(gate)}\)$", script, re.MULTILINE)
        assert f"`./scripts/test.sh {gate}" in docs
    assert "tests/qml/test_" not in script
    assert "    release)" not in script


def test_offline_full_gate_explicitly_excludes_external_tests() -> None:
    script = Path("scripts/test.sh").read_text(encoding="utf-8")

    assert '-m "not live and not package"' in script
    assert "RUN_LIVE_YAHOO=1" in script


def test_current_execution_plans_and_obsolete_rs_prototypes_are_separated() -> None:
    plans = Path("docs/superpowers/plans")

    assert plans.is_dir()
    assert tuple(plans.glob("*.md"))
    assert not Path("docs/prototype/rs-radar-flow.html").exists()
    assert not Path("docs/prototype/rs-radar-flow-gallery.html").exists()
    assert Path("docs/product/README.md").is_file()
    assert Path("docs/technical/ARCHITECTURE.md").is_file()


def test_desktop_qml_batch_has_one_documented_entry() -> None:
    script = Path("scripts/test.sh").read_text(encoding="utf-8")
    docs = Path("docs/development/TESTING.md").read_text(encoding="utf-8")

    assert "            desktop-qml)" in script
    assert "`./scripts/test.sh batch desktop-qml`" in docs
