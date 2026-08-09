from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast


def test_core_does_not_import_rs_strength() -> None:
    core = Path("src/stock_toolbox/core")
    for path in core.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        for node in imports:
            rendered = ast.unparse(node)
            assert "analyses.rs_strength" not in rendered, (
                f"{path} imports RS-owned code: {rendered}"
            )


def test_product_source_no_longer_uses_legacy_application_namespace() -> None:
    offenders = []
    for path in Path("src/stock_toolbox").rglob("*.py"):
        if "stock_toolbox.application." in path.read_text(encoding="utf-8"):
            offenders.append(str(path))
    assert offenders == []
