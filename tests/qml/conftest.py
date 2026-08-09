from __future__ import annotations

from pathlib import Path

import pytest

from stock_toolbox.composition import StockToolboxApplication, build_application
from stock_toolbox.runtime.environment import RuntimeEnvironment


@pytest.fixture
def scenario_application(tmp_path: Path) -> StockToolboxApplication:
    return build_application(
        RuntimeEnvironment.SCENARIO,
        home=tmp_path,
        scenario_run_id="qml-tests",
    )
